# Just Talk — System Architecture & Technical Specifications 🎙️

> **High-performance, privacy-first, on-device voice keyboard for macOS and Windows.**  
> Think → Speak → Done.

---

## 1. Executive Summary & Design Principles

**Just Talk** is a lightweight desktop productivity utility designed to provide sub-second voice-to-text dictation across any desktop application. Operating unobtrusively in the background via the system menu bar (macOS) or taskbar notification area (Windows), Just Talk captures audio upon a global push-to-talk key press, transcribes it on-device, enhances it via deterministic AI formatting, and inserts the result directly into the active text field.

### Core Architectural Principles:
1. **Zero Audio Exfiltration (Privacy-First):** Raw speech audio is processed 100% locally on your machine using `faster-whisper` (CTranslate2). No audio bytes ever leave the device.
2. **Sub-Second Latency:** Streaming 16kHz audio buffer, voice activity detection (VAD), and hardware-accelerated local inference guarantee minimal latency between releasing the key and text insertion.
3. **Deterministic & Resilient AI Formatting:** If enabled, only the plain-text transcript is sent to Google Gemini for subtle punctuation, capitalization, and filler-word removal. If offline or if the API exceeds a 2.0s threshold, the system immediately falls back to raw local transcription.
4. **Non-Intrusive Desktop Integration:** True clipboard preservation restores prior clipboard contents after simulated paste; active window detection ensures text lands where the user expects or falls back safely to the system clipboard.
5. **Modern Native Aesthetics:** Adheres strictly to macOS Big Sur/Sonoma/Sequoia visual standards (frosted glass acrylics, SF Pro / Inter typography, smooth state animations) while fully supporting Windows 10/11 taskbar conventions.

---

## 2. High-Level System Architecture

```mermaid
graph TD
    User([User]) -->|Hold Push-to-Talk Key| Shortcuts[Shortcut Manager<br/>mac_hook: CGEventTap / fallback_hook: pynput]
    
    subgraph Audio & STT Pipeline [Local Audio & Inference Engine]
        Shortcuts -->|Start Recording| Recorder[Audio Recorder<br/>sounddevice 16kHz PCM Buffer]
        Recorder -->|RMS Audio Level| AppBridge[Qt AppBridge Signals]
        AppBridge -->|Live Meter| Overlay[Floating Pill Overlay]
        Shortcuts -->|Release Key| Recorder
        Recorder -->|Raw PCM Array| VAD[Voice Activity Detector<br/>Silence Trimming & Energy Threshold]
        VAD -->|Clean Audio Chunk| Whisper[Whisper Engine<br/>faster-whisper CTranslate2]
        Whisper -->|Raw Transcript| Router[Action Router & AI Formatter]
    end

    subgraph AI Formatting [Cloud Enhancement / Offline Fallback]
        Router -->|Normal Mode| Gemini[Gemini API Formatter<br/>Strict 2.0s Timeout Fallback]
        Router -->|Action Mode: Fn+Shift| Actions[Intent Action Engine<br/>Translate / Summarize / Polish]
        Gemini -->|Enhanced Text| Inserter[Text Inserter]
        Actions -->|Transformed Text| Inserter
        Whisper -.->|Fallback on Timeout / Offline| Inserter
    end

    subgraph System Integration & GUI [Application Shell & OS Bridge]
        Inserter -->|Active App Detection| AppDetector[macOS NSWorkspace / Win32 API]
        Inserter -->|1. Backup Clipboard| Clip[Clipboard Manager]
        Inserter -->|2. Paste Cmd+V / Ctrl+V| OSInput[Quartz CGEvent / Win32 SendInput]
        Inserter -->|3. Restore Clipboard| Clip
        Inserter -->|Log Record| DB[(SQLite History DB<br/>30-day Retention)]
        
        AppBridge -->|Status Updates| MainWindow[Dual-Mode Main Window]
        AppBridge -->|Status Updates| Tray[System Tray Manager]
        AppBridge -->|Success / Offline Badges| Overlay
    end
```

---

