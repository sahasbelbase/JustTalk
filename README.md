# Just Talk (v3.0.0)

> **A fast, quiet voice keyboard for macOS and Windows.**  
> Think → Speak → Done.

**Website and downloads: [sahasbelbase.github.io/JustTalk](https://sahasbelbase.github.io/JustTalk/)**

[![Tests](https://github.com/sahasbelbase/JustTalk/actions/workflows/build.yml/badge.svg)](https://github.com/sahasbelbase/JustTalk/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Website](https://img.shields.io/badge/Website-sahasbelbase.github.io%2FJustTalk-blue)](https://sahasbelbase.github.io/JustTalk/)
[![Releases](https://img.shields.io/github/v/release/sahasbelbase/JustTalk?color=blue&label=Latest%20Release)](https://github.com/sahasbelbase/JustTalk/releases/latest)

Just Talk is a lightweight desktop productivity utility that runs quietly in your system tray or menu bar. Tap your hotkey, speak naturally, and your words appear directly in whatever application you are using (Chrome, VS Code, Slack, Notion, Discord, Terminal, etc.)—complete with instant draft streaming and optional AI-powered grammar polishing.

On a Mac, Just Talk's own AI model, trained on real Nepali speech, cleans up English and translates Nepali and Nepglish into English right on your computer, with no internet and no API key.

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

## What's New in Version 3.0.0

* **Just Talk's own on-device AI (Mac):** a small language model made for Just Talk cleans up English and translates Nepali and Nepglish into English on your Mac, with no internet and no API key. A typical dictation takes about 0.2 seconds. Turn it on in **Settings › AI Formatting** (a one-time 1.8 GB download from Hugging Face, checked with SHA-256). A cloud AI provider, if you set one up, is used as a backup. See [how it was trained and tested](#just-talks-own-on-device-model).
* **Voice profile setup:** new setup screens walk you through permissions, your languages, your kind of work, and your voice. You read a few short sentences, words light up as they are heard, and every speech engine on your computer is scored on your voice. The result tells you which engine to use and what it tends to mishear.
* **Learns your words:** names and jargon from your dictations and from voice setup are passed to Apple's recognizer, so "git" stops coming out as "gate". **Settings › Updates & Startup › Learning** shows what it learned and lets you remove anything wrong. An optional AI review of past dictations (text only) can find more.
* **Faster Mixed mode (Mac):** Apple hears English and Kriti hears Nepali. Just Talk now picks one for each stretch of speech (cut at pauses, 8 seconds at most), and recognizes, translates and cleans each finished stretch while you are still talking. In testing, dictations of 89 to 117 seconds were ready 1.3 to 2.3 seconds after stopping. The live preview shows English stretches in English.
* **Cleaner text:** hesitation sounds (umm, uhh, hmm, and उम् the way Kriti writes it) are removed everywhere. Lists appear only when you ask for one ("list", "points", "first... second", लिस्ट, बुँदा). AI answers never contain an em dash. A spoken web address such as "youtube.com" is typed as is. A leading "yes", "no" or "okay" is never dropped. Code and indentation are left alone.
* **Mac fixes:** Escape really cancels a dictation, with no Input Monitoring permission needed. The pill's ✕ returns you to the app you were typing in. Text that said "Inserted" but never appeared in Chromium apps (Brave, Chrome, VS Code) now lands. Terminals no longer get the same text twice.
* **Settings and Home:** each settings menu entry is its own page, like System Settings, with search across every page. Home and History show real numbers from your own dictations.

---

## Just Talk's Own On-Device Model

The speech engine (Kriti for Nepali, Apple or Whisper for English) turns your voice into words. Just Talk's own model then turns those words into clean English. It is a LoRA fine-tune of [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B), trained on a MacBook's own GPU with MLX, with no cloud GPUs, and it runs with [llama.cpp](https://github.com/ggml-org/llama.cpp) on Metal.

* **Current version:** v6.2, `justtalk-qwen3-1.7b-v6.2-Q8_0.gguf` (1.83 GB), Apache-2.0
* **Model card, files and every result:** [huggingface.co/SahasBelbase/justtalk-qwen3-1.7b-gguf](https://huggingface.co/SahasBelbase/justtalk-qwen3-1.7b-gguf)
* **Speed on an Apple M5 laptop:** median 0.24 s for a Nepali dictation and 0.12 s for an English clean-up
* **Mac only for now.** On Windows, AI formatting uses your cloud provider or Ollama.

### What it learned from

13,742 examples (13,592 for training and 150 kept back for validation), one pass, 8.7 million trainable parameters (about 0.5% of the model).

| Source | Examples |
| :--- | ---: |
| Nepali to English sentence pairs from [AI4Bharat BPCC](https://huggingface.co/datasets/ai4bharat/BPCC), some spoken by a Mac voice and written down by Kriti | 6,300 |
| English said with a Nepali accent and written in Devanagari by Kriti | 2,619 |
| English dictation clean-ups, including developer words Apple mishears ("push to get", "poll request") | 1,597 |
| Real voice: 434 recorded sentences (used twice) and 41 lines dictated through the app (used three times) | 991 |
| Hand-written fixes: negatives paired with positives, "probably" and "might", lists asked for and not, fillers, Action Mode edits | 848 |
| Everyday Nepglish sentences (174, read by Mac voices and written down by Kriti) | 696 |
| Long run-on dictations (3 to 6 sentences joined) | 691 |

Every English answer follows the same rules: keep the meaning, never add or drop a detail, never flip a "not", and no em dashes or semicolons.

### Benchmarks

chrF++ (0 to 100, higher is better) against the expected English. Every model ran the same tests with the same prompts, and none of the test sentences were used in training.

| Test (sentences) | Qwen3 1.7B, untuned | v2 (previous model) | **v6.2 (in the app now)** |
| :--- | ---: | ---: | ---: |
| Real Nepali dictations (29) | 35.4 | 40.1 | **41.1** |
| FLORES+ Nepali to English (200) | 40.8 | 40.8 | **42.1** |
| English clean-up (29) | 60.8 | 68.9 | **67.5** |
| Recorded voice, held out (91) | | 48.9 | **56.1** |
| Lines dictated through the app, held out (10) | | 64.5 | **77.5** |

Behaviour checks on 49 sentences it never saw:

| Check | v2 | **v6.2** |
| :--- | ---: | ---: |
| Keeps every "not" | 13 / 14 | **13 / 14** |
| Keeps "probably", "might", "I think" | 4 / 7 | **5 / 7** |
| Makes a list when you ask | 0 / 6 | **6 / 6** |
| No list when you didn't | 4 / 4 | **4 / 4** |
| Drops umm, uhh, hmm | 3 / 5 | **5 / 5** |

**Nine versions to get here.** 0.6B was too small for Nepali. v2 on the 1.7B model was the first real win and stayed in the app for a long time. Training further on top of it (v3) made it memorise the recordings and forget general Nepali, so every later version starts from the base model. v4 and v5 improved English but started flipping meaning ("I'll go to the office tomorrow" became "I will not come") and were pulled. v6.1 leaned towards "not" because its negative examples had no positive twins. v6.2 pairs every negative with its positive and is the first version better than v2 on real Nepali, general Nepali, the recorded voice and app dictation at the same time. Every version's scores are on the [model card](https://huggingface.co/SahasBelbase/justtalk-qwen3-1.7b-gguf).

**Known limits:** it sometimes drops होला (probably), doesn't know a few words such as अबेर (late), and very rarely misses a negative. It can't fix a number the speech engine wrote down wrong. It is a small model made for dictation, not for chat or facts.

---

## Previous Release: 2.3.1

* **Lighter when idle:** Just Talk frees the speech models from memory after you haven't dictated for a while (Settings › Free Memory, 10 minutes by default, or never) and reloads them while you speak. On our test Mac this dropped memory use from about 2.4 GB to about 0.7 GB with the large Whisper model and Kriti loaded. The window's status refresh also stops while it is hidden.
* **Action Mode writes for you:** With nothing selected, hold your shortcut + Shift and say *"write me a sick leave email"* or *"write a short poem about rain"*. It needs AI formatting turned on.
* **Better mixed Nepali + English:** Mostly-English speech in Mixed mode now goes to Whisper instead of Kriti, so English words are no longer spelled in Devanagari.
* **Fewer "not recognized" results in noisy rooms:** If the noise-reduced audio gives no text, Just Talk tries the original microphone audio before giving up.
* **AI polish times out less:** The polish step waits up to 5 seconds when your raw words are already typed, instead of 2.

## Earlier Release: 2.3.0

* **Simpler language setup:** Tell Just Talk once which languages you speak (Settings › Languages), then pick what you're typing in right now from the **Typing in** buttons on Home or the tray menu — English, नेपाली, or Mixed — with a single **Translate to English** switch. Settings that used to contradict each other can no longer get out of step, and English stays the default.
* **Kriti offline Nepali engine:** Nepali dictation can now run fully on your computer with [Kriti](https://github.com/Naamche-Labs/kriti) by Naamche Labs. On our test recordings it made 0 word errors where the cloud engine made 4, including on low and noisy speech and mixed Nepglish. One-click download (475 MB) from Home.
* **Voice isolation that keeps your words:** Re-designed voice enrollment (three phrases, live microphone meter, quality checks) and smarter matching. Your own dictations are no longer dropped as "background voice"; only clearly different voices are ignored, and if one was you, press Paste Last Dictation to get it back.
* **More voice edits:** Select text and say "polish this prompt", "fix grammar", "fix this query" (SQL) or "fix this code". Turning a list into a paragraph and back now works reliably, and Action Mode no longer switches itself off when you release Shift.
* **Fixes:** Nepali speech is no longer sent to an English recogniser; expanded History entries no longer fill the screen.

## Earlier Release: 2.2.0

* **Edit selected text by voice:** Select text in any app, hold your shortcut + **Shift**, and say what to change ("make this shorter", "make it polite", "translate to Nepali", "turn this into bullet points"). Just Talk rewrites the selection in place. With nothing selected, Action Mode works as before.
* **Paste last dictation:** Press **Ctrl + Cmd + V** (macOS) or **Win + Alt + V** (Windows) to type your last dictation again into whatever app is focused, handy when the cursor was in the wrong place. The tray menu also has **Copy Last Dictation**.
* **AI no longer answers your dictation:** Speech that sounds like a question ("give me an overview… what do you think?") is now cleaned up as text instead of being answered or replaced by a line like "I will translate the spoken transcript…".
* **Windows fixes:** Turning on "Open Just Talk at login" no longer gets the app flagged and removed by antivirus (it now uses a Startup-folder shortcut), and reopening the window keeps the page you were on instead of jumping to Home.

## Earlier Release: 2.1.0

* **Long dictation that keeps everything:** Speak for up to 5 minutes with pauses. Long audio is split at natural pauses and stitched back together, so nothing said before a pause is lost or repeated. In tap mode, recording stops after 8 seconds of silence (was 4.5 s).
* **Smarter AI cleanup:** Self-corrections are resolved ("meet at five, actually four" → "Can we meet at four?"), grammar and spelling are fixed Grammarly-style, and long dictations get more time instead of falling back to "inserted offline". Slow replies no longer pause AI formatting for everyone.
* **Premium, emoji-free interface:** A single set of line icons, plain section titles, a compact settings page that saves automatically, readable activity chart labels, and correct dark-mode colours.
* **Reliable background updates:** "Check for updates", model downloads, mic test and AI connection tests now report back to the window (previously some never finished).
* **Windows fixes:** Dictation now pastes into Chrome, VS Code, Slack, Office and other apps instead of only copying, and scrolling over a dropdown scrolls the page instead of changing the value.
* **Clean quit:** Cmd+Q, tray Quit, logout and shutdown all close Just Talk properly.

## Earlier Release: 2.0.1

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

* **On-Device AI (Mac):** Just Talk's own model cleans up English and translates Nepali and Nepglish offline, in about 0.2 seconds.
* **Voice Profile:** setup scores every speech engine on your voice and learns the words you use.
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
  * Say *"write me a sick leave email"* with **nothing selected** → writes the email where your cursor is.
  * **Select text first** and just say the change, e.g. *"make this shorter"* → the selection is rewritten in place.
* **Paste Last Dictation:** **Ctrl + Cmd + V** (macOS) / **Win + Alt + V** (Windows) types your last dictation again.

---

## Privacy & Offline Mode

1. **Your choice of speech engine:** With **Pure Offline Mode** or local Whisper, audio never leaves your computer. The built-in macOS engine uses Apple's on-device recognition where your Mac supports it. The Google Web Speech engine (used for Nepali, and first on Windows when online) sends audio to Google to transcribe it.
2. **Text-only AI formatting:** Only the transcribed text — never audio — is sent to the AI provider you choose (or to Ollama running locally) for punctuation, grammar and cleanup.
3. **Graceful fallback:** If the AI provider is slow or unreachable, the locally cleaned transcript is inserted instead. Short phrases wait at most ~2 s; long dictations get up to ~8 s. Only real outages (not slow replies) pause AI formatting.
4. **Pure Offline Mode:** One toggle disables every network request — on-device transcription only, and cloud AI formatting is switched off. On a Mac, the on-device AI model keeps cleaning up and translating.
5. **On-device AI sends nothing:** Just Talk's own model runs on your Mac. Your words never leave it, and it works with no account and no API key.
6. **Local credential storage:** API keys are stored only on your computer, in a private `.credentials` file in Just Talk's app-data folder with owner-only (0600) permissions, and are sent only to the provider you selected.

---

## Bring Your Own Model (BYOM)

Just Talk gives you absolute freedom to choose both your **Speech Recognition Engine** and your **AI Formatting Model**:

### 1. Speech-to-Text (STT) Engines
* **OS-Native Dictation (Default):** Zero latency, zero setup on Apple Silicon / macOS and Windows.
* **Google Web Speech (Cloud Fallback):** 100% free, zero login, zero API keys required. Excellent for multilingual and low-resource languages.
* **Local Whisper / BYOM:** Choose standard Whisper models (`base.en`, `small.en`, `large-v3-turbo`) or point to any custom Hugging Face repo or local CTranslate2 folder.

### 2. Just Talk's Own On-Device Model (Mac)
Turn on **Use the on-device AI model** in Settings › AI Formatting. It downloads once (1.8 GB) from [Hugging Face](https://huggingface.co/SahasBelbase/justtalk-qwen3-1.7b-gguf) and then cleans up English and translates Nepali and Nepglish with no internet. See [Just Talk's Own On-Device Model](#just-talks-own-on-device-model) for the training data and benchmarks.

### 3. Local Offline AI Formatting with Ollama (100% On-Device)
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
| **Offline Nepali** | Kriti (ONNX) | ~475 MB | Not measured | ~1.5 s for 90 s of speech | Nepali and Nepglish, fully offline |

The on-device AI model (Mac) is separate from the speech engine: 1.83 GB on disk, about 0.2 s per dictation on an Apple M5.

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

Just Talk has 351 tests covering configuration, SQLite history, voice activity detection, action routing, AI fallbacks, the on-device model's output checks, text filters, Mixed-mode routing, the voice profile, single-instance enforcement and native speech engines. Tests run in a temporary home folder and never touch your real settings:

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
│   ├── language_setup.py       # One source of truth for language settings
│   ├── model_lifecycle.py      # Frees speech and AI models from memory when idle
│   │
│   ├── app/
│   │   ├── main.py             # Entrypoint, dictation pipeline, Mixed-mode routing per stretch
│   │   ├── single_instance.py  # IPC socket / mutex single-instance enforcer
│   │   ├── theme.py            # Design tokens, typography, dark/light styles
│   │   ├── overlay.py          # Floating status pill (waveform, live preview, cancel)
│   │   ├── main_window.py      # Home, History, Settings (one page per menu entry), Conventions
│   │   ├── home_view.py        # Dashboard with real stats and a contribution graph
│   │   ├── history_view.py     # Searchable dictation history with one-click re-copy
│   │   ├── conventions_view.py # Code and SQL writing conventions manager
│   │   ├── onboarding_window.py# Setup: permissions, languages, your work, voice profile, first try
│   │   ├── onboarding_widgets.py # Reading view with live word highlighting, mic meter, step bar
│   │   ├── learned_dialog.py   # "See what it learned": review and remove learned words
│   │   ├── voice_enroll_dialog.py # Voice enrollment and "Test my voice"
│   │   ├── ai_formatting_view.py# AI provider, API key, model and formatting sandbox
│   │   ├── language_selector.py# Searchable language dropdown
│   │   ├── icons.py            # Monochrome SVG line icons (no emoji in the UI)
│   │   ├── ui_thread.py        # run_on_ui_thread(): safe worker-thread → Qt UI callbacks
│   │   ├── wheel_guard.py      # Stops the mouse wheel changing dropdowns while scrolling
│   │   └── tray.py             # Native system tray / menu bar integration
│   │
│   ├── audio/
│   │   ├── recorder.py         # 16kHz low-latency streaming microphone buffer (sounddevice)
│   │   ├── vad.py              # Voice activity detection, silence trimming, pause-aligned chunking
│   │   ├── noise_filter.py     # Light noise reduction (DeepFilterNet)
│   │   ├── speaker_recognizer.py # WeSpeaker CAM++ speaker embeddings
│   │   └── voice_match.py      # Whether a dictation came from an enrolled voice
│   │
│   ├── stt/
│   │   ├── engine.py           # Speech-to-text abstract base class
│   │   ├── mac_native_engine.py# Apple SFSpeechRecognizer; learned words go in as contextual strings
│   │   ├── windows_native_engine.py # Windows Media Speech Recognition engine
│   │   ├── google_web_engine.py# Zero-login, zero-key Google Web Speech API engine
│   │   ├── whisper_engine.py   # faster-whisper (CTranslate2) local inference engine
│   │   ├── kriti_engine.py     # Kriti offline Nepali engine
│   │   ├── kriti_onnx.py       # Kriti on NumPy + ONNX Runtime only (no NeMo, no PyTorch)
│   │   ├── long_form.py        # Live-partial caching so long dictation keeps earlier speech
│   │   └── model_manager.py    # Multi-tier model catalog and downloader
│   │
│   ├── ai/
│   │   ├── local_model.py      # Just Talk's own on-device model: download, prompts, output checks
│   │   ├── gemini.py           # Gemini client, local cleanup, text filters (fillers, dashes, web addresses)
│   │   ├── prompts.py          # System prompts (Subtle, Formal, Concise, Code, Nepglish)
│   │   ├── actions.py          # Speech intent router for Action Mode (Fn + Shift)
│   │   ├── providers.py        # Multi-provider LLM coordinator (Gemini, Ollama, Claude, OpenAI)
│   │   └── nvidia_fallback.py  # OpenAI-compatible NVIDIA endpoint
│   │
│   ├── profile/                # Voice profile and learning
│   │   ├── scripts.py          # Sentences read during voice setup, seeded by kind of work
│   │   ├── scoring.py          # Scores a read-aloud take against the sentence shown
│   │   ├── session.py          # One voice-setup session: next sentence, what each engine heard
│   │   ├── engines.py          # Engines compared in setup, and switching to the winner
│   │   ├── learner.py          # Learns your words and the speech engine's mix-ups
│   │   └── store.py            # The saved profile, in your own app-data folder
│   │
│   ├── system/
│   │   ├── audio_ducker.py     # Background audio mute/ducking during speech
│   │   ├── inserter.py         # Paste with clipboard restore, quick draft, paste check
│   │   ├── clipboard.py        # Multi-format clipboard backup & atomic restoration
│   │   ├── context_detector.py # Active editor/application context detector
│   │   ├── caret_locator.py    # Finds the focused text field and caret
│   │   ├── autostart.py        # Open at login (macOS and Windows)
│   │   ├── updater.py          # Checks GitHub Releases and updates in place
│   │   └── permissions.py      # macOS Accessibility & Microphone permission checker
│   │
│   ├── shortcuts/
│   │   ├── manager.py          # Tap-to-toggle & push-to-talk state coordinator
│   │   ├── mac_hook.py         # Native macOS CGEventTap Function (Fn/Globe) key monitor
│   │   ├── mac_escape.py       # Escape cancels: a hot key held only while recording
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

## Author

Built by Sahas Belbase. Portfolio: [sahas.netlify.app](https://sahas.netlify.app/)

## Third-Party Models & Credits

**Offline Nepali speech engine: Kriti.** Just Talk's optional offline Nepali engine is an ONNX conversion of [Kriti](https://github.com/Naamche-Labs/kriti) by [Naamche Labs](https://naamchelabs.com), an open Nepali speech recognition model (119M parameters) derived from the [AI4Bharat Nepali IndicConformer](https://huggingface.co/ai4bharat/indicconformer_stt_ne_hybrid_ctc_rnnt_large). Naamche Labs report 4.1% WER on clean read Nepali and 40.6% on the NepTel real-call benchmark (Whisper Large-V3: 96.3%). All credit for the model goes to Naamche Labs and AI4Bharat.

* **License:** MIT, as released by the Kriti authors and AI4Bharat. Training datasets keep their own licenses and are not distributed.
* **Changes:** exported from `kriti.nemo` to ONNX and reimplemented feature extraction, RNNT decoding and danda restoration in NumPy, so it runs with ONNX Runtime alone. The conversion, model card and parity results are published at [github.com/sahasbelbase/kriti](https://github.com/sahasbelbase/kriti); the converted model reproduces Kriti's original transcripts exactly on the parity clips.

**On-device AI model: Just Talk's fine-tune of Qwen3-1.7B.** Made by Sahas Belbase and published at [huggingface.co/SahasBelbase/justtalk-qwen3-1.7b-gguf](https://huggingface.co/SahasBelbase/justtalk-qwen3-1.7b-gguf) under Apache-2.0.

* **Base model:** [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) by the Qwen team (Apache-2.0).
* **Training data:** Nepali to English pairs from [BPCC](https://huggingface.co/datasets/ai4bharat/BPCC) by AI4Bharat (CC-BY-4.0), plus Just Talk's own recordings and hand-written examples. FLORES+ (CC-BY-SA-4.0) is used for testing only.
* **Runtime:** [llama.cpp](https://github.com/ggml-org/llama.cpp) through llama-cpp-python (MIT). Trained with [MLX](https://github.com/ml-explore/mlx) (MIT).

**Voice recognition: Wespeaker CAM++.** Speaker recognition uses the [Wespeaker CAM++ VoxCeleb model](https://huggingface.co/Wespeaker/wespeaker-voxceleb-campplus) (Apache-2.0), downloaded on demand and run entirely on device.
