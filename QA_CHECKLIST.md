# Just Talk — Quality Assurance (QA) Checklist

This document details the manual and automated validation procedures for **Just Talk** across macOS and Windows.

---

## 1. Windowing & Single Instance

| Test Case | Steps | Expected Result | Pass/Fail |
|-----------|-------|-----------------|-----------|
| **Single-Instance Enforcement** | 1. Launch Just Talk.<br>2. Try to launch a second instance from terminal or Finder. | Second launch terminates immediately; existing Just Talk window is raised and focused. | [ ] |
| **Dual-Mode Windowing** | 1. Launch Just Talk.<br>2. Click red window close button `(x)`. | Window hides without quitting. Menu bar tray icon remains active. Background push-to-talk continues functioning. | [ ] |
| **macOS Dock Transition** | 1. Open MainWindow.<br>2. Check Dock.<br>3. Close MainWindow.<br>4. Check Dock. | When MainWindow is open, Just Talk appears in macOS Dock as a regular application. When closed, activation policy reverts to Accessory (hidden from Dock). | [ ] |
| **Tray / Menu Bar Interaction** | 1. Click tray icon.<br>2. Select "Open Just Talk".<br>3. Select "History...".<br>4. Select "Settings...". | Menu opens smoothly; selecting options raises MainWindow directly to the corresponding screen (Home, History, Settings). | [ ] |
| **Clean Shutdown** | Select "Quit Just Talk" from tray menu or press `Cmd+Q` while window is focused. | All audio streams, hotkey monitors, and background threads stop cleanly. Lock file and socket are released. | [ ] |

---

## 2. Push-to-Talk & Audio Capture

| Test Case | Steps | Expected Result | Pass/Fail |
|-----------|-------|-----------------|-----------|
| **Push-to-Talk Trigger** | Hold `[ fn ]` (macOS) or `[ Right Alt ]` (Windows). Speak a short sentence. Release. | Floating pill appears at bottom-center; audio is recorded strictly while held. Transcription starts immediately on key release. | [ ] |
| **Accidental Tap Filter** | Tap shortcut key for < 200ms without speaking. | Audio capture cancels immediately without sending to STT or popping up error. | [ ] |
| **Stuck-Key Safeguard** | Hold shortcut for > 60 seconds. | Recording automatically caps at 60s to prevent memory explosion. | [ ] |
| **RMS Waveform Animation** | Hold shortcut and speak loudly vs softly. | 8 waveform bars smoothly modulate height based on live microphone RMS volume (fast attack ~40ms, smooth decay). | [ ] |
| **Silence / No Speech VAD** | Hold key in silence for 2 seconds and release. | Pill briefly shakes horizontally with amber warning "No speech detected" and auto-hides after 1.5s. | [ ] |

---

## 3. Speech-to-Text & In-Memory Model

| Test Case | Steps | Expected Result | Pass/Fail |
|-----------|-------|-----------------|-----------|
| **Local Whisper Warm RAM** | Hold key and say: "Meeting scheduled for 3 PM tomorrow." | Speech is transcribed locally via `faster-whisper` CTranslate2 model in < 400ms without internet connection. | [ ] |
| **Model Quality Switching** | In Settings > Voice & STT, switch from `base.en` to `tiny.en` or `small.en`. | Status updates; model is loaded into RAM in background thread. | [ ] |

---

## 4. Hardened AI Formatting & Zero-Loss Fallback

| Test Case | Steps | Expected Result | Pass/Fail |
|-----------|-------|-----------------|-----------|
| **Gemini Formatting** | Configure valid API key. Say: "um hey can you send me the report scratch that the presentation by tomorrow please". | Gemini formats text: removes hesitation, applies correction ("Can you send me the presentation by tomorrow, please?"). | [ ] |
| **Timeout / Offline Fallback** | Disconnect Wi-Fi or enter offline mode. Dictate a sentence. | Speech is **never lost**. App falls back to local light cleanup (capitalizes, removes filler words, adds period), inserts text, and pill displays `"Inserted (offline)"`. | [ ] |
| **Circuit Breaker Tripping** | Simulate 3 consecutive 5xx/timeout errors. | Circuit Breaker trips: pauses AI formatting for 5 minutes. Subsequent dictations instantly fallback locally without HTTP delay. Tray displays `"⚠️ AI formatting paused"`. | [ ] |
| **Circuit Breaker Cooldown & Recovery** | Wait 5 minutes after tripping or test connection in Settings. | Breaker enters half-open state; successful response clears failure counter and resumes AI formatting. | [ ] |
| **Granular Error Diagnosis** | In Settings > AI Formatting, test: invalid key, 404 model, 429 rate limit. | User receives helpful actionable diagnostic messages rather than raw stack traces. | [ ] |

---

## 5. Floating Pill Indicator

| Test Case | Steps | Expected Result | Pass/Fail |
|-----------|-------|-----------------|-----------|
| **Window Attributes** | Check pill while typing in full-screen games or documents. | Pill is click-through (`WA_TransparentForInput`), non-activating (`WA_ShowWithoutActivating`), and stays on top of all windows. | [ ] |
| **Morphing Geometry** | Trigger recording. | Smooth 180ms ease-out morph from circular dot to rounded capsule. | [ ] |
| **Inserted State** | Release key after valid dictation into active text field. | Pill turns emerald green (`#30D158`) with checkmark and label `"Inserted"`, auto-hiding after 1.2s. | [ ] |
| **Clipboard Fallback State** | Click on desktop wallpaper (no focused text field) and dictate. | Final text is placed on system clipboard. Pill displays `"Copied to clipboard"` (`#0A84FF`), auto-hiding after 1.5s. | [ ] |

---

## 6. Security & Credential Management

| Test Case | Steps | Expected Result | Pass/Fail |
|-----------|-------|-----------------|-----------|
| **OS Keychain Storage** | Enter API key in Settings or Onboarding. Save. Check config file (`~/.config/justtalk/config.json`). | API key is stored securely in macOS Keychain / Windows Credential Manager. `config.json` does **NOT** contain the plaintext key. | [ ] |
| **Config Migration** | Place a legacy plaintext `api_key` in `config.json` and start Just Talk. | Key is migrated to Keychain and removed from `config.json` automatically on startup. | [ ] |
| **Key Redaction in Logs** | Inspect terminal logs or error popups when calling Gemini. | All instances of `AIza...` and `AQ...` keys are redacted to `[REDACTED_API_KEY]`. | [ ] |

---

## 7. Interactive Onboarding & Tutorial

| Test Case | Steps | Expected Result | Pass/Fail |
|-----------|-------|-----------------|-----------|
| **First-Run Wizard** | Reset `has_completed_onboarding: false` and launch. | 5-step wizard opens with step indicator dots. | [ ] |
| **Permission Detection & Restart** | If Accessibility is granted after launch, check Step 1. | App detects event monitor state. If restart is needed, displays purple "Restart Just Talk" button. | [ ] |
| **Live Audio Demo (Step 2)** | Hold shortcut and speak sample phrase into demo practice box. | Waveform responds and text is transcribed into practice box. | [ ] |
| **Self-Correction Walkthrough (Step 3)** | Read explanation and try correction. | Compares raw vs cleaned output clearly. | [ ] |
| **Finish Onboarding** | Click "Get Started" on Step 5. | Sets `has_completed_onboarding: true`, saves config, closes wizard, and opens main application window. | [ ] |
| **Replay Tutorial** | In Settings > Tutorial & Onboarding, click "Replay Onboarding Tutorial". | Walkthrough reopens instantly. | [ ] |
