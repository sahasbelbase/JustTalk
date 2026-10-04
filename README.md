# Just Talk 🎙️

> **A fast, quiet voice keyboard for macOS and Windows.**  
> Think → Speak → Done.

[![Tests](https://github.com/sahasbelbase/JustTalk/actions/workflows/build.yml/badge.svg)](https://github.com/sahasbelbase/JustTalk/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Releases](https://img.shields.io/github/v/release/sahasbelbase/JustTalk?color=blue&label=Latest%20Release)](https://github.com/sahasbelbase/JustTalk/releases/latest)

Just Talk is a lightweight desktop productivity utility that runs quietly in your system tray or menu bar. When you hold your push-to-talk trigger, it captures your speech, transcribes it locally using on-device Whisper neural models, subtly cleans the text using Gemini, and instantly inserts the result directly into whatever text field or application you are currently using (Chrome, VS Code, Slack, Notion, Discord, Terminal, etc.).

If no text field is actively focused, the final text is automatically placed on your clipboard and a subtle notification is shown.

---

## 📥 Direct Downloads & Installers

Download the latest version of Just Talk directly for your operating system:

| Operating System | Package Format | Direct Download Link | Release Page |
| :--- | :--- | :--- | :--- |
| **macOS** (Apple Silicon & Intel) | `.dmg` Disk Image | [⬇️ **Download JustTalk-macOS.dmg**](https://github.com/sahasbelbase/JustTalk/releases/latest/download/JustTalk-macOS.dmg) | [GitHub Releases](https://github.com/sahasbelbase/JustTalk/releases/latest) |
| **Windows** (Windows 10 / 11 64-bit) | `.exe` Setup Installer | [⬇️ **Download JustTalk-Windows.exe**](https://github.com/sahasbelbase/JustTalk/releases/latest/download/JustTalk-Windows.exe) | [GitHub Releases](https://github.com/sahasbelbase/JustTalk/releases/latest) |

> 💡 **Looking for all releases or release notes?** Visit the [Just Talk Releases Page](https://github.com/sahasbelbase/JustTalk/releases/latest).

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

### 🍏 macOS Installation & Setup
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

### 🪟 Windows Installation & Setup
For detailed, step-by-step instructions, see **[Windows Installation Guide](packaging/windows/INSTALL_WINDOWS.md)**.

1. **Download Pre-Built Installer**: Download [**JustTalk-Setup.exe**](https://github.com/sahasbelbase/JustTalk/releases/latest/download/JustTalk-Setup-1.0.0.exe) (or get it from [GitHub Releases](https://github.com/sahasbelbase/JustTalk/releases/latest)) and run the setup wizard.
   - Installs to `%LOCALAPPDATA%\Programs\Just Talk` with **no admin UAC prompt needed**.
   - Creates Start Menu, Desktop, and Windows Startup shortcuts.
   - Configures `AppUserModelID` for native Windows 10/11 taskbar pinning.
2. **Dedicated Uninstaller**:
   - Easily uninstall via Windows Settings -> *Installed apps* or double-click `uninstall.exe` in the application folder.

---

## 📦 Building Standalone Packages & Installers

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
* `dist\windows_installer\JustTalk-Setup-1.0.0.exe`: Modern setup installer with custom branding and standalone `uninstall.exe`.

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
MIT License. Free and open source. See [LICENSE.md](LICENSE.md) for full license details.
