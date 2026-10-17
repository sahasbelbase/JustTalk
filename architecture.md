# Just Talk — System Architecture & Technical Specifications (v5.0)

> **High-performance, privacy-first, on-device voice keyboard for macOS and Windows.**  
> Think → Speak → Done.

---

## 1. Executive Summary & Design Principles

**Just Talk** is a lightweight desktop productivity utility designed to provide sub-second voice-to-text dictation across any desktop application. Operating unobtrusively in the background via the system menu bar (macOS) or taskbar notification area (Windows), Just Talk captures audio upon a global push-to-talk key press, transcribes it on-device, enhances it via deterministic AI formatting (including on-device fine-tuned Qwen3-1.7B v5 GGUF), and inserts the result directly into the active text field.

### Core Architectural Principles:
1. **Zero Audio & Text Exfiltration (Privacy-First):** Raw speech audio is processed 100% locally on your machine using `faster-whisper` (CTranslate2). For maximum privacy, our custom fine-tuned on-device LLM (`justtalk-qwen3-1.7b-v5-Q4_K_M.gguf`, 1,107 MB) cleans up transcripts, transliterates loanwords, strips disfluencies, and generates action summaries fully offline using Apple Silicon Metal / MLX acceleration.
2. **Sub-Second Latency:** Streaming 16kHz audio buffer, voice activity detection (VAD), and hardware-accelerated local inference guarantee minimal latency between releasing the key and text insertion (<90ms on Apple Silicon).
3. **Deterministic & Resilient AI Formatting:** If cloud enhancement is chosen, plain-text transcripts can also route to external providers (Gemini, OpenAI, Claude, Grok, Groq, OpenRouter, DeepSeek, or local Ollama) with length-scaled time budgets and immediate local fallbacks.
4. **Non-Intrusive Desktop Integration:** True clipboard preservation restores prior clipboard contents after simulated paste; active window detection ensures text lands where the user expects or falls back safely to the system clipboard.
5. **Modern Native Aesthetics (Stitch Design System):** Adheres strictly to macOS dark utility aesthetics (`#0F1115` base, `#16181D` surface cards, `#1E2229` raised surfaces, `#2A2E37` borders, `#3B82F6` blue accent, and `#10B981` emerald status indicators), two-column sub-navigation settings, and side-by-side expandable diff history.

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
        Router -->|Normal Mode| Gemini[AI Formatter (multi-provider)<br/>Length-scaled time budget + local fallback]
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
* **Stitch macOS System Design Language:**
  * **Palette & Tokens (`theme.py`):** Precise dark utility palette (`#0F1115` base canvas, `#16181D` surface cards, `#1E2229` raised surfaces, `#2A2E37` borders, `#21252E` subtle borders, `#3B82F6` primary accent, `#10B981` emerald status indicators, and `#F9FAFB` high-contrast typography).
  * **Line Icons (`icons.py`):** Crisp Retina SVG monochrome line icons (`home`, `history`, `conventions`, `settings`, `keyboard`, `memory`, `sparkles`, `language`, `copy`, `delete`, `soundwave`, `neurology`, `terminal`, `volume`, `arrow-down`).
  * **Left Sidebar Navigation:** 188px fixed navigation rail with macOS traffic light spacing, brand header, active route states, and persistent hardware status capsule (`Ready · fn`).
  * **Home View (`home_view.py`):**
    * *Hero Greeting & Latency:* Time-of-day greeting with real-time engine latency indicator (`● Engine Latency: 14ms (Metal Accelerated)`).
    * *4-Metric Bento Grid:* Cards for *Words Spoken*, *Time Saved* (~3.5x typing calculation), *Current Streak*, and *Spoken Today* (WPM tracking).
    * *Activity Heatmap:* 52-week GitHub-style contribution matrix with 5 emerald intensity buckets, Month and Day labels (Mon, Wed, Fri), and interactive mouse-hover tooltips showing date, words, duration, and top application.
    * *Dictation Shortcut Hero Card:* Mechanical keycap `<kbd>fn</kbd>` visualizer, active global hook badge, and "Test Dictation" trigger.
    * *Live Dictation Sandbox ("Try It Here"):* Real-time practice testing playground with Live Buffer pill and copy button.
    * *Footer Bento Trio:* Live status tiles for *Speech Engine* (`memory`), *AI Formatting* (`sparkles`), and *Input Device* (`mic`).
  * **History View (`history_view.py`):**
    * *Collapsible Accordion Diffs:* Expandable side-by-side comparison panels featuring the raw unfiltered speech transcript on the left (`diffRawPanel`) and polished formatted output on the right (`diffFormattedPanel`).
    * Monospace timestamps, app badges, context chips, word counts, quick-copy, and deletion.
  * **Settings Sub-Navigation:**
    * Two-column macOS System Settings architecture: 212px fixed left category sub-nav rail with quick search filter, match counter, and 8 category destinations (`Shortcut & Triggers`, `Speech Model`, `Nepali & Kriti`, `Languages`, `Speaking Speed`, `Voice & Audio`, `AI Formatting`, `Application`).
    * Right scrollable content container with smooth section targeting and automated settings persistence.
  * **Writing Conventions View (`conventions_view.py`):**
    * Two-column syntax rule configuration panel with live before/after transformation preview.
    * Dynamic sample output reflecting keyword capitalization (`upper`/`lower`), naming styles (`PascalCase`/`snake_case`/`camelCase`), indentation width, schema prefixes, semicolons, and disfluency stripping.
    * Rule search filter and one-click clipboard copy with temporary feedback.
