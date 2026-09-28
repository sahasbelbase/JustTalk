import multiprocessing
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
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("justtalk.desktop.voiceinput.1.0")
    except Exception as e:
        print(f"[Main] Warning: Could not set AppUserModelID: {e}", file=sys.stderr)

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from ..ai.actions import ActionRouter
from ..ai.gemini import GeminiFormatter
from ..audio.recorder import AudioRecorder
from ..audio.vad import VoiceActivityDetector
from ..config import AppConfig
from ..database.history import HistoryDatabase
from ..security import CredentialManager
from ..shortcuts.manager import ShortcutManager
from ..stt.model_manager import ModelManager
from ..stt.whisper_engine import WhisperSTTEngine
from ..system.inserter import TextInserter
from ..system.permissions import PermissionsManager
from .history_window import HistoryWindow
from .overlay import FloatingPillOverlay
from .settings_window import SettingsWindow
from .tray import SystemTrayManager


class AppBridge(QObject):
    """Qt signal bridge to dispatch audio and worker events safely to the main GUI thread."""

    level_changed = Signal(float)
    state_listening = Signal(bool)
    state_processing = Signal(str)
    state_inserted = Signal()
    state_copied = Signal()
    state_error = Signal(str)


class JustTalkApp:
    """Core controller coordinating audio, local ML, Gemini formatting, and system insertion."""

    def __init__(self):
        self.config = AppConfig.load()
        self.db = HistoryDatabase()
        # Purge records older than user retention setting
        self.db.purge_expired(self.config.history_retention_days)

        self.bridge = AppBridge()
        self.overlay: Optional[FloatingPillOverlay] = None
        self.tray: Optional[SystemTrayManager] = None
        self.settings_window: Optional[SettingsWindow] = None
        self.history_window: Optional[HistoryWindow] = None

        # Core subsystems
        self.vad = VoiceActivityDetector()
        self.recorder = AudioRecorder(
            device_index=self.config.audio_device_index,
            level_callback=lambda rms: self.bridge.level_changed.emit(rms),
        )
        self.model_manager = ModelManager()
        self.stt_engine = WhisperSTTEngine(self.model_manager)
        self.gemini = GeminiFormatter(
            api_key=CredentialManager.get_api_key(),
            model_name=self.config.gemini_model,
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
        app_icon = self.get_app_icon()
        app.setWindowIcon(app_icon)

        self.overlay = FloatingPillOverlay()

        # Connect Qt signals to overlay UI
        self.bridge.level_changed.connect(self.overlay.update_audio_level)
        self.bridge.state_listening.connect(self.overlay.show_listening)
        self.bridge.state_processing.connect(self.overlay.show_processing)
        self.bridge.state_inserted.connect(self.overlay.show_inserted)
        self.bridge.state_copied.connect(self.overlay.show_copied)
        self.bridge.state_error.connect(self.overlay.show_error)

        # System tray
        self.tray = SystemTrayManager(
            config=self.config,
            icon=app_icon,
            on_open_history=self.open_history,
            on_open_settings=self.open_settings,
            on_toggle_gemini=self._on_toggle_gemini,
            on_change_tier=self._on_change_tier,
            on_quit=self.quit,
        )
        self.tray.show()

        # Check OS permissions quietly without intrusive popup dialogs
        PermissionsManager.check_accessibility(prompt_if_needed=False)
        PermissionsManager.check_microphone()

        # Warm up the selected Whisper model in a background thread for instant response
        threading.Thread(
            target=lambda: self.stt_engine.load(self.config.model_tier),
            daemon=True,
        ).start()

        # Register global keyboard shortcuts
        self.shortcut_manager = ShortcutManager(
            shortcut=self.config.shortcut,
            action_shortcut=self.config.action_shortcut,
            push_to_talk=self.config.push_to_talk,
            on_start_recording=self.on_start_recording,
            on_stop_recording=self.on_stop_recording,
        )
        self.shortcut_manager.start()

    def on_start_recording(self, is_action_mode: bool = False) -> None:
        """Triggered when push-to-talk shortcut is pressed."""
        self._is_action_mode = is_action_mode
        self._record_start_time = time.time()
        self.bridge.state_listening.emit(is_action_mode)
        self.recorder.start()

    def on_stop_recording(self) -> None:
        """Triggered when push-to-talk shortcut is released."""
        audio = self.recorder.stop()
        if audio is None or len(audio) == 0:
            self.bridge.state_error.emit("No audio")
            return

        # Voice Activity Detection: Filter out accidental taps and pure silence
        if not self.vad.is_speech_present(audio):
            self.bridge.state_error.emit("No speech detected")
            return

        self.bridge.state_processing.emit("Transcribing...")
        # Dispatch transcription and formatting to background worker
        threading.Thread(
            target=self._process_audio_pipeline,
            args=(audio, self._is_action_mode),
            daemon=True,
        ).start()

    def _process_audio_pipeline(self, audio, is_action_mode: bool) -> None:
        """Background pipeline: STT -> Gemini -> Insertion -> Database."""
        start_time = time.time()

        # 1. Local Speech-to-Text
        raw_text = self.stt_engine.transcribe(audio, language=self.config.language)
        if not raw_text or not raw_text.strip():
            self.bridge.state_error.emit("No speech detected")
            return

        raw_text = raw_text.strip()
        print(f"[STT Raw]: {raw_text}")

        # 2. Action Routing & Intent Detection
        intent = ActionRouter.parse_intent(raw_text, is_action_mode=is_action_mode)
        final_text = raw_text
        action_name = intent.action_type

        # 3. Gemini Formatting Layer
        use_gemini = self.config.gemini_enabled and not self.config.offline_mode
        if use_gemini:
            self.bridge.state_processing.emit(
                "Translating..." if intent.action_type == "translate" else "Cleaning..."
            )
            cleaned, success, msg = self.gemini.format_text(
                raw_text=intent.target_payload,
                style=self.config.prompt_style,
                custom_system_instruction=intent.system_instruction,
            )
            if success and cleaned:
                final_text = cleaned
            else:
                # Zero-loss fallback: if Gemini fails or times out, use raw transcription
                final_text = intent.target_payload
                print(f"[Gemini Fallback]: {msg}")

        # 4. Text Insertion
        inserted_ok, status, active_app = self.inserter.insert(
            final_text,
            restore_clipboard=self.config.restore_clipboard,
        )

        total_latency_ms = int((time.time() - start_time) * 1000)

        # 5. UI Status Feedback
        if status == "inserted":
            self.bridge.state_inserted.emit()
        else:
            self.bridge.state_copied.emit()

        # 6. Save to local history database
        self.db.add(
            raw_transcription=raw_text,
            processed_text=final_text,
            action=action_name,
            application=active_app,
            status=status,
            duration_ms=total_latency_ms,
        )

    def _on_toggle_gemini(self, enabled: bool) -> None:
        self.config.gemini_enabled = enabled
        self.config.save()

    def _on_change_tier(self, tier_id: str) -> None:
        self.config.model_tier = tier_id
        self.config.save()
        threading.Thread(
            target=lambda: self.stt_engine.load(tier_id),
            daemon=True,
        ).start()

    def open_settings(self) -> None:
        """Display settings window."""
        if not self.settings_window:
            self.settings_window = SettingsWindow(
                config=self.config,
                model_manager=self.model_manager,
                on_config_changed=self._on_config_updated,
            )
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _on_config_updated(self, new_config: AppConfig) -> None:
        self.config = new_config
        self.gemini.set_api_key(CredentialManager.get_api_key())
        self.gemini.set_model(self.config.gemini_model)
        self.recorder.set_device(self.config.audio_device_index)
        if self.shortcut_manager:
            self.shortcut_manager.reload(
                shortcut=self.config.shortcut,
                action_shortcut=self.config.action_shortcut,
                push_to_talk=self.config.push_to_talk,
            )
        # Reload model if tier changed
        threading.Thread(
            target=lambda: self.stt_engine.load(self.config.model_tier),
            daemon=True,
        ).start()

    def open_history(self) -> None:
        """Display history window."""
        if not self.history_window:
            self.history_window = HistoryWindow(self.db)
        self.history_window.load_history()
        self.history_window.show()
        self.history_window.raise_()
        self.history_window.activateWindow()

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

    app = QApplication(sys.argv)
    app.setApplicationName("Just Talk")
    app.setOrganizationName("JustTalk")
    app.setQuitOnLastWindowClosed(False)  # Stays alive in system tray

    # Enforce strict single-instance lock
    from .single_instance import SingleInstanceManager
    single_instance = SingleInstanceManager()
    if not single_instance.try_lock():
        print("[JustTalk] Another instance of Just Talk is already running. Focused existing window. Exiting.")
        sys.exit(0)

    controller = JustTalkApp()
    single_instance.on_activate = controller.open_settings
    controller.initialize_ui(app)

    exit_code = app.exec()
    single_instance.cleanup()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
