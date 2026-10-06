# Just Talk (v2.1.0)

> **A fast, quiet voice keyboard for macOS and Windows.**  
> Think → Speak → Done.

[![Tests](https://github.com/sahasbelbase/JustTalk/actions/workflows/build.yml/badge.svg)](https://github.com/sahasbelbase/JustTalk/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Releases](https://img.shields.io/github/v/release/sahasbelbase/JustTalk?color=blue&label=Latest%20Release)](https://github.com/sahasbelbase/JustTalk/releases/latest)

Just Talk is a lightweight desktop productivity utility that runs quietly in your system tray or menu bar. Tap your hotkey, speak naturally, and your words appear directly in whatever application you are using (Chrome, VS Code, Slack, Notion, Discord, Terminal, etc.)—complete with instant draft streaming and optional AI-powered grammar polishing.

If no text field is actively focused, the final text is automatically placed on your clipboard and a subtle notification is shown.

---

## Downloads

Download the latest version of Just Talk directly for your operating system:

| Operating System | Package Format | Direct Download Link | Release Page |
| :--- | :--- | :--- | :--- |
| **macOS** (Apple Silicon & Intel) | `.dmg` Disk Image | [**Download JustTalk-macOS.dmg**](https://github.com/sahasbelbase/JustTalk/releases/latest/download/JustTalk-macOS.dmg) | [GitHub Releases](https://github.com/sahasbelbase/JustTalk/releases/latest) |
| **Windows** (Windows 10 / 11 64-bit) | `.exe` Setup Installer | [**Download JustTalk-Windows.exe**](https://github.com/sahasbelbase/JustTalk/releases/latest/download/JustTalk-Windows.exe) | [GitHub Releases](https://github.com/sahasbelbase/JustTalk/releases/latest) |

> **Looking for all releases or release notes?** Visit the [Just Talk Releases Page](https://github.com/sahasbelbase/JustTalk/releases/latest).

---

## What's New in Version 2.1.0

* **Long dictation that keeps everything:** Speak for up to 5 minutes with pauses. Long audio is split at natural pauses and stitched back together, so nothing said before a pause is lost or repeated. In tap mode, recording stops after 8 seconds of silence (was 4.5 s).
* **Smarter AI cleanup:** Self-corrections are resolved ("meet at five, actually four" → "Can we meet at four?"), grammar and spelling are fixed Grammarly-style, and long dictations get more time instead of falling back to "inserted offline". Slow replies no longer pause AI formatting for everyone.
* **Premium, emoji-free interface:** A single set of line icons, plain section titles, a compact settings page that saves automatically, readable activity chart labels, and correct dark-mode colours.
* **Reliable background updates:** "Check for updates", model downloads, mic test and AI connection tests now report back to the window (previously some never finished).
* **Windows fixes:** Dictation now pastes into Chrome, VS Code, Slack, Office and other apps instead of only copying, and scrolling over a dropdown scrolls the page instead of changing the value.
* **Clean quit:** Cmd+Q, tray Quit, logout and shutdown all close Just Talk properly.

## Previous Release: 2.0.1

* **Zero-Login, Instant Speech Engines:** No mandatory Hugging Face downloads or initial freezes. Uses macOS `SFSpeechRecognizer` or Windows Speech Recognition out-of-the-box, with seamless fallback to the free, zero-key Google Web Speech API.
* **Tap-to-Toggle Dictation:** Tap **Fn** (macOS) or **Right Alt** (Windows) once to start recording, tap again to finish. Built-in 250ms hardware debounce and repeat suppression prevent accidental double-toggles.
* **Seamless Two-Phase Text Insertion:** Initial draft text appears in your active text editor in ~200ms as you speak. When speech stops, Just Talk polishes grammar and formatting in-place.
* **Automatic Background Audio Ducking:** Mutes background music, video streams, or reels playing on your computer while dictating so they never bleed into your microphone.
* **Safety Nets:** A long pause after speaking after speaking automatically commits your transcript. Pressing `Escape` at any time instantly cancels recording and discards drafts.
* **Writing Conventions Panel:** Configure specialized dictation formatting for SQL, Python, JavaScript, TypeScript, C#, Rust, PHP, or Plain Prose with live before/after previews.
* **Contribution Activity Dashboard:** GitHub-style activity graph visualizing daily words spoken, time saved, and dictation streaks.
* **Multilingual & Code-Switching:** Fluent transcription and translation for English, Nepali (`ne-NP`), and mixed Nepali-English speech.

---

## Key Highlights

* **Tap or Push-to-Talk:** Tap **Fn** (macOS) or **Right Alt** (Windows) to toggle, or switch to classic hold-to-talk in Settings.
* **Instant Text Insertion:** Your words are cleaned and typed into your focused app in milliseconds.
* **Native macOS Aesthetic:** Frosted glass acrylic styling, dynamic dark/light mode, custom typography (`Inter`, `Lato`, `JetBrains Mono`), and fluid status animations.
* **Floating Animated HUD:** Minimalist floating pill overlay displays dynamic live audio waveforms while speaking, pulsing state while processing, and a subtle emerald badge on successful insertion.
* **Universal Compatibility:** Works seamlessly across web browsers, Electron apps, native editors, and terminals.
* **Clipboard Preservation:** Your previous clipboard contents are restored automatically after Just Talk pastes.
* **Single-Instance Lock:** Robust IPC lock prevents duplicate background instances from competing for audio devices or global hotkeys.
* **Action Mode (Fn + Shift):**
  * Say *"translate this into Spanish: Let's meet tomorrow at 10 AM"* → types Spanish translation.
  * Say *"rewrite this professionally: Need those reports ASAP"* → types polished business prose.
  * Say *"summarize this in bullet points: ... "* → types a concise summary.

---

## Privacy & Offline Mode

1. **Your choice of speech engine:** With **Pure Offline Mode** or local Whisper, audio never leaves your computer. The built-in macOS engine uses Apple's on-device recognition where your Mac supports it. The Google Web Speech engine (used for Nepali, and first on Windows when online) sends audio to Google to transcribe it.
2. **Text-only AI formatting:** Only the transcribed text — never audio — is sent to the AI provider you choose (or to Ollama running locally) for punctuation, grammar and cleanup.
3. **Graceful fallback:** If the AI provider is slow or unreachable, the locally cleaned transcript is inserted instead. Short phrases wait at most ~2 s; long dictations get up to ~8 s. Only real outages (not slow replies) pause AI formatting.
4. **Pure Offline Mode:** One toggle disables every network request — on-device transcription only, and cloud AI formatting is switched off.
5. **Local credential storage:** API keys are stored only on your computer, in a private `.credentials` file in Just Talk's app-data folder with owner-only (0600) permissions, and are sent only to the provider you selected.

---

## Bring Your Own Model (BYOM)

Just Talk gives you absolute freedom to choose both your **Speech Recognition Engine** and your **AI Formatting Model**:

### 1. Speech-to-Text (STT) Engines
* **OS-Native Dictation (Default):** Zero latency, zero setup on Apple Silicon / macOS and Windows.
* **Google Web Speech (Cloud Fallback):** 100% free, zero login, zero API keys required. Excellent for multilingual and low-resource languages.
* **Local Whisper / BYOM:** Choose standard Whisper models (`base.en`, `small.en`, `large-v3-turbo`) or point to any custom Hugging Face repo or local CTranslate2 folder.

### 2. Local Offline AI Formatting with Ollama (100% On-Device)
Run powerful open-weight LLMs locally with **zero API keys, zero cloud costs, and 100% offline privacy**:
* **Supported Models**: `llama3.2:3b`, `qwen2.5-coder:7b`, `mistral:7b`, `deepseek-r1:8b`, etc.
* **Auto-Scanner**: Detects all models installed in your local Ollama instance (`http://localhost:11434`) automatically.
* **Smart Preamble Sanitization**: Strips conversational fluff (`"Here is the text:"`) so your cursor receives pure, formatted text at 160 wpm.
* **Multi-Provider Cloud LLMs**: Also supports Google Gemini, OpenAI, Claude, xAI Grok, Groq, OpenRouter, and custom OpenAI-compatible endpoints.

---

## Model Tiers

Choose the speed and accuracy profile that matches your hardware:

| Tier | Engine / Model | Weight Size | RAM Usage | Latency (5s speech) | Best For |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **OS Native (Default)** | Apple / Windows Dictation | Built-in | System | <100ms | Zero setup, instant response |
| **Google Web Speech** | Free Cloud Endpoint | 0 MB | ~50 MB | ~200ms | Multilingual, Nepali, zero login |
| **Fast / Small** | `base.en` (Whisper) | ~140 MB | ~200 MB | ~250ms | Ultra-fast offline response |
| **Balanced** | `small.en` (Whisper) | ~460 MB | ~450 MB | ~400ms | High accuracy & technical terms |
| **High Quality / Multilingual** | `large-v3-turbo` (Whisper) | ~800 MB | ~850 MB | ~650ms | Dictation across 99+ languages |

---

## Quickstart (Running from Source)

### Prerequisites
* macOS 12+ (Apple Silicon or Intel) or Windows 10/11 (64-bit)
* Python 3.11+
* [uv](https://github.com/astral-sh/uv) (recommended package manager)

### macOS Installation & Setup
For detailed, step-by-step instructions, see **[macOS Installation Guide](packaging/mac/INSTALL_MAC.md)**.

1. **Download Pre-Built DMG**: Download [**JustTalk-macOS.dmg**](https://github.com/sahasbelbase/JustTalk/releases/latest/download/JustTalk-macOS.dmg) (or get it from [GitHub Releases](https://github.com/sahasbelbase/JustTalk/releases/latest)).
2. **Install**: Double-click the DMG and drag `Just Talk` into `/Applications`.
3. **Clear Quarantine (if prompted by Gatekeeper)**:
   ```bash
   xattr -cr /Applications/JustTalk.app
   ```
4. **Grant Permissions** (*System Settings > Privacy & Security*):
   - **Microphone**: Enabled for voice recording.
   - **Accessibility**: Enabled for global hotkey and text caret insertion.
5. **Xcode Developer Tools (if building from source)**:
   ```bash
   xcode-select --install
   ./packaging/mac/setup_mac.sh
   ```

### Windows Installation & Setup
For detailed, step-by-step instructions, see **[Windows Installation Guide](packaging/windows/INSTALL_WINDOWS.md)**.

1. **Download Pre-Built Installer**: Download [**JustTalk-Windows.exe**](https://github.com/sahasbelbase/JustTalk/releases/latest/download/JustTalk-Windows.exe) (or get it from [GitHub Releases](https://github.com/sahasbelbase/JustTalk/releases/latest)) and run the setup wizard.
   - Installs to `%LOCALAPPDATA%\Programs\Just Talk` with **no admin UAC prompt needed**.
   - Creates Start Menu, Desktop, and Windows Startup shortcuts.
   - Configures `AppUserModelID` for native Windows 10/11 taskbar pinning.
2. **Dedicated Uninstaller**:
   - Easily uninstall via Windows Settings -> *Installed apps* or double-click `uninstall.exe` in the application folder.

---

## Building Standalone Packages & Installers

### macOS (`.app` Bundle & `.dmg` Installer)
To compile and package the standalone macOS app:
```bash
chmod +x packaging/mac/build_app.sh
./packaging/mac/build_app.sh
```
This produces:
* `dist/JustTalk.app`: Signed standalone macOS application bundle.
* `dist/JustTalk-macOS.dmg` & `packaging/mac/JustTalk-macOS.dmg`: Drag-and-drop installer disk image.

---

### Windows (`.exe` Binary & Inno Setup / NSIS Installers)
To compile and package the standalone Windows executable and setup installer:
```powershell
# Automated PowerShell build script:
powershell -ExecutionPolicy Bypass -File packaging\windows\build_exe.ps1

# Or via Command Prompt:
packaging\windows\build_exe.bat
```
This produces:
* `dist\JustTalk\JustTalk.exe`: Standalone portable application.
* `dist\windows_installer\JustTalk-Windows.exe`: Inno Setup installer with custom branding and an uninstaller.

---

## Running the Test Suite

Just Talk includes comprehensive test coverage for configuration, SQLite history, Voice Activity Detection (VAD), action routing, Gemini offline fallbacks, single-instance enforcement, and native speech engines:

```bash
# Run all unit tests
uv run pytest -v
```

---

## Codebase Architecture

For in-depth architectural diagrams, thread models, and subsystem specifications, see **[architecture.md](architecture.md)**.

```text
JustTalk/
├── main.py                     # Root execution script
├── pyproject.toml              # Project dependencies and script entrypoints
├── architecture.md             # Comprehensive technical & architectural specifications
├── QA_CHECKLIST.md             # Quality assurance and release verification checklist
│
├── just_talk/
│   ├── config.py               # Dataclass & persistent JSON application configuration
│   ├── security.py             # Private 0600 credentials file for API keys
│   │
│   ├── app/
│   │   ├── main.py             # Application entrypoint, AppBridge signals, AUMID registration
│   │   ├── single_instance.py  # IPC socket / mutex single-instance enforcer
│   │   ├── theme.py            # macOS-inspired design tokens, typography, dark/light styles
│   │   ├── overlay.py          # Floating animated status pill HUD (waveform, pulse, badges)
│   │   ├── main_window.py      # Unified Control Center (Home, History, Settings, Conventions)
│   │   ├── home_view.py        # Dashboard with GitHub-style contribution graph
│   │   ├── history_view.py     # Searchable dictation history with one-click re-copy
│   │   ├── conventions_view.py # Code and SQL writing conventions manager
│   │   ├── onboarding_window.py# First-run onboarding & permissions setup wizard
│   │   ├── ai_formatting_view.py# AI provider, API key, model and formatting sandbox
│   │   ├── icons.py            # Monochrome SVG line icons (no emoji in the UI)
│   │   ├── ui_thread.py        # run_on_ui_thread(): safe worker-thread → Qt UI callbacks
│   │   └── wheel_guard.py      # Stops the mouse wheel changing dropdowns while scrolling
│   │   └── tray.py             # Native system tray / menu bar integration
│   │
│   ├── audio/
│   │   ├── recorder.py         # 16kHz low-latency streaming microphone buffer (sounddevice)
│   │   └── vad.py              # Voice activity detection, silence trimming, pause-aligned chunking
│   │
│   ├── stt/
│   │   ├── engine.py           # Speech-to-text abstract base class
│   │   ├── mac_native_engine.py# SFSpeechRecognizer macOS native dictation engine
│   │   ├── windows_native_engine.py # Windows Media Speech Recognition engine
│   │   ├── google_web_engine.py# Zero-login, zero-key Google Web Speech API engine
│   │   ├── whisper_engine.py   # faster-whisper (CTranslate2) local inference engine
│   │   ├── long_form.py        # Live-partial caching so long dictation keeps earlier speech
│   │   └── model_manager.py    # Multi-tier model catalog and downloader
│   │
│   ├── ai/
│   │   ├── gemini.py           # Gemini client, local cleanup and circuit breaker
│   │   ├── prompts.py          # Deterministic system prompts (Subtle, Formal, Concise, Code)
│   │   ├── actions.py          # Speech intent router for Action Mode (Fn + Shift)
│   │   └── providers.py        # Multi-provider LLM coordinator (Gemini, Ollama, Claude, OpenAI)
│   │
│   ├── system/
│   │   ├── audio_ducker.py     # Background audio mute/ducking during speech
│   │   ├── inserter.py         # Two-phase simulated text insertion & clipboard restoration
│   │   ├── clipboard.py        # Multi-format clipboard backup & atomic restoration
│   │   ├── context_detector.py # Active editor/application context detector
│   │   └── permissions.py      # macOS Accessibility & Microphone permission checker
│   │
│   ├── shortcuts/
│   │   ├── manager.py          # Tap-to-toggle & push-to-talk state coordinator
│   │   ├── mac_hook.py         # Native macOS CGEventTap Function (Fn/Globe) key monitor
│   │   └── fallback_hook.py    # Cross-platform hotkey listener (pynput)
│   │
│   ├── database/
│   │   └── history.py          # Local SQLite storage with automatic 30-day retention purge
│   │
│   └── assets/
│       ├── icon.png            # High-res 512x512 logo
│       ├── icon.ico            # Windows multi-resolution icon (16 to 256px)
│       ├── icon.icns           # Native Apple macOS icon bundle
│       └── fonts/              # Custom typography (Inter, Lato, JetBrains Mono)
│
├── packaging/
│   ├── mac/                    # Info.plist & build_app.sh
│   ├── windows/                # installer.iss (Inno Setup 6) & build_exe.ps1
│   └── justtalk.spec           # PyInstaller build specification
│
├── .github/workflows/
│   ├── build.yml               # Tests + macOS .dmg & Windows .exe builds; publishes releases on v* tags
│   └── pages.yml               # Deploys website/ to GitHub Pages
│
└── tests/                      # Unit and integration test suite
```

---

## License
MIT License. Free and open source. See [LICENSE.md](LICENSE.md) for full license details.