## 3. Subsystem Breakdown

### 3.1 Application Core & Lifecycle (`just_talk/app/`)
* **`main.py`:** Central coordinator. Initializes `QApplication`, configures `freeze_support()` for PyInstaller multiprocessing, sets the Windows `AppUserModelID` (`justtalk.desktop.voiceinput.1.0`) to preserve taskbar pinning, and orchestrates inter-module event signals via `AppBridge`.
* **`single_instance.py`:** Enforces single-process execution using a cross-platform IPC socket / mutex mechanism. Prevents multiple instances from competing for audio devices or global hotkeys.
* **`AppBridge`:** Qt `QObject` signal bridge that decouples background worker threads (audio streaming, neural inference, API calls) from the Qt main GUI thread. Signals include `level_changed`, `state_listening`, `state_processing`, `state_inserted`, and `state_inserted_offline`.

### 3.2 UI & Design System (`just_talk/app/`)
* **`theme.py`:** Comprehensive macOS-inspired design system:
  * **Typography:** Embedded variable fonts (`Inter`, `Lato`, `JetBrains Mono`, `Instrument Serif`).
  * **Palette:** Semantic dark/light tokens with translucent surfaces, acrylic borders, smooth hover states, and dynamic status badges.
  * **Custom Controls:** Frosted-glass styled push buttons, custom slider bars, segmented tabs, and rounded combo boxes.
* **`overlay.py` (`FloatingPillOverlay`):** Unobtrusive, borderless floating pill HUD displayed on the user's active screen during speech capture:
  * **Idle:** Hidden or docked.
  * **Listening:** Dynamic multi-bar audio waveform visualizing mic input levels in real time.
  * **Processing:** Smooth pulsing status indicator.
  * **Inserted:** Subtle emerald badge confirmating successful text dispatch.
* **`main_window.py`:** macOS split-view preferences and control center:
  * *Dictation & Status:* Live audio meter, push-to-talk shortcut trigger configuration, mic selector, active Whisper model tier.
  * *History:* Searchable, filterable dictation logs with one-click copy and deletion.
  * *AI Formatting:* Temperature sliders, formatting mode presets (Subtle, Formal, Concise, Code), custom instructions, and offline toggle.
  * *Audio Settings:* VAD sensitivity sliders, input device testing, audio buffer diagnostics.
  * *Diagnostics:* System permissions monitor, RAM footprint, and local model integrity.
* **`onboarding_window.py`:** First-run onboarding wizard guiding users through macOS Accessibility permissions (`AXIsProcessTrusted`), Microphone authorizations, Google AI Studio key setup, and hotkey calibration.
* **`tray.py`:** Native system menu bar (macOS) / system tray (Windows) integration providing quick access to Settings, Dictation History, Mute, Force Offline mode, and Exit.

### 3.3 Audio Pipeline (`just_talk/audio/`)
* **`recorder.py`:** Low-latency streaming audio input using `sounddevice` / PortAudio. Captures 16kHz mono 16-bit PCM audio in a ring buffer. Calculates real-time Root-Mean-Square (RMS) amplitude emitted at 60Hz for smooth HUD animation.
* **`vad.py` (`VoiceActivityDetector`):** Detects voice activity and automatically trims leading and trailing dead air. Rejects audio buffers that fall below minimum speech duration or energy thresholds to avoid unnecessary model inference.

### 3.4 Speech-to-Text Subsystem (`just_talk/stt/`)
* **`engine.py`:** Abstract base class establishing the contract for speech-to-text engines (`transcribe(audio: np.ndarray) -> str`).
* **`whisper_engine.py`:** High-efficiency local transcription powered by `faster-whisper` (CTranslate2).
  * Automatically detects and utilizes Apple Silicon Metal / MPS acceleration, NVIDIA CUDA on Windows, or multi-threaded CPU execution.
  * Employs INT8 and FP16 quantization for low memory footprint and sub-second execution on standard consumer laptops.
