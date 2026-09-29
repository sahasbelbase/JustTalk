# Just Talk 🎙️

> **A fast, quiet voice keyboard for macOS and Windows.**  
> Think → Speak → Done.

[![Tests](https://github.com/sahas/JustTalk/actions/workflows/build.yml/badge.svg)](https://github.com/sahas/JustTalk/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

Just Talk is a lightweight desktop productivity utility that runs quietly in your system tray or menu bar. When you hold your push-to-talk trigger, it captures your speech, transcribes it locally using on-device Whisper neural models, subtly cleans the text using Gemini, and instantly inserts the result directly into whatever text field or application you are currently using (Chrome, VS Code, Slack, Notion, Discord, Terminal, etc.).

If no text field is actively focused, the final text is automatically placed on your clipboard and a subtle notification is shown.

---

## ⚡ Key Highlights & Experience

* **Push-to-Talk:** Hold **Fn** (macOS) or **Right Alt** (Windows) → speak naturally → release key.
* **Instant Text Insertion:** Your words are cleaned and typed into your focused app in milliseconds.
* **Native macOS Aesthetic:** Frosted glass acrylic styling, dynamic dark/light mode, custom typography (`Inter`, `Lato`, `JetBrains Mono`, `Instrument Serif`), and fluid status animations.
* **Floating Animated HUD:** Minimalist floating pill overlay displays dynamic live audio waveforms while speaking, pulsing state while processing, and a subtle emerald badge on successful insertion.
* **Dual-Mode Main Window:** macOS split-view preferences with quick sidebar navigation across Dictation & Status, History, AI Formatting, Audio Settings, and Diagnostics.
* **Universal Compatibility:** Works seamlessly across web browsers, Electron apps, native editors, and terminals.
* **Clipboard Preservation:** Your prior clipboard contents (text, rich text, images) are seamlessly restored 50ms after paste.
* **Single-Instance Lock:** Robust IPC lock prevents duplicate background instances from competing for audio devices or global hotkeys.
* **Action Mode (Fn + Shift):**
  * Say *"translate this into Spanish: Let's meet tomorrow at 10 AM"* → types Spanish translation.
  * Say *"rewrite this professionally: Need those reports ASAP"* → types polished business prose.
  * Say *"summarize this in bullet points: ... "* → types a concise summary.

---

## 🔒 Privacy & Offline First

1. **Local Speech-to-Text:** Raw audio never leaves your machine. Inference is performed locally using `faster-whisper` (CTranslate2).
2. **Deterministic Text Formatting:** Only the transcribed text string is sent to the Gemini API (via Google AI Studio) for subtle punctuation, capitalization, and filler word removal.
3. **Strict 2.0s Circuit Breaker:** If offline or if network latency exceeds 2.0 seconds, the system instantly inserts the raw local transcription with zero delay.
4. **Pure Offline Mode:** A single toggle disables cloud requests entirely, using 100% on-device local transcription.
5. **Secure Credential Storage:** API keys are never stored in plain text; they are secured using the operating system's native keychain (macOS Keychain with automatic access control and Windows Credential Vault).

---

## 🧠 Model Tiers

Choose the speed and accuracy profile that matches your hardware:

| Tier | Model | Weight Size | RAM Usage | Latency (5s speech) | Best For |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Fast / Small** | `base.en` | ~140 MB | ~200 MB | ~250ms | Ultra-fast response on older laptops |
| **Balanced (Recommended)** | `small.en` | ~460 MB | ~450 MB | ~400ms | Exceptional technical accuracy & punctuation |
| **High Quality / Multilingual** | `large-v3-turbo`| ~800 MB | ~850 MB | ~650ms | Multilingual dictation across 99+ languages |

---

## 🚀 Quickstart (Running from Source)

### Prerequisites
* macOS 12+ (Apple Silicon or Intel) or Windows 10/11 (64-bit)
* Python 3.11+
* [uv](https://github.com/astral-sh/uv) (recommended package manager)

### macOS Setup

```bash
# Clone the repository
git clone https://github.com/sahas/JustTalk.git
cd JustTalk

# Run the desktop application
uv run python main.py
```

### Windows Setup

You can launch Just Talk instantly with zero manual installation by running the one-click launcher:
```cmd
# Double-click or run from command prompt
JustTalk-Launch-Windows.bat
```
*(The launcher automatically bootstraps `uv` and dependencies if not already present).*

Alternatively, run via standard command line:
```cmd
uv run python main.py
```

### Initial Configuration
1. Click the **Just Talk** icon in your macOS menu bar or Windows taskbar.
2. Select **Open Just Talk** or **Settings...**
3. Navigate to **AI Formatting** and paste your free Google AI Studio API key.
4. Test the connection and customize your formatting preset.

---

## 📦 Building Standalone Packages & Installers

### macOS (`.app` Bundle & `.dmg` Installer)
To build a standalone macOS application that includes custom icons and Info.plist permissions:

```bash
./packaging/mac/build_app.sh
```

This creates:
* `dist/JustTalk.app`: Double-clickable standalone macOS application.
* `dist/JustTalk-macOS.dmg`: Drag-and-drop installer disk image.

#### macOS Permissions Required:
* **Microphone Access:** Prompted on first voice trigger (`NSMicrophoneUsageDescription`).
* **Accessibility Access:** Required for global hotkeys and frontmost window detection (*System Settings > Privacy & Security > Accessibility*).

---

### Windows (`.exe` Binary & Inno Setup Installer)
On Windows, Just Talk explicitly sets its `AppUserModelID` (`justtalk.desktop.voiceinput.1.0`) on launch. When pinned to the taskbar, Windows permanently binds to the application and displays the custom multi-resolution microphone icon, completely preventing the common bug where pinned Python utilities revert to the generic Python snake logo.

To compile:
```cmd
# 1. Compile standalone binary with PyInstaller
uv run pyinstaller --clean -y packaging\justtalk.spec

# 2. Build Inno Setup Installer
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\installer.iss
```

This generates `dist\windows_installer\JustTalk-Setup-1.0.0.exe`.

---

## 🧪 Running the Test Suite

Just Talk includes comprehensive test coverage for configuration, SQLite history, Voice Activity Detection (VAD), action routing, Gemini offline fallbacks, single-instance enforcement, and real on-device Whisper inference:

```bash
# Run all unit tests
uv run pytest -v

# Run the real on-device Whisper neural inference test
uv run pytest tests/test_live_whisper.py -v -s
```

---

## 📁 Codebase Architecture

For in-depth architectural diagrams, thread models, and subsystem specifications, see **[architecture.md](architecture.md)**.

```text
JustTalk/
├── main.py                     # Root execution script
├── pyproject.toml              # Project dependencies and script entrypoints
├── architecture.md             # Comprehensive technical & architectural specifications
├── QA_CHECKLIST.md             # Quality assurance and release verification checklist
├── JustTalk-Launch-Windows.bat # Zero-install one-click launcher for Windows
│
├── just_talk/
│   ├── config.py               # Dataclass & persistent JSON application configuration
│   ├── security.py             # OS Keychain & Windows Credential Vault credential manager
│   │
│   ├── app/
│   │   ├── main.py             # Application entrypoint, AppBridge signals, AUMID registration
│   │   ├── single_instance.py  # IPC socket / mutex single-instance enforcer
│   │   ├── theme.py            # macOS-inspired design tokens, typography, dark/light styles
│   │   ├── overlay.py          # Floating animated status pill HUD (waveform, pulse, badges)
│   │   ├── main_window.py      # Unified Control Center (Home, History, Settings, Models, AI Prompts)
│   │   ├── onboarding_window.py# First-run onboarding & permissions setup wizard
│   │   ├── ai_formatting_view.py# AI prompt tuning, temperature, and formatting controls
│   │   └── tray.py             # Native system tray / menu bar integration
│   │
│   ├── audio/
│   │   ├── recorder.py         # 16kHz low-latency streaming microphone buffer (sounddevice)
│   │   └── vad.py              # Voice Activity Detector & dead-air silence trimmer
│   │
│   ├── stt/
│   │   ├── engine.py           # Speech-to-text abstract base class
│   │   ├── whisper_engine.py   # faster-whisper (CTranslate2) local inference engine
│   │   └── model_manager.py    # Multi-tier model catalog and downloader
│   │
│   ├── ai/
│   │   ├── gemini.py           # Google AI Studio client with 2.0s circuit breaker fallback
│   │   ├── prompts.py          # Deterministic system prompts (Subtle, Formal, Concise, Code)
│   │   └── actions.py          # Speech intent router for Action Mode (Fn + Shift)
│   │
│   ├── system/
│   │   ├── inserter.py         # Native simulated paste (Cmd+V / Ctrl+V) & active app detector
│   │   ├── clipboard.py        # Multi-format clipboard backup & atomic restoration
│   │   └── permissions.py      # macOS Accessibility & Microphone permission checker
│   │
│   ├── shortcuts/
│   │   ├── manager.py          # Push-to-talk & toggle hotkey state coordinator
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
│       └── fonts/              # Custom typography (Inter, Lato, JetBrains Mono, Instrument Serif)
│
├── packaging/
│   ├── mac/                    # Info.plist & build_app.sh
│   ├── windows/                # installer.iss (Inno Setup 6)
│   └── justtalk.spec           # PyInstaller build specification
│
├── .github/workflows/
│   └── build.yml               # Automated cross-platform CI/CD matrix (macOS & Windows)
│
└── tests/                      # Unit and integration test suite
```

---

## ⚖️ License
MIT License. Free and open source.
