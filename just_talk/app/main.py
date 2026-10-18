"""Desktop application entrypoint and main coordinator."""

from __future__ import annotations

import datetime
import multiprocessing
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# CRITICAL FOR PYINSTALLER & MULTIPROCESSING:
# Must call freeze_support immediately to prevent child processes from re-launching the main app!
multiprocessing.freeze_support()

# CRITICAL FIX FOR WINDOWS TASKBAR PINNING:
# Must set AppUserModelID before initializing any UI/QApplication,
# otherwise Windows binds the window to python.exe and pinning reverts to the Python icon!
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "justtalk.desktop.voiceinput.1.0"
        )
    except Exception as e:
        print(f"[Main] Warning: Could not set AppUserModelID: {e}", file=sys.stderr)

import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt, Signal, Slot, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from ..ai.actions import ActionIntent, ActionRouter
from ..ai.gemini import GeminiFormatter, without_ai_dashes, without_fillers
from ..ai.prompts import (
    EDIT_SELECTION_STYLE,
    GENERATE_STYLE,
    build_edit_selection_prompt,
    build_generate_prompt,
    build_prompt,
)
from ..ai.prompts import speaker_context_block
from ..ai.local_model import LocalModel
from ..ai.providers import MultiProviderFormatter
from ..audio.noise_filter import NoiseFilter
from ..audio.recorder import AudioRecorder
from ..audio.speaker_recognizer import SpeakerRecognizer
from ..audio.voice_match import adapt_profile, decide, profiles_from_records, speech_only
from ..audio.vad import VoiceActivityDetector
from ..config import AppConfig
from ..database.history import HistoryDatabase
from ..security import CredentialManager
from ..shortcuts.manager import ShortcutManager
from ..stt import create_stt_engine_for_config, get_native_stt_engine
from ..stt.model_manager import ModelManager
from ..stt.kriti_engine import KritiEngine
from ..model_lifecycle import ModelLifecycle
from ..profile.learner import Learner
from ..profile.scripts import ROLES_BY_ID, fix_known_mishearings, vocabulary_terms
from ..profile.store import VoiceProfile
from ..language_setup import english_dominant
from ..stt.whisper_engine import WhisperSTTEngine
from ..stt.mac_native_engine import MacNativeSTTEngine
from ..profile.scoring import has_devanagari, language_words, sound_overlap
from ..stt.long_form import EarlyPieces, IncrementalTranscriber
from ..system.audio_ducker import SystemAudioDucker
from ..system.caret_locator import CaretLocator
from ..system.clipboard import ClipboardManager
from ..system.context_detector import detect_context
from ..system.inserter import TextInserter
from ..system.permissions import PermissionsManager
from .main_window import MainWindow
from .onboarding_window import OnboardingWindow
from .overlay import FloatingPillOverlay
from .theme import ThemeManager
from .tray import SystemTrayManager
from .ui_thread import run_on_ui_thread
from .wheel_guard import install_wheel_guard


class AppBridge(QObject):
    """Qt signal bridge to dispatch audio and worker events safely to the main GUI thread.

    CRITICAL THREADING RULE:
    Several event sources (Quartz CGEventTap, PortAudio audio callback, pynput listener)
    fire on non-Qt C-level threads. PySide6 cannot auto-detect QueuedConnection for
    receivers that are not QObjects. ALL cross-thread signals must either:
      (a) connect to @Slot methods on THIS QObject with explicit QueuedConnection, or
      (b) connect to QWidget slots (which are QObjects with thread affinity).
    """

    level_changed = Signal(float)
    partial_transcript = Signal(str)
    state_listening = Signal(bool)
    state_processing = Signal(str)
    state_inserted = Signal()
    state_inserted_offline = Signal()
    state_copied = Signal()
    state_error = Signal(str)

    # Thread-safe recording triggers: emitted from the Quartz/pynput thread,
    # connected to @Slot methods below with explicit QueuedConnection.
    start_recording_requested = Signal(bool)   # bool: is_action_mode
    stop_recording_requested = Signal()
    cancel_recording_requested = Signal()
    action_mode_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._controller = None  # Set after JustTalkApp.__init__

        # Self-connect with EXPLICIT QueuedConnection.
        # Since both sender and receiver are this QObject (main thread affinity),
        # QueuedConnection guarantees the slot runs on the main thread event loop
        # even when emit() is called from a Quartz/PortAudio/pynput C thread.
        self.start_recording_requested.connect(
            self._on_start_recording, Qt.ConnectionType.QueuedConnection
        )
        self.stop_recording_requested.connect(
            self._on_stop_recording, Qt.ConnectionType.QueuedConnection
        )
        self.cancel_recording_requested.connect(
            self._on_cancel_recording, Qt.ConnectionType.QueuedConnection
        )
        self.action_mode_changed.connect(
            self._on_action_mode_changed, Qt.ConnectionType.QueuedConnection
        )

    @Slot(bool)
    def _on_start_recording(self, is_action_mode: bool) -> None:
        """Guaranteed to run on the main Qt thread."""
        if self._controller:
            self._controller.on_start_recording(is_action_mode)

    @Slot()
    def _on_stop_recording(self) -> None:
        """Guaranteed to run on the main Qt thread."""
        if self._controller:
            self._controller.on_stop_recording()

    @Slot()
    def _on_cancel_recording(self) -> None:
        """Guaranteed to run on the main Qt thread."""
        if self._controller:
            self._controller._on_cancel_recording()

    @Slot(bool)
    def _on_action_mode_changed(self, is_action_mode: bool) -> None:
        """Guaranteed to run on the main Qt thread."""
        if self._controller:
            self._controller.on_action_mode_changed(is_action_mode)


class JustTalkApplication(QApplication):
    """
    Subclassed QApplication to handle macOS Dock icon clicks and reopen events.
    """

    def __init__(self, argv):
        super().__init__(argv)
        self.controller: Optional[JustTalkApp] = None
        # Set when the app itself is quitting (Cmd+Q, tray Quit, macOS logout/shutdown),
        # so the main window stops hiding-to-tray and lets the quit go through.
        self.is_quitting = False
        self._setup_mac_reopen()

    def event(self, e: QEvent) -> bool:
        if e.type() == QEvent.Type.Quit:
            self.is_quitting = True
            if self.controller:
                self.controller.cleanup()
        return super().event(e)

    def _setup_mac_reopen(self) -> None:
        """Register AppKit and AppleEvent reopen handlers so clicking Dock or Finder re-opens window."""
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSApp
            from Foundation import NSAppleEventManager
            import objc

            app_ref = self

            # 1. Native AppleEvent 'rapp' (kAEReopenApplication) and 'oapp' (kAEOpenApplication) handlers
            class AEHandler(objc.lookUpClass("NSObject")):
                def handleReopenEvent_withReplyEvent_(self, event, reply):
                    if app_ref.controller:
                        app_ref.controller.reopen()

            self._ae_handler = AEHandler.alloc().init()
            manager = NSAppleEventManager.sharedAppleEventManager()
            if manager:
                for event_id in (0x72617070, 0x6F617070):  # 'rapp' and 'oapp'
                    manager.setEventHandler_andSelector_forEventClass_andEventID_(
                        self._ae_handler,
                        "handleReopenEvent:withReplyEvent:",
                        0x61657674,  # 'aevt' (kCoreEventClass)
                        event_id,
                    )

            # 2. AppKit NSApplicationDelegate reopen and activation handler
            delegate = NSApp.delegate()
            if delegate:
                class ReopenHandler(objc.lookUpClass("NSObject")):
                    def applicationShouldHandleReopen_hasVisibleWindows_(self, ns_app, flag):
                        if app_ref.controller:
                            app_ref.controller.reopen()
                        return True

                    def applicationDidBecomeActive_(self, notification):
                        if app_ref.controller and app_ref.controller.main_window:
                            if not app_ref.controller.main_window.isVisible():
                                app_ref.controller.reopen()

                cls = type(delegate)
                if not hasattr(cls, "_justtalk_reopen_installed"):
                    objc.classAddMethods(
                        cls,
                        [
                            ReopenHandler.applicationShouldHandleReopen_hasVisibleWindows_,
                            ReopenHandler.applicationDidBecomeActive_,
                        ],
                    )
                    cls._justtalk_reopen_installed = True
        except Exception as e:
            print(f"[Main] Warning: Could not register macOS reopen handler: {e}", file=sys.stderr)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ApplicationActivate:
            if self.controller:
                self.controller.reopen()
        return super().event(event)


# Mixed Nepali + English with Apple: use Apple's English only when it was sure and heard the same
# sounds Kriti did. Logged on every mixed dictation so these can be tuned from real speech.
MIXED_APPLE_MIN_CONFIDENCE = 0.6
MIXED_MIN_SOUND_OVERLAP = 0.55
MIXED_APPLE_SURE = 0.9  # the user's Nepali never got above 0.54 from Apple
# Kriti itself wrote English ("द", "एन्ड", "इज") and no Nepali grammar words: it was English, even when
# Apple was unsure (0.5-0.6 on a 15 Oct English story, whose stretches then came out as Devanagari).
MIXED_KRITI_ENGLISH_WORDS = 0.1
MIXED_APPLE_MIN_IF_KRITI_ENGLISH = 0.4
MIXED_PIECE_SEC = 8.0  # language is decided per stretch of this length at most, cut at pauses
# The on-device model drops whole sentences from long Nepali (it trained on up to ~80 words), so
# Mixed mode translates a few stretches at a time: on 15 Oct dictations, 33 -> 57 chrF++.
MIXED_TRANSLATE_MAX_WORDS = 40