* **`wheel_guard.py`:** App-wide event filter ensuring mouse wheel scrolling over dropdowns and spin boxes scrolls the parent view instead of inadvertently altering values.

### 3.3 Audio Pipeline (`just_talk/audio/`)
* **`recorder.py`:** Low-latency streaming audio input using `sounddevice` / PortAudio. Captures 16kHz mono 16-bit PCM audio in a ring buffer. Calculates real-time Root-Mean-Square (RMS) amplitude emitted at 60Hz for smooth HUD animation.
* **`vad.py` (`VoiceActivityDetector`):** Detects voice activity and automatically trims leading and trailing dead air. Rejects audio buffers that fall below minimum speech duration or energy thresholds to avoid unnecessary model inference.

### 3.4 Speech-to-Text Subsystem (`just_talk/stt/`)
* **`engine.py`:** Abstract base class establishing the contract for speech-to-text engines (`transcribe(audio: np.ndarray) -> str`).
* **`mac_native_engine.py` (default on macOS):** Apple `SFSpeechRecognizer` (on-device when supported for the locale). Long audio is split at natural pauses (≤15 s chunks via `VoiceActivityDetector.split_on_pauses`) and each chunk's results are merged by `UtteranceTracker`, which keys every result by the audio span it covers. This handles Apple's behaviour of starting a fresh transcript after a pause, revising words, and re-sending finished utterances — without losing or duplicating text. Chunks that error or time out fall back to Google Web Speech (unless Pure Offline Mode).
* **`windows_native_engine.py` (default on Windows):** Google Web Speech first when online, local Whisper otherwise or in Pure Offline Mode.
* **`google_web_engine.py`:** Free Google Web Speech endpoint (sends audio to Google). Long audio is sent as pause-aligned chunks; a network failure mid-dictation returns nothing so callers fall back to an engine that can transcribe everything.
* **`long_form.py` (`IncrementalTranscriber`):** Live-preview helper — earlier speech is transcribed once and cached, only the recent tail is re-decoded, so the HUD always shows the whole dictation.
* **`whisper_engine.py`:** High-efficiency local transcription powered by `faster-whisper` (CTranslate2).
  * Automatically detects and utilizes Apple Silicon Metal / MPS acceleration, NVIDIA CUDA on Windows, or multi-threaded CPU execution.
  * Employs INT8 and FP16 quantization for low memory footprint and sub-second execution on standard consumer laptops.
* **`model_manager.py`:** Multi-tier model catalog and downloader:
  * **Fast / Base (`base.en`):** ~140 MB, ~250ms latency. Optimized for older hardware and fast dictation.
  * **Balanced (`small.en`):** ~460 MB, ~400ms latency. Recommended default with outstanding technical accuracy.
  * **Quality / Multilingual (`large-v3-turbo`):** ~800 MB, ~650ms latency. Supports 99+ languages.

