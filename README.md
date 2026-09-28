# Just Talk 🎙️
> **A fast, quiet voice keyboard for macOS and Windows.**  
> Think → Speak → Done.

Just Talk is a lightweight desktop productivity utility that runs in your system tray / menu bar. When you hold your push-to-talk trigger, it captures your speech, transcribes it locally using on-device Whisper neural models, subtly cleans the text using Gemini, and instantly inserts the result directly into whatever text field or application you are currently using (Chrome, VS Code, Slack, Notion, Discord, Terminal, etc.).

If no text field is actively focused, the final text is automatically placed on your clipboard and a subtle notification is shown.

---

## ⚡ The Experience

* **Push-to-Talk:** Hold **Fn** (macOS) or **Right Alt** (Windows) → speak naturally → release key.
* **Instant Text Insertion:** Your words are cleaned and typed into your focused app in milliseconds.
* **Universal Compatibility:** Works across web browsers, electron apps, native editors, and terminals.
* **Clipboard Preservation:** Your prior clipboard contents are seamlessly restored after paste.
* **Action Mode (Fn + Shift):**
  * Say *"translate this into Spanish: Let's meet tomorrow at 10 AM"* → types Spanish translation.
  * Say *"rewrite this professionally: Need those reports ASAP"* → types polished business prose.
  * Say *"summarize this: ... "* → types a concise summary.

---

## 🔒 Privacy & Offline First

1. **Local Speech-to-Text:** Raw audio never leaves your machine. Inference is performed locally using `whisper.cpp` / `faster-whisper`.
2. **Deterministic Text Formatting:** Only the transcribed text string is sent to the Gemini API (via Google AI Studio) for subtle punctuation and filler word removal.
3. **Pure Offline Mode:** A single toggle disables cloud requests entirely, inserting the raw local transcription with zero network calls.
4. **Secure Credential Storage:** API keys are never stored in plain text; they are secured using the operating system's native keychain (macOS Keychain and Windows Credential Vault).

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
* [uv](https://github.com/astral-sh/uv) (recommended)

### 1. Clone & Run
```bash
cd /Users/sahas/Documents/Projects/JustTalk

# Run the desktop application
uv run python main.py
```

### 2. Configure Your Gemini API Key
1. Click the **Just Talk** tray icon in your menu bar / taskbar.
2. Select **Settings...** → Navigate to the **Gemini** tab.
3. Paste your free Google AI Studio API key and click **Test Connection**.
4. Click **Save Preferences**.

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

#### macOS Permissions:
* **Microphone Access:** Prompted on first voice trigger (`NSMicrophoneUsageDescription`).
* **Accessibility Access:** Required for global hotkeys and frontmost window detection (*System Settings > Privacy & Security > Accessibility*).

---

### Windows (`.exe` Binary & Inno Setup Installer)
On Windows, Just Talk explicitly sets its `AppUserModelID` (`justtalk.desktop.voiceinput.1.0`) on launch. When pinned to the taskbar, Windows permanently binds to the application and displays the custom multi-resolution microphone icon, completely preventing the common bug where pinned Python utilities revert to the generic Python snake logo.

To compile:
```cmd
# 1. Compile binary
uv run pyinstaller --clean -y packaging\justtalk.spec

# 2. Build Inno Setup Installer
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\installer.iss
```

This generates `dist\windows_installer\JustTalk-Setup-1.0.0.exe`.

---

## 🧪 Running the Test Suite

Just Talk includes comprehensive test coverage for configuration, SQLite history, Voice Activity Detection (VAD), action routing, Gemini offline fallbacks, and real on-device Whisper inference:

```bash
# Run all unit tests
uv run pytest -v

# Run the real on-device Whisper neural inference test
uv run pytest tests/test_live_whisper.py -v -s
```

---

## 📁 Project Architecture

```text
JustTalk/
├── app/
│   ├── main.py              # Central application coordinator & Windows AUMID registration
│   ├── overlay.py           # Subtle floating status pill (Listening, Processing, Inserted)
│   ├── tray.py              # Native system tray icon & menu
│   ├── settings_window.py   # Minimalist preferences dialog & device test
│   └── history_window.py    # Searchable local dictation history viewer
│
├── audio/
│   ├── recorder.py          # 16kHz low-latency streaming microphone buffer
│   └── vad.py               # Voice Activity Detector & silence trimmer
│
├── stt/
│   ├── engine.py            # STT abstract interface
│   ├── whisper_engine.py    # faster-whisper (CTranslate2) local inference engine
│   └── model_manager.py     # Multi-tier model catalogue & downloader
│
├── ai/
│   ├── gemini.py            # Google AI Studio Gemini API client with 2.0s fallback
│   ├── prompts.py           # Deterministic system prompts (Subtle, Formal, Concise, Translate)
│   └── actions.py           # Speech intent router for Action Mode (Fn + Shift)
│
├── system/
│   ├── inserter.py          # Simulated paste (Cmd+V / Ctrl+V) & active app detector
│   ├── clipboard.py         # Multi-format clipboard backup & restoration
│   └── permissions.py       # macOS Accessibility & Microphone permission checker
│
├── shortcuts/
│   ├── manager.py           # Push-to-talk & toggle hotkey coordinator
│   ├── mac_hook.py          # macOS native Function (Fn/Globe) key event monitor
│   └── fallback_hook.py     # Cross-platform hotkey listener (pynput)
│
├── database/
│   └── history.py           # SQLite database with automatic 30-day retention purge
│
├── assets/
│   ├── icon.png             # High-res 512x512 logo
│   ├── icon.ico             # Windows multi-resolution icon (16 to 256px)
│   └── icon.icns            # Native Apple macOS icon bundle
│
├── packaging/
│   ├── mac/                 # Info.plist & build_app.sh
│   ├── windows/             # installer.iss (Inno Setup)
│   └── justtalk.spec        # PyInstaller specification
│
└── tests/                   # Complete unit and integration test suite
```

---

## ⚖️ License
MIT License. Free and open source.