* **`model_manager.py`:** Multi-tier model catalog and downloader:
  * **Fast / Base (`base.en`):** ~140 MB, ~250ms latency. Optimized for older hardware and fast dictation.
  * **Balanced (`small.en`):** ~460 MB, ~400ms latency. Recommended default with outstanding technical accuracy.
  * **Quality / Multilingual (`large-v3-turbo`):** ~800 MB, ~650ms latency. Supports 99+ languages.

### 3.5 AI Formatting & Intent Routing (`just_talk/ai/`)
* **`gemini.py` (`GeminiFormatter`):** Integrates with Google AI Studio via `google-genai` / REST. Cleans raw speech into polished written prose without changing vocabulary or meaning:
  * Removes verbal tics ("um", "uh", "you know", "like").
  * Corrects punctuation, casing, technical terms, and homophones.
  * **Hardened System Prompt:** Strict guardrails prevent the LLM from outputting conversational filler (e.g., "Here is your cleaned text:") or refusing dictation.
  * **Circuit Breaker:** 2.0-second timeout circuit breaker immediately drops back to the raw local transcript if network conditions degrade.
* **`prompts.py`:** Structured system instructions tailored for dictation styles (Subtle Cleanup, Professional Email, Concise Bullets, Code & Technical).
* **`actions.py` (`ActionRouter`):** Action Mode handler triggered via `Fn + Shift`:
  * Detects spoken action prefixes (e.g., *"translate to French: ..."*, *"summarize this: ..."*, *"reply professionally: ..."*).
  * Routes prompt to Gemini with specialized transformation parameters before typing.

### 3.6 System Integration & Text Insertion (`just_talk/system/`)
* **`inserter.py` (`TextInserter`):**
  1. Inspects the frontmost application using macOS `NSWorkspace` / `CGWindowList` or Windows `GetForegroundWindow`.
  2. Backs up current clipboard data (text, HTML, images).
  3. Writes formatted text to the clipboard.
  4. Dispatches native simulated paste keyboard events:
     * **macOS:** Quartz `CGEventCreateKeyboardEvent` (`Cmd + V`).
     * **Windows:** Win32 `SendInput` (`Ctrl + V`).
  5. Waits 50ms for the target application to ingest the event, then asynchronously restores the user's previous clipboard contents.
  6. If no text-accepting application is frontmost, leaves the transcribed text on the clipboard and emits a gentle desktop notification.
* **`clipboard.py`:** Manages safe multi-format clipboard preservation and atomic restoration.
* **`permissions.py`:** Verifies and prompts for OS permissions:
  * macOS Accessibility API permissions (`AXIsProcessTrustedWithOptions`).
  * macOS Microphone access permissions (`AVCaptureDevice`).

### 3.7 Hardware Hotkeys & Key Event Interception (`just_talk/shortcuts/`)
* **`mac_hook.py`:** Native macOS event tap using CoreGraphics `CGEventTapCreate`:
  * Intercepts hardware `Fn` / Globe key events (`kCGEventFlagsSecondaryFn` / `NX_DEVICELCTLKEY`).
  * Solves the notorious macOS limitation where `Fn` cannot normally be bound as a global hold-to-talk key by generic user-space key loggers.
  * Operates without triggering system dictation or interfering with function key media controls.
* **`fallback_hook.py`:** Cross-platform fallback based on `pynput`:
  * Handles Windows global hotkeys (defaulting to **Right Alt**).
  * Allows customizable key combinations (e.g., `Ctrl + Space`, `Cmd + Shift + J`).
* **`manager.py` (`ShortcutManager`):** State coordinator managing push-to-talk vs. toggle modes, debouncing rapid key taps, and handling modifier flags.

### 3.8 Security & Persistence (`just_talk/security.py`, `just_talk/database/`)
* **`security.py` (`CredentialManager`):** Safely stores the Gemini API key in the operating system's hardware-backed credential store:
  * **macOS:** Native Keychain Services via `/usr/bin/security` with `-A` access control flags to eliminate annoying repeating password dialogs.
  * **Windows:** Windows Credential Vault via `keyring`.