class _MixedEarly:
    """Mixed mode work done while the user is still talking: each finished stretch recognized
    (Apple + Kriti) and, in Translate mode, each finished run of stretches translated."""

    def __init__(self, pieces: EarlyPieces, translate: bool) -> None:
        self.pieces = pieces
        self.translate = translate
        self.translated: dict = {}  # (lang, text) -> (result, ok, message)
        self.thread: Optional[threading.Thread] = None


class JustTalkApp:
    """Core controller coordinating audio, local ML, Gemini formatting, and system insertion."""

    def __init__(self):
        self.config = AppConfig.load()
        self.db = HistoryDatabase()
        # Purge records older than user retention setting
        self.db.purge_expired(self.config.history_retention_days)
        PermissionsManager.ensure_healthy_input_volume()

        self.bridge = AppBridge()
        self.bridge._controller = self  # Back-reference for thread-safe dispatch
        self.overlay: Optional[FloatingPillOverlay] = None
        self.tray: Optional[SystemTrayManager] = None
        self.main_window: Optional[MainWindow] = None
        self.onboarding_window: Optional[OnboardingWindow] = None

        # Core subsystems
        self.vad = VoiceActivityDetector()
        self.recorder = AudioRecorder(
            device_index=self.config.audio_device_index,
            level_callback=lambda rms: self.bridge.level_changed.emit(rms),
        )
        self.model_manager = ModelManager()
        provider = getattr(self.config, "stt_provider", "whisper") or "whisper"
        if provider == "whisper":
            self.stt_engine = WhisperSTTEngine(self.model_manager)
        else:
            self.stt_engine = create_stt_engine_for_config(self.config, self.model_manager)
        self.stt = self.stt_engine
        self.native_stt_engine = get_native_stt_engine(
            model_manager=self.model_manager,
            offline_mode=getattr(self.config, "offline_mode", False),
        )
        self._streaming_thread: Optional[threading.Thread] = None
        self._whisper_partial: Optional[IncrementalTranscriber] = None
        self._early_mixed: Optional[_MixedEarly] = None  # Mixed mode work done while the user talks

        provider_id = getattr(self.config, "ai_provider", "gemini") or "gemini"
        model = getattr(self.config, "ai_model", "") or self.config.gemini_model
        if provider_id == "ollama":
            custom_base = getattr(self.config, "ollama_base_url", "http://localhost:11434/v1") or "http://localhost:11434/v1"
            model = getattr(self.config, "ollama_model", "") or "qwen2.5-coder:7b"
        else:
            custom_base = getattr(self.config, "custom_api_base_url", "")
        self.gemini = MultiProviderFormatter(
            provider_id=provider_id,
            api_key=CredentialManager.get_provider_api_key(provider_id),
            model_name=model,
            custom_base_url=custom_base,
            timeout=getattr(self.config, "formatting_budget_sec", 2.0),
        )
        self.inserter = TextInserter()
        self.audio_ducker = SystemAudioDucker()
        self.noise_filter = NoiseFilter()
        self.speaker_recognizer = SpeakerRecognizer()
        self.kriti = KritiEngine(self.model_manager.models_dir)
        self.voice_profile: Optional[VoiceProfile] = VoiceProfile.load()
        self.local_ai = LocalModel(self.model_manager.models_dir)
        self.learner = Learner.load()
        self._review_running = False
        self.lifecycle = ModelLifecycle(
            targets=self._unloadable_models,
            idle_minutes=lambda: getattr(self.config, "model_idle_unload_minutes", 10),
        )
        self.shortcut_manager: Optional[ShortcutManager] = None

        self._is_action_mode = False
        self._record_start_time = 0.0
        self._has_detected_speech = False
        self._last_speech_time = 0.0

    def get_app_icon(self) -> QIcon:
        """Resolve application icon from assets directory."""
        asset_dir = Path(__file__).resolve().parent.parent / "assets"
        for icon_name in ("icon.png", "icon.ico", "icon.icns"):
            p = asset_dir / icon_name
            if p.exists():
                return QIcon(str(p))

        # Generate a fallback runtime pixmap icon if asset files are missing
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        return QIcon(pixmap)

    def initialize_ui(self, app: QApplication) -> None:
        """Construct GUI windows, tray icon, and signal connections."""
        # 1. Load fonts and apply initial theme
        ThemeManager.load_fonts()
        ThemeManager.apply_theme(app, self.config.appearance)

        # Listen to system color scheme changes (macOS Light/Dark mode switch)
        if hasattr(app, "styleHints") and hasattr(app.styleHints(), "colorSchemeChanged"):
            app.styleHints().colorSchemeChanged.connect(
                lambda: self._on_system_color_scheme_changed(app)
            )

        app_icon = self.get_app_icon()
        app.setWindowIcon(app_icon)

        # 2. Initialize Floating Pill Overlay
        self.overlay = FloatingPillOverlay()
        # EXPLICIT QueuedConnection for signals emitted from non-Qt threads
        # (PortAudio audio callback, background pipeline threads).
        # The overlay is a QWidget (QObject) on the main thread, so QueuedConnection
        # guarantees the slot runs on the main thread even when emit() fires from C threads.
        self.bridge.level_changed.connect(
            self.overlay.update_audio_level, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.partial_transcript.connect(
            self.overlay.update_partial_transcript, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.state_listening.connect(
            self.overlay.show_listening, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.state_processing.connect(
            self.overlay.show_processing, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.state_inserted.connect(
            self.overlay.show_inserted, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.state_inserted_offline.connect(
            self.overlay.show_inserted_offline, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.state_copied.connect(
            self.overlay.show_copied, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.state_error.connect(
            self.overlay.show_error, Qt.ConnectionType.QueuedConnection
        )
        self.overlay.cancel_requested.connect(self._on_cancel_recording)
        # Confirm button goes through the bridge signal for thread safety
        self.overlay.confirm_requested.connect(
            lambda: self.bridge.stop_recording_requested.emit()
        )

        # 3. Initialize Main Application Window
        self.main_window = MainWindow(
            config=self.config,
            db=self.db,
            model_manager=self.model_manager,
            gemini=self.gemini,
            on_config_changed=self._on_config_updated,
        )
        self.main_window.replay_tutorial_requested.connect(self.show_onboarding)
        self.main_window.learner = self.learner
        self.main_window.refresh_learning()
        self.main_window.learn_now_requested.connect(lambda: self.review_history(on_done=self.main_window.on_learning_done))

        # 4. System Tray
        self.tray = SystemTrayManager(
            config=self.config,
            icon=app_icon,
            on_open_main=self.open_main_window,
            on_toggle_gemini=self._on_toggle_gemini,
            on_change_tier=self._on_change_tier,
            on_quit=self.quit,
            gemini=self.gemini,
            on_copy_last=self.copy_last_dictation,
            on_set_typing_language=lambda code: self.main_window.set_typing_language(code),
            on_set_translate=lambda on: self.main_window.set_translate(on),
        )
        self.tray.show()
        # Keep the tray's "Typing In" menu in step with the Home screen
        self.main_window.config_changed.connect(lambda _cfg: self.tray.refresh_menu())
        self.main_window.update_available.connect(self.tray.set_update_available)

        # 5. Open window (Onboarding or Main Window)
        # Any manual launch from Finder / Dock / Spotlight must ALWAYS present the UI!
        # Background / minimized start is only respected if explicitly invoked with CLI flags.
        is_background_launch = any(
            arg in sys.argv for arg in ("--minimized", "--background", "--startup")
        )
        if not self.config.has_completed_onboarding:
            self.show_onboarding()
        elif is_background_launch and self.config.start_minimized:
            print("[Main] Started minimized to menu bar / system tray.", file=sys.stderr)
        else:
            self.open_main_window("home")

        # 6. Check permissions (prompt for Accessibility, Input Monitoring & Microphone on macOS if needed)
        if sys.platform == "darwin":
            acc_ok = PermissionsManager.check_accessibility(prompt_if_needed=True)
            input_ok = PermissionsManager.check_input_monitoring()
            if not input_ok:
                PermissionsManager.request_input_monitoring()
            if not (acc_ok and input_ok):
                print(f"[Main] Permissions missing (Accessibility={acc_ok}, InputMonitoring={input_ok}). Starting watcher.", file=sys.stderr)
                self._start_permissions_watcher()
            mic_ok, mic_msg = PermissionsManager.check_microphone()
            if not mic_ok:
                print(f"[Main] Microphone access prompt: {mic_msg}", file=sys.stderr)
                PermissionsManager.request_microphone()

        # 7. Warm up speech engine (only download/load background thread if Whisper is selected)
        # Whisper is the big one: unless the user chose to keep models loaded, it loads on the
        # first recording instead of at launch, so an idle app costs almost nothing.
        if getattr(self.config, "stt_provider", "os_native") == "whisper":
            if not getattr(self.config, "model_idle_unload_minutes", 10):
                self._preload_models_async()
        else:
            self.stt_engine.load()

        # Frees the models after the idle limit (checked once a minute)
        self._lifecycle_timer = QTimer(self.bridge)
        self._lifecycle_timer.setInterval(60_000)
        self._lifecycle_timer.timeout.connect(self._lifecycle_tick)
        self._lifecycle_timer.start()

        # 8. Start keyboard shortcuts
        # The shortcut callbacks fire from a Quartz CFRunLoop thread (not the Qt thread).
        # They ONLY emit signals — the actual recording logic runs on the main thread
        # via AppBridge's @Slot methods connected with explicit QueuedConnection.
        self.shortcut_manager = ShortcutManager(
            shortcut=self.config.shortcut,
            action_shortcut=self.config.action_shortcut,
            push_to_talk=self.config.push_to_talk,
            on_start_recording=lambda action: self.bridge.start_recording_requested.emit(action),
            on_stop_recording=lambda: self.bridge.stop_recording_requested.emit(),
            on_action_mode_changed=lambda is_action: self.bridge.action_mode_changed.emit(is_action),
            on_cancel_recording=lambda: self.bridge.cancel_recording_requested.emit(),
            on_paste_last=self.paste_last_dictation,
        )
        self.shortcut_manager.start()

        # 9. Main-thread visualizer timer (50 Hz / 20ms) for rock-solid UI updates without audio thread locking
        self._level_timer = QTimer(self.bridge)
        self._level_timer.setInterval(20)
        self._level_timer.timeout.connect(self._poll_audio_level)

    def _unloadable_models(self):
        """Models that can be freed when idle and reloaded on demand."""
        targets = [("speech model", self.stt_engine.is_loaded, self.stt_engine.unload)]
        if hasattr(self.kriti, "unload"):
            targets.append(("Kriti", self.kriti.is_loaded, self.kriti.unload))
        targets.append(("voice ID", self.speaker_recognizer.is_loaded, self.speaker_recognizer.unload))
        targets.append(("on-device AI", self.local_ai.is_loaded, self.local_ai.unload))
        return [t for t in targets if hasattr(t[2], "__call__")]

    def _lifecycle_tick(self) -> None:
        if self.recorder.is_recording:
            self.lifecycle.touch()  # a long recording must not outlast the idle limit
            return
        self.lifecycle.unload_if_idle()

    def _preload_models_async(self) -> None:
        """Warm the models the next transcription will need, without blocking the caller."""
        self.lifecycle.touch()
        cfg = self.config

        def worker():
            try:
                with self.lifecycle.busy():
                    if getattr(cfg, "stt_provider", "os_native") == "whisper" and not self.stt_engine.is_loaded():
                        custom = cfg.custom_stt_model_path if getattr(cfg, "stt_model_source", "bundled") == "custom" else None
                        self.stt_engine.load(cfg.model_tier, custom_target=custom)
                    if (
                        getattr(cfg, "nepali_asr_engine", "whisper") == "kriti"
                        and getattr(cfg, "language", "en") in ("ne", "ne_en")
                        and self.kriti.is_available()
                    ):
                        self.kriti.load()
                    if getattr(cfg, "speaker_id_enabled", True) and self.speaker_recognizer.is_available():
                        self.speaker_recognizer._ensure_session()
                    if getattr(cfg, "local_ai", False):
                        self.local_ai.load()  # loads while the user speaks; first answer is then instant
            except Exception as e:
                print(f"[Lifecycle] Preload failed: {e}", file=sys.stderr)

        threading.Thread(target=worker, daemon=True).start()

    def _start_permissions_watcher(self) -> None:
        """Poll Accessibility and Input Monitoring periodically until granted, then seamlessly reload shortcuts."""
        from PySide6.QtCore import QTimer

        if hasattr(self, "_perm_timer") and self._perm_timer.isActive():
            return
        self._perm_timer = QTimer(self.bridge)
        self._perm_timer.setInterval(1500)

        def check_and_reload():
            acc_ok = PermissionsManager.check_accessibility(prompt_if_needed=False)
            input_ok = PermissionsManager.check_input_monitoring()
            if acc_ok and input_ok:
                self._perm_timer.stop()
                print("[Main] Accessibility and Input Monitoring permissions granted! Re-hooking shortcuts.", file=sys.stderr)
                if self.shortcut_manager:
                    self.shortcut_manager.reload(
                        shortcut=self.config.shortcut,
                        action_shortcut=self.config.action_shortcut,
                        push_to_talk=self.config.push_to_talk,
                    )
                if self.main_window:
                    self.main_window._refresh_home_status()

        self._perm_timer.timeout.connect(check_and_reload)
        self._perm_timer.start()

    def _on_system_color_scheme_changed(self, app: QApplication) -> None:
        """Handle live OS theme change."""
        if self.config.appearance == "system":
            ThemeManager.apply_theme(app, "system")
            if self.main_window:
                self.main_window.refresh_theme_icons()

    def reopen(self) -> None:
        """Reopen or activate the main application window or onboarding wizard."""
        if not self.config.has_completed_onboarding and self.onboarding_window and self.onboarding_window.isVisible():
            self.show_onboarding()
        else:
            self.open_main_window(None)

    def open_main_window(self, screen_name: Optional[str] = None) -> None:
        """Open or raise the main full application window."""
        if self.main_window:
            self.main_window.show_and_activate(screen_name)

    def show_onboarding(self) -> None:
        """Open setup: permissions, languages, role, voice profile, first try."""
        if not self.onboarding_window or not self.onboarding_window.isVisible():
            self.onboarding_window = OnboardingWindow(
                config=self.config,
                gemini=self.gemini,
                model_manager=self.model_manager,
                on_complete=self._on_onboarding_complete,
                kriti=self.kriti,
                on_engines_changed=lambda: self.set_stt_provider(self.config.stt_provider),
                learner=self.learner,
            )
        if sys.platform == "darwin":
            try:
                from AppKit import NSApp, NSApplicationActivationPolicyRegular

                NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
                NSApp.activateIgnoringOtherApps_(True)
            except Exception:
                pass
        self.onboarding_window.show()
        self.onboarding_window.raise_()
        self.onboarding_window.activateWindow()

    def _on_onboarding_complete(self) -> None:
        self.voice_profile = VoiceProfile.load()
        self.review_history()  # no-op unless AI review is on
        if self.main_window:
            # Setup changed languages, vocabulary and engines; show them in Settings without saving again
            self.main_window._loading_settings = True
            try:
                self.main_window._load_settings_values()
            finally:
                self.main_window._loading_settings = False
            if self.tray:
                self.tray.refresh_menu()
        self.open_main_window("home")

    def _speaker_context(self) -> str:
        role = ROLES_BY_ID.get(getattr(self.config, "user_role", ""))
        return speaker_context_block(
            role.label if role else "", vocabulary_terms(self.config, self.learner), self.learner.known_mixups()
        )

    def _mixed_mode_ready(self) -> bool:
        return (
            getattr(self.config, "language", "") == "ne_en"
            and getattr(self.config, "nepali_asr_engine", "whisper") == "kriti"
            and isinstance(self.stt_engine, MacNativeSTTEngine)
            and self.kriti.is_available()
        )

    def _early_mixed_loop(self, early: _MixedEarly) -> None:
        """Apple takes about 10 s for 90 s of Nepali (Kriti about 1.5 s) and the on-device model
        about 4 s to translate it, so in Mixed mode each finished stretch of speech is recognized,
        and each finished run of stretches translated, while the user is still talking."""
        while self.recorder and self.recorder.is_recording:
            time.sleep(0.5)
            try:
                early.pieces.update(self.recorder.get_current_audio())
                if early.translate:
                    runs = self._segment_runs(self._segments_from(early.pieces.results()))
                    for run in runs[:-1]:  # the last run can still grow
                        if run not in early.translated:
                            early.translated[run] = self._run_local_ai(*run)
            except Exception as e:
                print(f"[STT] Mixed early work stopped: {e}", file=sys.stderr)
                return

    def _mixed_piece(self, piece) -> tuple:
        """(Apple's English, Apple's average word confidence, Kriti's Devanagari) for one stretch."""
        if not len(piece) or float(np.max(np.abs(piece))) < 0.002:  # a thinking pause
            return "", 0.0, ""
        if getattr(self.config, "voice_isolation_enabled", True) and hasattr(self, "noise_filter"):
            piece = self.noise_filter.filter(piece, sr=16000)
        confs: list = []
        english = (self.stt_engine.transcribe(piece, language="en", confidences=confs) or "").strip()
        devanagari = (self.kriti.transcribe(piece, language="ne") or "").strip()
        return english, sum(confs) / len(confs) if confs else 0.0, devanagari

    def _segments_from(self, results: list, log: bool = False) -> list:
        """[(text, "en" | "ne")] from recognized stretches: Apple's English where Apple was confident
        and heard the same sounds as Kriti, Kriti's Devanagari everywhere else."""
        segments = []
        for start, end, (english, confidence, devanagari) in results:
            if not english and not devanagari:
                continue
            overlap = sound_overlap(english, devanagari)
            en_words, ne_words = language_words(devanagari)
            use_english = bool(english) and (
                (confidence >= MIXED_APPLE_MIN_CONFIDENCE and overlap >= MIXED_MIN_SOUND_OVERLAP)
                or confidence >= MIXED_APPLE_SURE
                or (en_words >= MIXED_KRITI_ENGLISH_WORDS and ne_words == 0 and confidence >= MIXED_APPLE_MIN_IF_KRITI_ENGLISH)
            )
            if log:
                print(f"[STT] Mixed {(end - start) / 16000:.1f}s -> {'EN' if use_english else 'NE'} "
                      f"(Apple confidence {confidence:.2f}, sound overlap {overlap:.2f}, Kriti English/Nepali words "
                      f"{en_words:.2f}/{ne_words:.2f}) Apple={english!r} Kriti={devanagari!r}", file=sys.stderr)
            text = english if use_english else devanagari
            if text:
                segments.append((text, "en" if use_english else "ne"))
        return segments

    def _mixed_preview(self, early: _MixedEarly, audio, preview) -> str:
        """Mixed mode's live text: finished stretches as they will be typed (Apple's English where
        it heard English, Kriti's Devanagari elsewhere), then Kriti's guess for the stretch still
        being spoken. Kriti alone showed English words in Nepali letters until the very end."""
        done = early.pieces.results()
        tail = audio[done[-1][1]:] if done else audio
        shown = " ".join(text for text, _ in self._segments_from(done))
        live = preview(tail) if len(tail) >= int(16000 * 0.35) else ""
        return f"{shown} {live or ''}".strip()

    def _mixed_transcribe(self, audio, early: Optional[EarlyPieces] = None) -> list:
        """People who mix Nepali and English switch language mid-dictation, so the engine is chosen
        per stretch of speech (split at pauses). `early` has the stretches already recognized
        while the user was talking."""
        started = time.monotonic()
        pieces = early if early is not None else EarlyPieces(self._mixed_piece, max_piece_sec=MIXED_PIECE_SEC)
        done_early = len(pieces)
        results = pieces.finish(audio)
        segments = self._segments_from(results, log=True)
        print(f"[STT] Mixed: {done_early} of {len(results)} stretches done while talking, "
              f"rest took {time.monotonic() - started:.2f}s", file=sys.stderr)
        return segments

    def _run_local_ai(self, seg_lang: str, text: str) -> tuple:
        return self.local_ai.run("translate" if seg_lang == "ne" else "cleanup", text, self._speaker_context())

    def _translate_segments(self, segments: list, done: Optional[dict] = None):
        """Translate the Nepali stretches and clean up the English ones (punctuation, misheard
        words), a few same-language stretches per call: whole sentences for context, short enough
        that the model keeps every detail. `done` has runs already translated while the user talked."""
        runs, parts, failed, msg = self._segment_runs(segments), [], 0, ""
        for run in runs:
            result, ok, msg = (done or {}).get(run) or (None, False, "")
            if not ok:
                result, ok, msg = self._run_local_ai(*run)
            if not ok:
                # Keep the rest polished: one rejected run used to send a whole 100-word story out raw
                failed += 1
                print(f"[LocalAI] {run[0]} run kept as heard ({msg}): {run[1][:60]!r}", file=sys.stderr)
                result = GeminiFormatter.light_local_cleanup(run[1])
            parts.append(result)
        if failed == len(runs):
            return "", False, msg
        return " ".join(parts), True, ""

    @staticmethod
    def _segment_runs(segments: list, max_words: int = MIXED_TRANSLATE_MAX_WORDS) -> list:
        """[(lang, text)]: consecutive same-language stretches joined, up to max_words per run."""
        runs: list = []
        for text, seg_lang in segments:
            if runs and runs[-1][0] == seg_lang and len(runs[-1][1].split()) + len(text.split()) <= max_words:
                runs[-1] = (seg_lang, f"{runs[-1][1]} {text}")
            else:
                runs.append((seg_lang, text))
        return runs

    @staticmethod
    def _local_task(intent, action_name: str, text: str, is_action_mode: bool) -> Optional[str]:
        """What the on-device model can do for this dictation: translate to English or clean up
        English. Nepali-script output and Action Mode stay with the cloud model."""
        if is_action_mode:
            return None
        if action_name == "translate" and (getattr(intent, "target_language", None) or "English").lower() == "english":
            return "translate" if has_devanagari(text) else "cleanup"  # English already: just tidy it
        if action_name == "format" and not any("\u0900" <= c <= "\u097f" for c in text):
            return "cleanup"
        return None

    def _learn_from_dictation(self, raw_text: str, final_text: str, action_name: str) -> None:
        """Every dictation teaches the learner (locally); now and then the AI review runs too."""
        translated = action_name == "translate" or getattr(self.config, "speech_mode", "transcribe") == "translate"
        self.learner.observe_dictation(raw_text, final_text, translated=translated)
        if self.learner.review_due():
            self.review_history()

    def review_history(self, on_done: Optional[Callable[[str], None]] = None) -> bool:
        """Ask the AI provider to learn this user's words and mix-ups from past dictation text.
        Runs in the background with its own client so it never disturbs live cleanup."""
        cfg = self.config
        if not getattr(cfg, "learn_with_ai", False) or not getattr(cfg, "gemini_enabled", True) or getattr(cfg, "offline_mode", False):
            if on_done:
                on_done("Turn on AI review and AI cleanup to learn from past dictations.")
            return False
        if self._review_running:
            return False
        self._review_running = True
        g = self.gemini
        reviewer = MultiProviderFormatter(
            provider_id=g.provider_id, api_key=g.api_key, model_name=g.model_name,
            custom_base_url=getattr(g, "base_url", None) if g.provider_id in ("custom", "ollama") else None,
        )

        def ask(system: str, user: str) -> Optional[str]:
            text, ok, msg = reviewer.format_text(raw_text=user, style=GENERATE_STYLE, custom_system_instruction=system, budget_sec=45.0)
            if not ok:
                print(f"[Learner] Review failed: {CredentialManager.redact(msg)}", file=sys.stderr)
            return text if ok else None

        def worker() -> None:
            message = "Couldn't reach the AI provider. Try again later."
            try:
                rows = [
                    (item.raw_transcription, item.processed_text)
                    for item in self.db.get_recent(limit=200)
                    if item.action not in (EDIT_SELECTION_STYLE, GENERATE_STYLE)  # those store a command, not speech
                ]
                terms, mixups = self.learner.review(rows, ask)
                if terms or mixups:
                    message = f"Learned {terms} words and {mixups} mix-ups from your dictations."
                print(f"[Learner] Review: {message}", file=sys.stderr)
            except Exception as e:
                print(f"[Learner] Review error: {e}", file=sys.stderr)
            finally:
                self._review_running = False
            if on_done:
                run_on_ui_thread(lambda: on_done(message))

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _poll_audio_level(self) -> None:
        """Poll current RMS level from recorder on main Qt thread and update visualizer."""
        if self.recorder and self.recorder.is_recording:
            lvl = self.recorder.get_audio_level()
            if self.overlay:
                self.overlay.update_audio_level(lvl)

            now = time.time()
            vad_thresh = getattr(self.vad, "energy_threshold", 0.015)
            if lvl >= vad_thresh:
                self._has_detected_speech = True
                self._last_speech_time = now
            elif self._has_detected_speech:
                # Silence auto-commit: if speech was detected and user paused for a long while in
                # toggle mode. Kept generous so pausing to think mid-dictation doesn't end it.
                if not getattr(self.config, "push_to_talk", False):
                    silence_sec = now - self._last_speech_time
                    if silence_sec >= 8.0:
                        print(f"[Record] Silence auto-commit ({silence_sec:.1f}s silence after speech)", file=sys.stderr)
                        self.bridge.stop_recording_requested.emit()
                        return

            # Safety limit: max recording duration (default 5 min). Older configs persisted 60s,
            # which cut off long dictation, so treat that as a floor rather than a ceiling.
            max_sec = max(getattr(self.config, "max_recording_sec", 300.0) or 300.0, 300.0)
            if now - self._record_start_time >= max_sec:
                print(f"[Record] Max recording limit reached ({max_sec:.1f}s), auto-stopping.", file=sys.stderr)
                self.bridge.stop_recording_requested.emit()

    @Slot(bool)
    def on_start_recording(self, is_action_mode: bool = False) -> None:
        """Triggered on the main Qt thread when push-to-talk shortcut is pressed."""
        self._is_action_mode = is_action_mode
        self._record_start_time = time.time()
        self._has_detected_speech = False
        self._last_speech_time = time.time()
        self.inserter.capture_active_target()
        self._preload_models_async()  # loads while the user speaks; no-op if already resident

        # Temporarily mute computer audio (music, YouTube, movies, Reels) while holding shortcut
        if getattr(self.config, "mute_audio_while_recording", True):
            self.audio_ducker.mute()

        print(f"[Record] START recording (action_mode={is_action_mode})", file=sys.stderr)
        self.bridge.state_listening.emit(is_action_mode)
        started = self.recorder.start()
        if not started:
            print("[Record] ERROR: Microphone failed to start!", file=sys.stderr)
            if hasattr(self, "audio_ducker"):
                self.audio_ducker.unmute()
            self.bridge.state_error.emit("Microphone error")
        else:
            self._level_timer.start()
            self._start_streaming_worker()
            print("[Record] Microphone stream opened successfully.", file=sys.stderr)

    def _start_streaming_worker(self) -> None:
        """Start background live streaming STT thread to stream partial words to the overlay HUD."""
        self._last_partial_transcript = ""
        for engine in (self.stt_engine, getattr(self, "native_stt_engine", None)):
            if hasattr(engine, "reset_partial"):
                engine.reset_partial()
        self._whisper_partial = (
            IncrementalTranscriber(self.stt_engine.transcribe, window_sec=6.0)
            if isinstance(self.stt_engine, WhisperSTTEngine) else None
        )
        self._early_mixed = None
        if self._mixed_mode_ready():
            self.stt_engine.vocabulary = vocabulary_terms(self.config, self.learner)
            translate = (getattr(self.config, "speech_mode", "") == "translate" and getattr(self.config, "local_ai", False)
                         and self.local_ai.is_available())
            early = _MixedEarly(EarlyPieces(self._mixed_piece, max_piece_sec=MIXED_PIECE_SEC), translate)
            early.thread = threading.Thread(target=self._early_mixed_loop, args=(early,), daemon=True)
            early.thread.start()
            self._early_mixed = early
        self._streaming_thread = threading.Thread(
            target=self._streaming_stt_loop,
            daemon=True,
        )
        self._streaming_thread.start()

    def _preview_transcriber(self, lang):
        """The engine that shows words live while you talk. It runs several times a second, so it
        has to be light: re-running Whisper Turbo on the whole recording each time kept the CPU at
        100% for the entire dictation and made Macs hot."""
        cur = (getattr(self.config, "language", "en") or "").lower()
        if (cur in ("ne", "ne_en") and getattr(self.config, "nepali_asr_engine", "kriti") == "kriti"
                and self.kriti.is_available()):
            return lambda audio: self.kriti.transcribe(audio, language="ne")  # ~0.1 s per pass
        engine = self.stt_engine
        if engine is not None and engine.is_loaded() and hasattr(engine, "transcribe_partial"):
            return lambda audio: engine.transcribe_partial(audio, language=lang, task="transcribe")
        if isinstance(engine, WhisperSTTEngine) and engine.is_loaded() and self._whisper_partial is not None:
            partial = self._whisper_partial  # only the last few seconds are re-decoded
            return lambda audio: partial.update(audio, language=lang, task="transcribe")
        native = getattr(self, "native_stt_engine", None)
        if native is not None and hasattr(native, "transcribe_partial"):
            return lambda audio: native.transcribe_partial(audio, language=lang, task="transcribe")
        return None

    def _streaming_stt_loop(self) -> None:
        """Decode the growing recording while the user speaks and show the words in the HUD."""
        min_samples = int(16000 * 0.35)  # 350ms minimum audio before partial decoding begins
        last_audio_samples = 0
        pause = 0.18

        while self.recorder and self.recorder.is_recording:
            time.sleep(pause)
            if not self.recorder or not self.recorder.is_recording:
                break

            cur_audio = self.recorder.get_current_audio()
            if cur_audio is None or len(cur_audio) < min_samples:
                continue

            # Only decode if buffer has grown by at least 150ms of new audio
            if len(cur_audio) - last_audio_samples < int(16000 * 0.15):
                continue

            last_audio_samples = len(cur_audio)

            try:
                lang = self.config.stt_language(getattr(self.config, "speech_mode", "transcribe") == "translate")
                preview = self._preview_transcriber(lang)
                if preview is None:
                    continue
                started = time.monotonic()
                early = self._early_mixed
                partial_text = self._mixed_preview(early, cur_audio, preview) if early else preview(cur_audio)
                # Rest at least as long as the decode took, so the preview never uses more than
                # about half the CPU however slow the engine is.
                pause = max(0.18, 1.2 * (time.monotonic() - started))

                if partial_text and partial_text.strip() and self.recorder and self.recorder.is_recording:
                    cleaned = partial_text.strip()
                    self._last_partial_transcript = cleaned
                    self.bridge.partial_transcript.emit(cleaned)
            except Exception:
                pass

    def on_action_mode_changed(self, is_action_mode: bool) -> None:
        """Triggered on the main Qt thread when Shift is pressed/released while already holding push-to-talk."""
        if not is_action_mode and self._is_action_mode:
            # Sticky for the rest of the recording: people tap Fn+Shift and let go of Shift
            # first, which used to silently turn Action Mode (and selection editing) back off.
            print("[Record] Shift released; keeping Action Mode for this recording", file=sys.stderr)
            return
        self._is_action_mode = is_action_mode
        print(f"[Record] Dynamically toggled Action Mode: {is_action_mode}", file=sys.stderr)
        if self.overlay and self.recorder and self.recorder.is_recording:
            self.overlay.set_action_mode(is_action_mode)

    def _on_cancel_recording(self) -> None:
        """User cancelled recording via the overlay [ ✕ ] button or Escape key."""
        self._level_timer.stop()
        if hasattr(self, "audio_ducker"):
            self.audio_ducker.unmute()
        if self.overlay:
            self.overlay.update_audio_level(0.0)
        self.recorder.stop()
        if hasattr(self, "inserter"):
            self.inserter.cancel_draft()
            # the click activates Just Talk a moment later; then go back to the browser/editor
            QTimer.singleShot(150, self.inserter.return_to_target)
        if self.shortcut_manager:
            self.shortcut_manager.reset_state()
        self.bridge.state_error.emit("Cancelled")

    @Slot()
    def on_stop_recording(self) -> None:
        """Triggered on the main Qt thread when push-to-talk shortcut is released or checkmark is clicked."""
        self._level_timer.stop()
        if hasattr(self, "audio_ducker"):
            self.audio_ducker.unmute()
        if self.overlay:
            self.overlay.update_audio_level(0.0)

        hold_duration = time.time() - self._record_start_time
        print(f"[Record] STOP recording (held for {hold_duration:.2f}s)", file=sys.stderr)

        if self.shortcut_manager:
            self.shortcut_manager.reset_state()

        if hold_duration < 0.08:
            # Micro-tap / jitter (<80ms): stop recorder and hide overlay
            print("[Record] Key tap too brief (<0.08s), hiding overlay silently.", file=sys.stderr)
            self.recorder.stop()
            self.overlay.hide_overlay()
            return

        audio = self.recorder.stop()
        if audio is None or len(audio) == 0:
            print(f"[Record] No audio frames captured! audio={'None' if audio is None else 'empty'}", file=sys.stderr)
            self.overlay.hide_overlay()
            return

        import numpy as np
        duration_sec = len(audio) / 16000
        rms = float(np.sqrt(np.mean(np.square(audio))))
        peak = float(np.max(np.abs(audio)))
        nonzero = int(np.count_nonzero(audio))
        print(f"[Record] Audio captured: {len(audio)} samples ({duration_sec:.2f}s), "
              f"RMS={rms:.6f}, Peak={peak:.6f}, NonZero={nonzero}/{len(audio)}", file=sys.stderr)

        # Detect silence caused by macOS blocking microphone access
        if duration_sec >= 0.35 and (nonzero == 0 or peak < 0.0001):
            if sys.platform == "darwin":
                has_mic, mic_msg = PermissionsManager.check_microphone()
                if not has_mic:
                    print(f"[Record] Microphone blocked by macOS TCC: {mic_msg}", file=sys.stderr)
                    PermissionsManager.request_microphone()
                    self.bridge.state_error.emit("Microphone permission required")
                    return
            print("[Record] Flatline silence: no input signal detected from microphone.", file=sys.stderr)
            self.bridge.state_error.emit("No microphone audio")
            return

        # Voice Activity Detection: Filter out accidental taps and pure silence
        vad_result = self.vad.is_speech_present(audio)
        has_partial = bool(self._last_partial_transcript and self._last_partial_transcript.strip())
        print(f"[Record] VAD result: speech_present={vad_result}, has_partial={has_partial} "
              f"(threshold={self.vad.energy_threshold}, min_dur={self.vad.min_speech_duration_sec}s)", file=sys.stderr)

        if not vad_result and not has_partial:
            if duration_sec >= 0.25:
                print(f"[Record] Audio energy too quiet (RMS={rms:.6f}, Peak={peak:.6f}) → 'Voice too quiet'", file=sys.stderr)
                self.bridge.state_error.emit("Voice too quiet")
            else:
                print("[Record] Too short, hiding overlay silently", file=sys.stderr)
                self.overlay.hide_overlay()
            return

        print("[Record] VAD passed → sending to transcription pipeline", file=sys.stderr)
        self.bridge.state_processing.emit("Transcribing...")
        # Dispatch transcription and formatting to background worker
        early, self._early_mixed = self._early_mixed, None
        threading.Thread(
            target=self._process_audio_pipeline,
            args=(audio, self._is_action_mode),
            kwargs={"early": early},
            daemon=True,
        ).start()

    def _process_audio_pipeline(
        self, audio, is_action_mode: bool, force_accept_speaker: bool = False, early: Optional[_MixedEarly] = None
    ) -> None:
        with self.lifecycle.busy():
            self._run_audio_pipeline(audio, is_action_mode, force_accept_speaker, early)

    def _run_audio_pipeline(
        self, audio, is_action_mode: bool, force_accept_speaker: bool = False, early: Optional[_MixedEarly] = None
    ) -> None:
        """Background pipeline: STT -> Gemini -> Insertion -> Database.

        force_accept_speaker re-runs a dictation the voice filter ignored, after the user
        confirmed it was them (Paste Last Dictation right after the "ignored" notice).
        early holds the Mixed mode work already done while the user was talking.
        """
        try:
            start_time = time.time()

            # 0a. Detect editing context (non-blocking, falls back to "text" on any error)
            try:
                _ctx_info = detect_context()
                detected_context = _ctx_info.context
            except Exception:
                detected_context = "text"

            # 0b. Check if STT model is loaded or downloading (only needed for local Whisper)
            if getattr(self.config, "stt_provider", "os_native") == "whisper" and not self.stt_engine.is_loaded():
                if getattr(self.stt_engine, "is_loading", False):
                    msg = getattr(self.stt_engine, "loading_status", "Loading speech model...")
                    self.bridge.state_processing.emit(msg)
                wait_start = time.time()
                while not self.stt_engine.is_loaded() and (time.time() - wait_start < 12.0):
                    time.sleep(0.25)
                    if getattr(self.stt_engine, "is_loading", False):
                        msg = getattr(self.stt_engine, "loading_status", "Loading speech model...")
                        self.bridge.state_processing.emit(msg)

                if not self.stt_engine.is_loaded():
                    self.bridge.state_error.emit("Speech model downloading")
                    return

            # 1. Speaker identification on the raw, speech-only audio: the same signal
            #    enrollment captures. Comparing noise-filtered audio against a raw profile,
            #    silence included, scored the user's own voice anywhere from 0.23 to 0.76.
            identified_speaker = None
            if (
                not force_accept_speaker
                and getattr(self.config, "speaker_id_enabled", True)
                and hasattr(self, "speaker_recognizer")
                and self.speaker_recognizer.is_available()
            ):
                profiles = profiles_from_records(self.db.get_voice_profile_records())
                if profiles:
                    emb = self.speaker_recognizer.extract_embedding(speech_only(audio))
                    if emb is not None:
                        decision = decide(emb, profiles)
                        print(
                            f"[SpeakerID] {decision.action} (speaker={decision.speaker}, score={decision.score:.2f})",
                            file=sys.stderr,
                        )
                        if decision.action == "match":
                            identified_speaker = decision.speaker
                        elif decision.action == "other" and getattr(self.config, "target_speaker_isolation", False):
                            # Only clearly-different voices are dropped; keep the audio so the
                            # user can say "that was me" with Paste Last Dictation.
                            self._last_ignored = (audio, emb, time.time(), is_action_mode)
                            shortcut = "\u2303\u2318V" if sys.platform == "darwin" else "Win+Alt+V"
                            self.bridge.state_error.emit(f"Ignored another voice \u00b7 {shortcut} if it was you")
                            return

            # 2. Background noise reduction
            unfiltered_audio = audio
            if getattr(self.config, "voice_isolation_enabled", True) and hasattr(self, "noise_filter"):
                audio = self.noise_filter.filter(audio, sr=16000)

            # 3. Local Speech-to-Text with Multilingual & Dual-Task Support
            speech_mode = getattr(self.config, "speech_mode", "transcribe")
            use_gemini = self.config.gemini_enabled and not self.config.offline_mode
            use_local = getattr(self.config, "local_ai", False) and self.local_ai.is_available()  # works offline too
            is_translation_mode = (speech_mode == "translate")

            # High-fidelity 2-stage translation for mixed language / Nepglish code-switching:
            # Stage 1: Whisper transcribes raw speech faithfully without translation distortion
            # Stage 2: Gemini / LLM translates mixed speech into clean, idiomatic English
            # When offline without AI, Whisper must fall back to built-in task="translate"
            task = "translate" if (is_translation_mode and not (use_gemini or use_local)) else "transcribe"

            cur_lang = getattr(self.config, "language", "en")
            lang = self.config.stt_language(is_translation_mode)

            if is_translation_mode or is_action_mode:
                self.bridge.state_processing.emit("Translating speech to English...")
            else:
                self.bridge.state_processing.emit("Transcribing...")

            # Construct context prompt (bilingual acoustic priming, active app name, custom vocabulary)
            app_name = self.inserter.get_active_app_name()
            prompt_parts = []
            if is_translation_mode or cur_lang in ("ne_en", "ne", "auto", None):
                # Priming Whisper with bilingual context prevents acoustic hallucinations on code-switched / Nepali speech
                prompt_parts.append("Namaste, yo meeting ma we will discuss code, features, bug fixes, ra testing: आजको काम र भोलिको अपडेट।")
            if app_name and app_name != "Active Application":
                prompt_parts.append(f"Dictation into {app_name}.")
            vocab_terms = vocabulary_terms(self.config, self.learner)
            for engine in (self.stt_engine, getattr(self, "native_stt_engine", None)):
                if hasattr(engine, "vocabulary"):
                    engine.vocabulary = vocab_terms
            if vocab_terms:
                prompt_parts.append(f"Custom vocabulary: {', '.join(vocab_terms)}.")
            initial_prompt = " ".join(prompt_parts) if prompt_parts else None

            # Kriti is Nepali-only: route to it only when the user dictates in Nepali (or mixed),
            # never just because Nepali is one of several selected languages.
            # In mixed mode, ask Whisper (when it is the loaded engine) which language dominates:
            # mostly-English speech goes to Whisper so English isn't spelled in Devanagari.
            if cur_lang == "ne_en" and lang is None and task == "transcribe" and hasattr(self.stt_engine, "detect_language"):
                detected = self.stt_engine.detect_language(audio)
                print(f"[STT] Mixed mode language check: {detected}", file=sys.stderr)
                if english_dominant(detected):
                    lang = "en"

            use_kriti = (
                getattr(self.config, "nepali_asr_engine", "whisper") == "kriti"
                and task == "transcribe"
                and lang != "en"
                and (lang == "ne" or cur_lang in ("ne", "ne_en"))
                and self.kriti.is_available()
            )

            raw_text = ""
            mixed_segments: list = []  # [(text, "en" | "ne")] when Mixed mode decides per stretch of speech
            if use_kriti and cur_lang == "ne_en" and isinstance(self.stt_engine, MacNativeSTTEngine):
                mixed_segments = self._mixed_transcribe(unfiltered_audio, early.pieces if early else None)
                raw_text = " ".join(t for t, _ in mixed_segments)
                if mixed_segments and all(seg_lang == "en" for _, seg_lang in mixed_segments):
                    lang = "en"
            elif use_kriti:
                raw_text = self.kriti.transcribe(audio, language="ne")
                print(f"[STT] Kriti: {raw_text!r}", file=sys.stderr)

            if not raw_text or not raw_text.strip():
                raw_text = self.stt_engine.transcribe(
                    audio,
                    language=lang,
                    task=task,
                    initial_prompt=initial_prompt,
                )
                # Automatic fallback: if configured language yielded nothing, try auto-detection
                if (not raw_text or not raw_text.strip()) and lang:
                    raw_text = self.stt_engine.transcribe(
                        audio,
                        language=None,
                        task=task,
                        initial_prompt=initial_prompt,
                    )

            # The live words are recognised from the raw microphone audio, so if the cleaned-up audio
            # comes back empty (noise reduction can eat quiet speech in a loud room), try the raw audio
            if (not raw_text or not raw_text.strip()) and unfiltered_audio is not audio:
                if use_kriti:
                    raw_text = self.kriti.transcribe(unfiltered_audio, language="ne")
                if not raw_text or not raw_text.strip():
                    raw_text = self.stt_engine.transcribe(
                        unfiltered_audio,
                        language=lang,
                        task=task,
                        initial_prompt=initial_prompt,
                    )
                if raw_text and raw_text.strip():
                    print("[STT] Recovered transcription from unfiltered audio", file=sys.stderr)

            if not raw_text or not raw_text.strip():
                if self._last_partial_transcript and self._last_partial_transcript.strip():
                    raw_text = self._last_partial_transcript.strip()
                    print(f"[STT] Recovered transcription from live partial stream: '{raw_text}'", file=sys.stderr)
                else:
                    print("[STT] Transcription returned empty → 'No speech recognized'", file=sys.stderr)
                    self.bridge.state_error.emit("No speech recognized")
                    return

            raw_text = raw_text.strip()
            print(f"[STT Raw (task={task}, lang={lang})]: {raw_text}")

            # 4. Action Routing & Intent Detection
            conventions = getattr(self.config, "conventions", {})
            can_action = use_gemini or use_local
            if is_action_mode and can_action and has_devanagari(raw_text) and self.local_ai.is_available():
                # Kriti writes spoken English commands in Nepali letters ("ट्रान्सलेट डिस टु इङ्ग्लिस"):
                # read the request as English so commands are recognised and the result is English
                spoken, ok, _ = self.local_ai.run("translate", raw_text, self._speaker_context())
                if ok and spoken.strip():
                    print(f"[Action] request in English: {spoken!r}", file=sys.stderr)
                    raw_text = spoken.strip()
            if is_action_mode and can_action:
                selected_text = self.inserter.copy_selection()
                if selected_text and detected_context != "text" and TextInserter.is_implicit_line_copy(selected_text):
                    # Code editors copy the whole current line when nothing is selected
                    selected_text = ""
                if selected_text:
                    self._edit_selected_text(
                        selected_text, raw_text, audio, start_time, detected_context, identified_speaker
                    )
                    return

            if is_action_mode:
                intent = ActionRouter.parse_intent(raw_text, is_action_mode=True, context=detected_context, conventions=conventions)
                action_name = intent.action_type
                final_text = intent.target_payload
                if can_action and action_name == "format" and final_text.strip():
                    # Action key, nothing selected, and no translate/rewrite/summarize command:
                    # the speech is a request ("write me a poem"), so write it.
                    self._edit_selected_text(
                        "", raw_text, audio, start_time, detected_context, identified_speaker, generate=True
                    )
                    return
            elif is_translation_mode:
                intent = ActionIntent(
                    action_type="translate",
                    target_payload=raw_text,
                    target_language="English",
                    system_instruction=build_prompt("translate", target_language="English", context=detected_context, conventions=conventions),
                )
                action_name = "translate"
                final_text = raw_text
            else:
                cur_lang = (getattr(self.config, "language", "en") or "").lower()
                is_nepali = cur_lang in ("ne", "ne_en") or any(
                    ord(c) >= 0x0900 and ord(c) <= 0x097F for c in raw_text
                )
                nepali_mode = None
                if is_nepali:
                    rec_mode = getattr(_ctx_info, "recommended_nepali_mode", "romanized")
                    nepali_mode = self.config.resolve_nepali_mode(rec_mode)
                    print(
                        f"[Nepglish] Context routing: app='{getattr(_ctx_info, 'app_name', 'Unknown')}', "
                        f"mode='{nepali_mode}', style='{getattr(self.config, 'romanized_style', 'cha')}'",
                        file=sys.stderr,
                    )

                intent = ActionRouter.parse_intent(
                    raw_text,
                    is_action_mode=False,
                    context=detected_context,
                    conventions=conventions,
                    nepali_mode=nepali_mode,
                    romanized_style=getattr(self.config, "romanized_style", "cha"),
                )
                action_name = intent.action_type
                final_text = intent.target_payload
            is_offline_fallback = False

            # Phase 1: Fast Typeless Draft Emission into Active Target
            # If two_phase_emission is enabled and not in action mode, insert the raw speech instantly!
            two_phase = getattr(self.config, "two_phase_emission", True)
            draft_emitted = False
            draft_text = ""
            active_app = self.inserter.get_active_app_name()

            if two_phase and not is_action_mode and action_name != "translate" and not self.inserter.draft_can_be_undone(active_app):
                print(f"[TwoPhase] No draft in '{active_app}': undo can't take it back there", file=sys.stderr)
            elif two_phase and not is_action_mode and action_name != "translate":
                # Quick clean of obvious stutters/whitespace for the draft
                draft_text = GeminiFormatter.light_local_cleanup(final_text)
                if draft_text:
                    inserted_ok, status, active_app = self.inserter.insert(
                        draft_text,
                        restore_clipboard=False,  # Don't restore yet; we may replace with polished version
                        replace_previous=False,
                    )
                    if inserted_ok and status == "inserted":
                        draft_emitted = True
                        print(
                            f"[TwoPhase] Phase 1: Draft text emitted into '{active_app}' in {int((time.time() - start_time) * 1000)}ms",
                            file=sys.stderr,
                        )
                        self.bridge.state_processing.emit("Polishing...")

            # 5. AI Formatting Layer: dynamic user choice with seamless fallback
            prefer_local = getattr(self.config, "local_ai", False) and self.local_ai.is_available()
            can_local = self.local_ai.is_available()
            local_task = self._local_task(intent, action_name, final_text, is_action_mode) if can_local else None

            # The on-device model runs when it's switched on, or as a backup when the cloud fails
            if use_gemini or (prefer_local and local_task):
                if not draft_emitted:
                    self.bridge.state_processing.emit(
                        "Translating..." if (action_name == "translate" or intent.action_type == "translate") else "Cleaning..."
                    )
                cleaned, success, msg = "", False, ""

                # If user preferred local on-device AI, try local first
                if prefer_local and local_task:
                    t_local = time.time()
                    if mixed_segments:  # a few stretches per call: the model drops parts of long text
                        if early and early.thread:
                            early.thread.join(timeout=15)  # let a translation it started finish
                        cleaned, success, msg = self._translate_segments(mixed_segments, early.translated if early else None)
                    else:
                        cleaned, success, msg = self.local_ai.run(local_task, final_text, self._speaker_context())
                    print(f"[LocalAI] {local_task} in {int((time.time() - t_local) * 1000)}ms: "
                          f"{cleaned!r}" if success else f"[LocalAI] {msg}", file=sys.stderr)
                    # If local failed, fallback to cloud if enabled
                    if not success and use_gemini:
                        print(f"[AI Fallback] Local AI failed, trying Cloud AI...", file=sys.stderr)
                        cleaned, success, msg = self.gemini.format_text(
                            raw_text=final_text,
                            style=self.config.prompt_style,
                            custom_system_instruction=intent.system_instruction,
                            draft_on_screen=draft_emitted,
                            speaker_context=self._speaker_context(),
                        )
                elif use_gemini:
                    # User preferred Cloud AI: run Cloud AI first
                    cleaned, success, msg = self.gemini.format_text(
                        raw_text=final_text,
                        style=self.config.prompt_style,
                        custom_system_instruction=intent.system_instruction,
                        draft_on_screen=draft_emitted,
                        speaker_context=self._speaker_context(),
                    )
                    # If Cloud AI failed (network, quota, timeout, error), seamlessly redirect to our on-device model!
                    if (not success or not cleaned) and can_local and local_task:
                        print(f"[AI Redirect] Cloud AI failed ({msg}), redirecting to on-device AI...", file=sys.stderr)
                        t_local = time.time()
                        if mixed_segments:
                            if early and early.thread:
                                early.thread.join(timeout=15)
                            cleaned, success, msg = self._translate_segments(mixed_segments, early.translated if early else None)
                        else:
                            cleaned, success, msg = self.local_ai.run(local_task, final_text, self._speaker_context())
                        print(f"[LocalAI Redirect] {local_task} in {int((time.time() - t_local) * 1000)}ms: "
                              f"{cleaned!r}" if success else f"[LocalAI Redirect] {msg}", file=sys.stderr)

                if success and cleaned:
                    final_text = without_fillers(without_ai_dashes(cleaned))
                else:
                    # Circuit breaker triggered or formatting error: instantly insert raw dictation
                    final_text = GeminiFormatter.light_local_cleanup(final_text)
                    is_offline_fallback = True
                    print(f"[AI Fallback/Raw Dictation]: {CredentialManager.redact(msg)}")
                    if self.tray:
                        try:
                            run_on_ui_thread(self.tray.refresh_menu)
                        except Exception:
                            pass
            else:
                final_text = GeminiFormatter.light_local_cleanup(final_text)
                is_offline_fallback = True

            final_text = fix_known_mishearings(final_text, vocabulary_terms(self.config, self.learner))

            # 6. Final Insertion: In-Place Polish replacement or single-phase insertion
            if draft_emitted:
                if final_text != draft_text:
                    # In-place polish: replace the draft with the polished text via undo + paste
                    print(f"[TwoPhase] Phase 2: Replacing draft with polished text in '{active_app}'", file=sys.stderr)
                    inserted_ok, status, active_app = self.inserter.insert(
                        final_text,
                        restore_clipboard=self.config.restore_clipboard,
                        replace_previous=True,
                    )
                else:
                    # Draft is already identical to final text! Just restore clipboard if requested
                    inserted_ok = True
                    status = "inserted"
                    if self.config.restore_clipboard:
                        orig_clip = getattr(self.inserter, "_original_clipboard", None)
                        if orig_clip is not None:
                            ClipboardManager.restore_after_delay(orig_clip, 1.0)
                    self.inserter._has_active_draft = False
            else:
                # Standard single-phase insertion (for action mode, translation mode, or if two_phase is disabled)
                inserted_ok, status, active_app = self.inserter.insert(
                    final_text,
                    restore_clipboard=self.config.restore_clipboard,
                )

            total_latency_ms = int((time.time() - start_time) * 1000)

            # 7. UI Status Feedback
            if status == "inserted":
                if is_offline_fallback:
                    self.bridge.state_inserted_offline.emit()
                else:
                    self.bridge.state_inserted.emit()
            else:
                self.bridge.state_copied.emit()

            # 8. Save to local history database with speaker attribution
            status_to_save = "inserted (offline)" if (status == "inserted" and is_offline_fallback) else status
            try:
                self.db.add(
                    raw_transcription=raw_text,
                    processed_text=final_text,
                    action=action_name,
                    application=active_app,
                    status=status_to_save,
                    duration_ms=total_latency_ms,
                    speaker=identified_speaker,
                    context=detected_context,
                    duration_sec=round(len(audio) / 16000, 2) if audio is not None else 0.0,
                )
            except Exception as db_err:
                print(f"[Database] Failed to record history: {db_err}", file=sys.stderr)
            try:
                self._learn_from_dictation(raw_text, final_text, action_name)
            except Exception as learn_err:
                print(f"[Learner] {learn_err}", file=sys.stderr)

            # Refresh home recent items if visible (must dispatch to main thread)
            if self.main_window and self.main_window.isVisible():
                try:
                    run_on_ui_thread(self.main_window._refresh_home_status)
                except Exception:
                    pass

        except Exception as e:
            print(f"[Pipeline] Uncaught error in audio pipeline: {e}", file=sys.stderr)
            if hasattr(self, "inserter"):
                self.inserter.cancel_draft()
            try:
                self.bridge.state_error.emit("Processing error")
            except Exception:
                pass


    def _edit_selected_text(
        self,
        selected_text: str,
        instruction: str,
        audio,
        start_time: float,
        detected_context: str,
        identified_speaker: Optional[str],
        generate: bool = False,
    ) -> None:
        """Action Mode: rewrite the selection per the spoken instruction, or (generate=True,
        nothing selected) write new text from the spoken request."""
        use_gemini = getattr(self.config, "gemini_enabled", True) and not getattr(self.config, "offline_mode", False)
        use_local = getattr(self.config, "local_ai", False) and hasattr(self, "local_ai") and self.local_ai.is_available()
        can_local = hasattr(self, "local_ai") and self.local_ai.is_available()

        edited, success, msg = "", False, ""

        if generate:
            print(f"[Generate] request: {instruction!r}", file=sys.stderr)
            self.bridge.state_processing.emit("Writing...")
            if use_gemini:
                edited, success, msg = self.gemini.format_text(
                    raw_text=instruction,
                    style=GENERATE_STYLE,
                    custom_system_instruction=build_generate_prompt(context=detected_context),
                )
            if (not success or not edited) and (use_local or can_local):
                print(f"[Generate] Cloud AI unavailable or failed ({msg}), redirecting to on-device AI...", file=sys.stderr)
                edited, success, msg = self.local_ai.run("generate", instruction, f"Context: {detected_context}")
        else:
            print(f"[EditSelection] {len(selected_text)} chars selected, instruction: {instruction!r}", file=sys.stderr)
            self.bridge.state_processing.emit("Editing selection...")
            if use_gemini:
                edited, success, msg = self.gemini.format_text(
                    raw_text=selected_text,
                    style=EDIT_SELECTION_STYLE,
                    custom_system_instruction=build_edit_selection_prompt(instruction, context=detected_context),
                    edit_instruction=instruction,
                )
            if (not success or not edited) and (use_local or can_local):
                print(f"[EditSelection] Cloud AI unavailable or failed ({msg}), redirecting to on-device AI...", file=sys.stderr)
                edit_input = f"Instruction: {instruction}\n\nSelected text:\n{selected_text}"
                edited, success, msg = self.local_ai.run("edit", edit_input, f"Context: {detected_context}")

        if not success or not edited:
            # Leave the user's text untouched rather than pasting an unedited copy over it
            print(f"[{'Generate' if generate else 'EditSelection'}] AI failed: {CredentialManager.redact(msg)}", file=sys.stderr)
            self.bridge.state_error.emit("Couldn't write that" if generate else "Couldn't edit selection")
            return

        edited = without_fillers(without_ai_dashes(edited))
        inserted_ok, status, active_app = self.inserter.insert(
            edited,
            restore_clipboard=self.config.restore_clipboard,
        )
        if status == "inserted":
            self.bridge.state_inserted.emit()
        else:
            self.bridge.state_copied.emit()

        try:
            self.db.add(
                raw_transcription=instruction,
                processed_text=edited,
                action=GENERATE_STYLE if generate else EDIT_SELECTION_STYLE,
                application=active_app,
                status=status,
                duration_ms=int((time.time() - start_time) * 1000),
                speaker=identified_speaker,
                context=detected_context,
                duration_sec=round(len(audio) / 16000, 2) if audio is not None else 0.0,
            )
        except Exception as db_err:
            print(f"[Database] Failed to record history: {db_err}", file=sys.stderr)

    def last_dictation_text(self) -> str:
        """Most recent dictation output, or "" when history is empty."""
        try:
            recent = self.db.get_recent(limit=1)
        except Exception:
            return ""
        return recent[0].processed_text if recent else ""

    def paste_last_dictation(self) -> None:
        """Global shortcut: type the last dictation again into the focused app."""
        if self.recorder.is_recording:
            return
        threading.Thread(target=self._paste_last_worker, daemon=True).start()

    def _paste_last_worker(self) -> None:
        ignored = getattr(self, "_last_ignored", None)
        if ignored and time.time() - ignored[2] < self.IGNORED_VOICE_RECOVERY_SEC:
            # "That was me": type the dictation the voice filter skipped and learn from it
            self._last_ignored = None
            audio, emb, _, was_action_mode = ignored
            self._learn_voice_sample(emb)
            self.inserter.wait_for_modifiers_released()
            self.inserter.capture_active_target()
            print("[PasteLast] Recovering dictation ignored as another voice", file=sys.stderr)
            self._process_audio_pipeline(audio, was_action_mode, force_accept_speaker=True)
            return

        text = self.last_dictation_text()
        if not text:
            self.bridge.state_error.emit("Nothing to paste yet")
            return
        # The shortcut's own modifiers are still down; pasting now would send e.g. Ctrl+Cmd+V again
        self.inserter.wait_for_modifiers_released()
        self.inserter.capture_active_target()
        _ok, status, _app = self.inserter.insert(text, restore_clipboard=self.config.restore_clipboard)
        print(f"[PasteLast] Re-pasted last dictation ({len(text)} chars) -> {status}", file=sys.stderr)
        if status == "inserted":
            self.bridge.state_inserted.emit()
        else:
            self.bridge.state_copied.emit()

    IGNORED_VOICE_RECOVERY_SEC = 60.0

    def _learn_voice_sample(self, emb) -> None:
        """Fold a confirmed sample into the closest enrolled profile."""
        try:
            profiles = profiles_from_records(self.db.get_voice_profile_records())
            if not profiles:
                return
            best = max(profiles, key=lambda p: float(np.dot(emb, p.embedding)))
            updated = adapt_profile(best.embedding, emb, best.sample_count)
            self.db.update_voice_profile_embedding(best.name, updated, best.sample_count + 1)
            print(f"[SpeakerID] Learned from confirmed sample for '{best.name}'", file=sys.stderr)
        except Exception as e:
            print(f"[SpeakerID] Could not update profile: {e}", file=sys.stderr)

    def copy_last_dictation(self) -> None:
        """Tray menu: put the last dictation on the clipboard."""
        text = self.last_dictation_text()
        if text:
            ClipboardManager.set_text(text)
            self.bridge.state_copied.emit()
        else:
            self.bridge.state_error.emit("Nothing to copy yet")

    def _on_toggle_gemini(self, enabled: bool) -> None:
        self.config.gemini_enabled = enabled
        self.config.save()
        if self.main_window:
            self.main_window._refresh_home_status()

    def _on_change_tier(self, tier_id: str) -> None:
        self.config.model_tier = tier_id
        self.config.save()
        threading.Thread(
            target=lambda: self.stt_engine.load(tier_id),
            daemon=True,
        ).start()
        if self.main_window:
            self.main_window._refresh_home_status()

    def _on_config_updated(self, new_config: AppConfig) -> None:
        self.config = new_config
        provider_id = getattr(self.config, "ai_provider", "gemini") or "gemini"
        model = getattr(self.config, "ai_model", "") or self.config.gemini_model
        if provider_id == "ollama":
            custom_base = getattr(self.config, "ollama_base_url", "http://localhost:11434/v1") or "http://localhost:11434/v1"
            model = getattr(self.config, "ollama_model", "") or "qwen2.5-coder:7b"
        else:
            custom_base = getattr(self.config, "custom_api_base_url", "")
        if hasattr(self.gemini, "set_provider"):
            self.gemini.set_provider(
                provider_id=provider_id,
                api_key=CredentialManager.get_provider_api_key(provider_id),
                model_name=model,
                custom_base_url=custom_base,
            )
        else:
            self.gemini.set_api_key(CredentialManager.get_api_key())
            self.gemini.set_model(self.config.gemini_model)
        self.recorder.set_device(self.config.audio_device_index)
        if self.shortcut_manager:
            self.shortcut_manager.reload(
                shortcut=self.config.shortcut,
                action_shortcut=self.config.action_shortcut,
                push_to_talk=self.config.push_to_talk,
            )
        # Hot-swap or reload STT engine if provider/tier changed
        self.stt_engine = create_stt_engine_for_config(self.config, self.model_manager)
        if getattr(self.config, "stt_provider", "os_native") == "whisper":
            custom_stt = self.config.custom_stt_model_path if getattr(self.config, "stt_model_source", "bundled") == "custom" else None
            threading.Thread(
                target=lambda: self.stt_engine.load(self.config.model_tier, custom_target=custom_stt),
                daemon=True,
            ).start()
        else:
            self.stt_engine.load()

    def set_stt_provider(self, provider_id: str) -> None:
        """Hot-swap the active speech-to-text engine at runtime without restart."""
        print(f"[App] Hot-swapping STT provider to: {provider_id}", file=sys.stderr)
        self.config.stt_provider = provider_id
        self.config.save()
        self.stt_engine = create_stt_engine_for_config(self.config, self.model_manager)
        if provider_id == "whisper":
            custom_stt = self.config.custom_stt_model_path if getattr(self.config, "stt_model_source", "bundled") == "custom" else None
            threading.Thread(
                target=lambda: self.stt_engine.load(self.config.model_tier, custom_target=custom_stt),
                daemon=True,
            ).start()
        else:
            self.stt_engine.load()

    def cleanup(self) -> None:
        """Restore system audio and release the hotkey listener and microphone."""
        if hasattr(self, "audio_ducker"):
            self.audio_ducker.unmute()
        if self.shortcut_manager:
            self.shortcut_manager.stop()
        if self.recorder:
            self.recorder.stop()

    def quit(self) -> None:
        """Clean shutdown."""
        app = QApplication.instance()
        if app is not None:
            app.is_quitting = True
        self.cleanup()
        QApplication.quit()


def main() -> None:
    """Desktop application entrypoint."""
    multiprocessing.freeze_support()

    # Route logs to app data directory so background app issues can be diagnosed
    try:
        from ..config import get_app_data_dir
        log_path = get_app_data_dir() / "app.log"
        class FileLogger:
            def __init__(self, path, original_stream):
                self.f = open(path, "a", encoding="utf-8", buffering=1)
                self.orig = original_stream
            def write(self, s):
                try:
                    self.f.write(s)
                except Exception:
                    pass
                if self.orig:
                    try:
                        self.orig.write(s)
                    except Exception:
                        pass
            def flush(self):
                try:
                    self.f.flush()
                except Exception:
                    pass
                if self.orig:
                    try:
                        self.orig.flush()
                    except Exception:
                        pass

        sys.stdout = FileLogger(log_path, sys.stdout)
        sys.stderr = FileLogger(log_path, sys.stderr)
        print(f"\n=== Just Talk Started ({datetime.datetime.now()}) ===", file=sys.stderr)
    except Exception:
        pass

    # Headless CLI: Pre-download model (invoked by Windows installer or setup scripts)
    if "--download-model" in sys.argv or "--prewarm" in sys.argv:
        print("[Setup] Checking / downloading Whisper speech recognition model...", file=sys.stderr)
        try:
            from ..config import AppConfig
            from ..stt.model_manager import ModelManager

            cfg = AppConfig.load()
            mgr = ModelManager()
            tier = cfg.model_tier or "quality"

            def cli_progress(pct: float, msg: str):
                if pct > 0:
                    sys.stderr.write(f"\r[Setup] {msg}   ")
                    sys.stderr.flush()

            if not mgr.is_model_downloaded(tier):
                mgr.download_model(tier, progress_callback=cli_progress)
            print("\n[Setup] Whisper speech model is fully ready.", file=sys.stderr)
        except Exception as err:
            print(f"\n[Setup] Model pre-download warning: {err}", file=sys.stderr)
        sys.exit(0)

    app = JustTalkApplication(sys.argv)
    app.setApplicationName("Just Talk")
    app.setOrganizationName("JustTalk")
    app.setQuitOnLastWindowClosed(False)  # Stays alive in system tray / background
    install_wheel_guard(app)  # Scrolling a page must not change dropdowns under the pointer

    # Enforce strict single-instance lock
    from .single_instance import SingleInstanceManager

    single_instance = SingleInstanceManager()
    if not single_instance.try_lock():
        print(
            "[JustTalk] Another instance of Just Talk is already running. Focused existing window. Exiting."
        )
        sys.exit(0)

    controller = JustTalkApp()
    app.controller = controller
    single_instance.on_activate = lambda: controller.reopen()
    controller.initialize_ui(app)

    exit_code = app.exec()
    single_instance.cleanup()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
