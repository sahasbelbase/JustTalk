# Installing Just Talk on macOS

This guide walks you through installing, configuring permissions, and running **Just Talk** on macOS (Apple Silicon M1/M2/M3/M4 and Intel Macs).

---

## Method 1: Install Pre-Built DMG (Recommended for Users)

### Step 1: Open the DMG Installer
1. Double-click `JustTalk-macOS.dmg` (found in `dist/`, `packaging/mac/`, or downloaded from GitHub Releases).
2. A window opens showing **Just Talk** and a shortcut to your **Applications** folder.
3. Drag the **Just Talk** icon into the **Applications** folder.

### Step 2: Open Just Talk
1. Open **Finder** -> Go to **Applications** -> double-click **Just Talk**.
2. **If macOS Gatekeeper shows an alert**:
   - *"Just Talk cannot be opened because Apple cannot check it for malicious software"*
   - **Fix via GUI**:
     Right-click (or Control-click) `Just Talk.app` in `/Applications` -> Select **Open** -> Click **Open** again in the popup dialog.
   - **Fix via Terminal**:
     Run this single command to remove the quarantine flag:
     ```bash
     xattr -cr /Applications/JustTalk.app
     ```

---

## Method 2: Build & Install from Source (For Developers)

If you are modifying or compiling Just Talk yourself, follow these steps:

### Step 1: Install Xcode Command Line Tools
Just Talk uses native macOS Quartz and CoreAudio frameworks. Install the Apple command-line developer tools:
```bash
xcode-select --install
```
*(If already installed, this will confirm that the tools are present).*

### Step 2: Install uv (Fast Python Package Manager)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Step 3: Run the Automated Build Script
From the project root directory, run:
```bash
chmod +x packaging/mac/build_app.sh
./packaging/mac/build_app.sh
```
This script will:
1. Generate high-resolution `.icns` application icons.
2. Compile standalone binaries with PyInstaller.
3. Apply `Info.plist` and entitlements (`com.apple.security.device.audio-input`).
4. Sign the bundle with ad-hoc identity `com.justtalk.desktop`.
5. Package `dist/JustTalk-macOS.dmg` with drag-and-drop Applications symlink.

### Step 4: Install to Applications
```bash
cp -R dist/JustTalk.app /Applications/JustTalk.app
open /Applications/JustTalk.app
```

---

## Step 3: Grant Required macOS Permissions

To transcribe your voice and type into other apps (like Chrome, Brave, VS Code, Notes, Slack), macOS requires **two permissions**:

### 1. Microphone Permission
- **Why**: Captures your spoken voice when holding the shortcut key.
- **How**:
  - Open **System Settings** -> **Privacy & Security** -> **Microphone**.
  - Toggle **Just Talk** to **ON** (Enabled).

### 2. Accessibility Permission
- **Why**: Allows Just Talk to detect global shortcut key events (Quartz EventTap), dynamically locate your text cursor/caret position, and automatically insert transcribed text.
- **How**:
  - Open **System Settings** -> **Privacy & Security** -> **Accessibility**.
  - Click **+** (or toggle) and add `/Applications/JustTalk.app`.
  - Ensure the toggle is **ON** (Enabled).

### 3. Input Monitoring Permission (Optional / Auxiliary)
- Open **System Settings** -> **Privacy & Security** -> **Input Monitoring**.
- Ensure **Just Talk** is toggled **ON**.

---

## Troubleshooting & Quick Fixes

### Quick Setup & Diagnostic Script
We have included a dedicated 1-click helper script in the repository:
```bash
./packaging/mac/setup_mac.sh
```
This script checks your Xcode CLI tools, clears quarantine attributes, verifies codesigning, and inspects microphone entitlements.

### Microphone Not Hearing Audio / Stuck in TCC?
If macOS ever stops passing audio to Just Talk after a system update or rebuild:
```bash
# Reset TCC approval for microphone:
tccutil reset Microphone com.justtalk.desktop

# Reset TCC approval for accessibility:
tccutil reset Accessibility com.justtalk.desktop
```
Then restart Just Talk:
```bash
pkill -f "JustTalk" || true
open /Applications/JustTalk.app
```
macOS will display fresh permission prompts that you can approve in 1 click.

### Re-Signing the App Bundle Manually
If you manually copied frameworks or updated files inside `JustTalk.app`:
```bash
codesign --force --deep --sign "-" --entitlements packaging/mac/entitlements.plist --identifier "com.justtalk.desktop" /Applications/JustTalk.app
```