* **`database/history.py` (`HistoryDatabase`):** Local SQLite storage:
  * Logs timestamp, target application, duration, raw transcript, cleaned text, and model tier used.
  * Automatic retention policy trims entries older than 30 days.
  * Completely offline and local; never synchronized to third-party clouds.

---

## 4. Concurrency & Threading Model

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        MAIN GUI THREAD (Qt Event Loop)                 │
│  - QApplication, MainWindow, Overlay, System Tray, Onboarding          │
│  - Receives Qt signals from AppBridge (thread-safe UI redraws)         │
└──────────────────┬─────────────────────────────────▲───────────────────┘
                   │ Starts / Stops                  │ Qt Signals
                   ▼                                 │
┌─────────────────────────────────────────┐ ┌────────┴───────────────────┐
│     BACKGROUND WORKER THREAD POOL       │ │     AUDIO STREAMING THREAD         │
│  - Faster-Whisper CTranslate2 STT       │ │  - sounddevice PortAudio Callback  │
│  - Gemini REST API HTTP calls           │ │  - Rolling 16kHz PCM ring buffer   │
│  - Native simulated paste events        │ │  - Computes RMS level at 60Hz      │
└─────────────────────────────────────────┘ └────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│       GLOBAL OS HOOK THREAD             │
│  - macOS: CoreGraphics CGEventTap       │
│  - Windows: pynput LowLevelHook         │
│  - Low latency, non-blocking key states │
└─────────────────────────────────────────┘
```

1. **GUI Responsiveness:** The main thread is strictly reserved for UI rendering and system events. No audio I/O, model loading, file writes, or HTTP calls occur on the GUI thread.
2. **Audio Stream Continuity:** Audio capture runs in high-priority native PortAudio callbacks, streaming chunks into an in-memory ring buffer.
3. **Async Inference & Timeout:** When the key is released, inference is scheduled on a dedicated background worker. The worker notifies `AppBridge`, which dispatches signals back to the main thread to animate the overlay pill.

---

## 5. Security & Privacy Guarantees

| Category | Implementation Detail | Guarantee |
| :--- | :--- | :--- |
| **Audio Privacy** | `faster-whisper` on CTranslate2 | Audio is never sent to the network. Completely local. |
| **Credential Storage** | macOS Keychain / Windows Credential Vault | API keys are encrypted at rest using OS hardware keystore. |
| **Network Traffic** | HTTPS requests to `generativelanguage.googleapis.com` | Only text transcripts (never audio). Can be disabled 100% via Offline Toggle. |
| **Clipboard Safety** | Backup -> Paste -> Restore pipeline | The user's clipboard is restored within 50ms of paste completion. |
| **Local Data** | Local SQLite (`~/.just_talk/history.db`) | History never leaves the machine. Auto-purged after 30 days. |

---

## 6. Build & Packaging Architecture

### 6.1 macOS
* Script: `packaging/mac/build_app.sh`
* Output: `dist/JustTalk.app` and `dist/JustTalk-macOS.dmg`
* Incorporates custom `.icns` multi-resolution icon bundle.
* Configures `Info.plist` with:
  * `NSMicrophoneUsageDescription`: Transparent permission rationale for audio capture.
  * `LSUIElement`: Configures app as an agent/menu bar accessory that doesn't clutter the macOS Dock unless the main window is opened.

### 6.2 Windows
* Zero-Install Launcher: `JustTalk-Launch-Windows.bat` (automatically bootstraps `uv` and launches the application).
* PyInstaller Specification: `packaging/justtalk.spec`.
* Windows Installer: `packaging/windows/installer.iss` (Inno Setup 6 compiler generating `JustTalk-Setup-1.0.0.exe`).
* AppUserModelID binding ensures taskbar pins retain the official multi-tier `.ico` asset.

### 6.3 CI/CD Automation
* Workflow: `.github/workflows/build.yml`
* Matrix builds for `macos-latest` and `windows-latest`.
* Automated test verification, asset generation, standalone binary compilation, and release artifact upload.
