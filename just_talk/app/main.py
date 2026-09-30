"""Desktop application entrypoint and main coordinator."""

from __future__ import annotations

import multiprocessing
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

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

from PySide6.QtCore import QEvent, QObject, Qt, Signal, Slot, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from ..ai.actions import ActionRouter
from ..ai.gemini import GeminiFormatter
from ..ai.providers import MultiProviderFormatter
from ..audio.recorder import AudioRecorder
from ..audio.vad import VoiceActivityDetector
from ..config import AppConfig
from ..database.history import HistoryDatabase
from ..security import CredentialManager
from ..shortcuts.manager import ShortcutManager
from ..stt.model_manager import ModelManager
from ..stt.whisper_engine import WhisperSTTEngine
from ..system.autostart import AutostartManager
from ..system.inserter import TextInserter
from ..system.permissions import PermissionsManager
from .main_window import MainWindow
from .onboarding_window import OnboardingWindow
from .overlay import FloatingPillOverlay
from .theme import ThemeManager
from .tray import SystemTrayManager


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


class JustTalkApplication(QApplication):
    """
    Subclassed QApplication to handle macOS Dock icon clicks and reopen events.
    """

    def __init__(self, argv):
        super().__init__(argv)
        self.controller: Optional[JustTalkApp] = None
        self._setup_mac_reopen()

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
        self.stt_engine = WhisperSTTEngine(self.model_manager)
        provider_id = getattr(self.config, "ai_provider", "gemini") or "gemini"
        model = getattr(self.config, "ai_model", "") or self.config.gemini_model
        custom_base = getattr(self.config, "custom_api_base_url", "")
        self.gemini = MultiProviderFormatter(
            provider_id=provider_id,
            api_key=CredentialManager.get_provider_api_key(provider_id),
            model_name=model,
            custom_base_url=custom_base,
            timeout=getattr(self.config, "formatting_budget_sec", 3.0),
        )
        self.inserter = TextInserter()
        self.shortcut_manager: Optional[ShortcutManager] = None

        self._is_action_mode = False
        self._record_start_time = 0.0

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

        # 4. System Tray
        self.tray = SystemTrayManager(
            config=self.config,
            icon=app_icon,
            on_open_main=self.open_main_window,
            on_toggle_gemini=self._on_toggle_gemini,
            on_change_tier=self._on_change_tier,
            on_quit=self.quit,
            gemini=self.gemini,
        )
        self.tray.show()

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

        # 7. Warm up Whisper model in background
        threading.Thread(
            target=lambda: self.stt_engine.load(self.config.model_tier),
            daemon=True,
        ).start()

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
        )
        self.shortcut_manager.start()

        # 9. Main-thread visualizer timer (50 Hz / 20ms) for rock-solid UI updates without audio thread locking
        self._level_timer = QTimer(self.bridge)
        self._level_timer.setInterval(20)
        self._level_timer.timeout.connect(self._poll_audio_level)

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

    def reopen(self) -> None:
        """Reopen or activate the main application window or onboarding wizard."""
        if not self.config.has_completed_onboarding and self.onboarding_window and self.onboarding_window.isVisible():
            self.show_onboarding()
        else:
            self.open_main_window("home")

    def open_main_window(self, screen_name: Optional[str] = "home") -> None:
        """Open or raise the main full application window."""
        if self.main_window:
            self.main_window.show_and_activate(screen_name)

    def show_onboarding(self) -> None:
        """Open the 5-step onboarding wizard."""
        if not self.onboarding_window:
            self.onboarding_window = OnboardingWindow(
                config=self.config,
                gemini=self.gemini,
                model_manager=self.model_manager,
                on_complete=lambda: self.open_main_window("home"),
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

    def _poll_audio_level(self) -> None:
        """Poll current RMS level from recorder on main Qt thread and update visualizer."""
        if self.recorder and self.recorder.is_recording and self.overlay:
            lvl = self.recorder.get_audio_level()
            self.overlay.update_audio_level(lvl)

    @Slot(bool)
    def on_start_recording(self, is_action_mode: bool = False) -> None:
        """Triggered on the main Qt thread when push-to-talk shortcut is pressed."""
        self._is_action_mode = is_action_mode
        self._record_start_time = time.time()
        print(f"[Record] START recording (action_mode={is_action_mode})", file=sys.stderr)
        self.bridge.state_listening.emit(is_action_mode)
        started = self.recorder.start()
        if not started:
            print("[Record] ERROR: Microphone failed to start!", file=sys.stderr)
            self.bridge.state_error.emit("Microphone error")
        else:
            self._level_timer.start()
            print("[Record] Microphone stream opened successfully.", file=sys.stderr)

    def _on_cancel_recording(self) -> None:
        """User cancelled recording via the overlay [ ✕ ] button."""
        self._level_timer.stop()
        if self.overlay:
            self.overlay.update_audio_level(0.0)
        self.recorder.stop()
        if self.shortcut_manager:
            self.shortcut_manager.reset_state()
        self.bridge.state_error.emit("Cancelled")

    @Slot()
    def on_stop_recording(self) -> None:
        """Triggered on the main Qt thread when push-to-talk shortcut is released or checkmark is clicked."""
        self._level_timer.stop()
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
        print(f"[Record] VAD result: speech_present={vad_result} "
              f"(threshold={self.vad.energy_threshold}, min_dur={self.vad.min_speech_duration_sec}s)", file=sys.stderr)

        if not vad_result:
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
        threading.Thread(
            target=self._process_audio_pipeline,
            args=(audio, self._is_action_mode),
            daemon=True,
        ).start()

    def _process_audio_pipeline(self, audio, is_action_mode: bool) -> None:
        """Background pipeline: STT -> Gemini -> Insertion -> Database."""
        try:
            start_time = time.time()

            # 0. Check if STT model is loaded or downloading
            if not self.stt_engine.is_loaded():
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

            # 1. Local Speech-to-Text with Multilingual & Dual-Task Support
            speech_mode = getattr(self.config, "speech_mode", "transcribe")
            task = "translate" if speech_mode == "translate" else "transcribe"
            lang = self.config.language if self.config.language not in ("auto", "none", "", None) else None

            if task == "translate":
                self.bridge.state_processing.emit("Translating speech to English...")
            else:
                self.bridge.state_processing.emit("Transcribing...")

            raw_text = self.stt_engine.transcribe(audio, language=lang, task=task)
            # Automatic fallback: if configured language yielded nothing, try auto-detection
            if (not raw_text or not raw_text.strip()) and lang:
                raw_text = self.stt_engine.transcribe(audio, language=None, task=task)

            if not raw_text or not raw_text.strip():
                print("[STT] Whisper returned empty transcription → 'No speech recognized'", file=sys.stderr)
                self.bridge.state_error.emit("No speech recognized")
                return

            raw_text = raw_text.strip()
            print(f"[STT Raw (task={task}, lang={lang})]: {raw_text}")

            # 2. Action Routing & Intent Detection
            if task == "translate":
                # Speech already translated into English by Whisper
                intent = ActionRouter.parse_intent(raw_text, is_action_mode=False)
                action_name = "translate"
                final_text = raw_text
            else:
                intent = ActionRouter.parse_intent(raw_text, is_action_mode=is_action_mode)
                action_name = intent.action_type
                final_text = intent.target_payload
            is_offline_fallback = False

            # 3. Gemini Formatting Layer
            use_gemini = self.config.gemini_enabled and not self.config.offline_mode
            if use_gemini:
                self.bridge.state_processing.emit(
                    "Translating..." if intent.action_type == "translate" else "Cleaning..."
                )
                cleaned, success, msg = self.gemini.format_text(
                    raw_text=final_text,
                    style=self.config.prompt_style,
                    custom_system_instruction=intent.system_instruction,
                )
                if success and cleaned:
                    final_text = cleaned
                else:
                    final_text = cleaned
                    is_offline_fallback = True
                    print(f"[Gemini Fallback]: {CredentialManager.redact(msg)}")
                    if self.tray:
                        try:
                            QTimer.singleShot(0, self.tray.refresh_menu)
                        except Exception:
                            pass
            else:
                final_text = GeminiFormatter.light_local_cleanup(final_text)
                is_offline_fallback = True

            # 4. Text Insertion
            inserted_ok, status, active_app = self.inserter.insert(
                final_text,
                restore_clipboard=self.config.restore_clipboard,
            )

            total_latency_ms = int((time.time() - start_time) * 1000)

            # 5. UI Status Feedback
            if status == "inserted":
                if is_offline_fallback:
                    self.bridge.state_inserted_offline.emit()
                else:
                    self.bridge.state_inserted.emit()
            else:
                self.bridge.state_copied.emit()

            # 6. Save to local history database (always preserving raw transcription)
            status_to_save = "inserted (offline)" if (status == "inserted" and is_offline_fallback) else status
            try:
                self.db.add(
                    raw_transcription=raw_text,
                    processed_text=final_text,
                    action=action_name,
                    application=active_app,
                    status=status_to_save,
                    duration_ms=total_latency_ms,
                )
            except Exception as db_err:
                print(f"[Database] Failed to record history: {db_err}", file=sys.stderr)

            # Refresh home recent items if visible (must dispatch to main thread)
            if self.main_window and self.main_window.isVisible():
                try:
                    QTimer.singleShot(0, self.main_window._refresh_home_status)
                except Exception:
                    pass

        except Exception as e:
            print(f"[Pipeline] Uncaught error in audio pipeline: {e}", file=sys.stderr)
            try:
                self.bridge.state_error.emit("Processing error")
            except Exception:
                pass


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
        # Sync autostart
        AutostartManager.set_autostart(self.config.launch_at_startup)

        # Reload model if tier changed
        threading.Thread(
            target=lambda: self.stt_engine.load(self.config.model_tier),
            daemon=True,
        ).start()

    def quit(self) -> None:
        """Clean shutdown."""
        if self.shortcut_manager:
            self.shortcut_manager.stop()
        if self.recorder:
            self.recorder.stop()
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
            tier = cfg.model_tier or "balanced"
            if not mgr.is_model_downloaded(tier):
                mgr.download_model(tier)
            print("[Setup] Whisper speech model is fully ready.", file=sys.stderr)
        except Exception as err:
            print(f"[Setup] Model pre-download warning: {err}", file=sys.stderr)
        sys.exit(0)

    app = JustTalkApplication(sys.argv)
    app.setApplicationName("Just Talk")
    app.setOrganizationName("JustTalk")
    app.setQuitOnLastWindowClosed(False)  # Stays alive in system tray / background

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