### 3.5 AI Formatting & Intent Routing (`just_talk/ai/`)
* **v5 On-Device Local Model (`justtalk-qwen3-1.7b-v5-Q4_K_M.gguf`):**
  * Fine-tuned LoRA adapters merged into Qwen3-1.7B and exported to 4-bit Medium GGUF (1,107 MB).
  * Deployed locally in `Application Support/JustTalk/models/local-ai/`.
  * Specialized on Nepglish technical vocabulary, loanword preservation, disfluency stripping, and emotional storytelling without hallucination.
  * **Benchmark Scorecard (`results/eval_v5_17.txt`):**
    * Raw transcript cleanup: **73.2 chrF++** (<90ms on Apple Silicon Metal).
    * Held-out personal voice test: **58.7 chrF++** (<170ms).
    * FLORES+ Nepali-English translation: **39.3 chrF++** (<300ms).
* **`providers.py` (`MultiProviderFormatter`):** Unified interface for local and cloud providers (Local v5 GGUF, Gemini, OpenAI, Anthropic, Grok, Groq, OpenRouter, DeepSeek, custom OpenAI-compatible endpoints, Ollama):
  * **Time budget:** `_time_budget()` allocates ~2 s for short phrases and scales up to ~8 s for extended dictation; two-phase insertion ensures immediate draft display so users experience zero friction.
  * **Circuit breaker:** API and network errors count towards temporary suspension (3 consecutive failures → 5 minute cooldown).
  * **Hardened prompt wrapper:** Transcripts are demarcated as pure content, ensuring models never interpret user speech as meta-instructions.
* **`prompts.py`:** Domain-specific prompt templates enforcing subtle grammatical correction, filler word elimination, punctuation synthesis, and technical casing preservation.
* **`actions.py` (`ActionRouter`):** Action Mode handler triggered via `Fn + Shift`:
  * Detects spoken transformations (*"summarize in bullet points: ..."*, *"write me a sick leave email"*, *"rewrite professionally: ..."*).
  * Formats dynamic responses directly into the active cursor position.

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
* **`security.py` (`CredentialManager`):** Stores provider API keys and the custom base URL in a private `.credentials` JSON file inside the app-data folder (`~/Library/Application Support/JustTalk` on macOS, `%APPDATA%\JustTalk` on Windows) with owner-only `0600` permissions. Environment variables (`GEMINI_API_KEY`, etc.) take precedence. Legacy keychain entries are purged silently.
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
   * **Worker → UI callbacks** must go through `ui_thread.run_on_ui_thread(fn)` (a queued Qt signal on a GUI-thread `QObject`). `QTimer.singleShot(0, fn)` from a plain `threading.Thread` silently never fires, because that thread has no Qt event loop.
2. **Audio Stream Continuity:** Audio capture runs in high-priority native PortAudio callbacks, streaming chunks into an in-memory ring buffer.
3. **Async Inference & Timeout:** When the key is released, inference is scheduled on a dedicated background worker. The worker notifies `AppBridge`, which dispatches signals back to the main thread to animate the overlay pill.

---

## 5. Security & Privacy Guarantees

| Category | Implementation Detail | Guarantee |
| :--- | :--- | :--- |
| **Audio Privacy** | Engine-dependent | Pure Offline Mode / Whisper: audio never leaves the machine. Apple built-in: on-device where supported. Google Web Speech (Nepali; Windows online default): audio is sent to Google. |
| **Credential Storage** | Private `.credentials` file, `0600` permissions | Keys stay on the device and are sent only to the selected provider. |
| **Network Traffic** | HTTPS to the selected AI provider | AI formatting sends text only (never audio). Pure Offline Mode disables all network requests. |
| **Clipboard Safety** | Backup -> Paste -> Restore pipeline | The user's clipboard is restored after the paste is consumed. Tests use an in-memory clipboard and never send real keystrokes. |
| **Local Data** | Local SQLite (`history.db` in the app-data folder) | History never leaves the machine. Retention is configurable (default 30 days). |

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
* **`.github/workflows/build.yml`:** on pushes to `main`, pull requests and `v*` tags — runs the test suite and builds the macOS `.dmg` (macos-14) and Windows Inno Setup `.exe` (windows-latest). On a `v*` tag, a release job publishes both installers plus `SHA256SUMS.txt` to GitHub Releases, which is what the in-app updater reads.
* **`.github/workflows/pages.yml`:** on changes to `website/`, deploys the site to the `gh-pages` branch (GitHub Pages).
