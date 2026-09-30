# Installing Just Talk on Windows

This guide provides step-by-step instructions to install, configure, and uninstall **Just Talk** on Windows 10 and Windows 11 (64-bit).

---

## Method 1: Install via Setup Wizard (Recommended for Users)

### Step 1: Download & Run Installer
1. Download or open `JustTalk-Setup-1.0.0.exe` (found in `dist/windows_installer/` or GitHub Releases).
2. Double-click the installer to launch the modern branded setup wizard.

### Step 2: Handle Windows Defender SmartScreen (If Prompted)
Because the open-source installer is self-signed, Windows Defender SmartScreen may display:
- *"Windows protected your PC: Microsoft Defender SmartScreen prevented an unrecognized app from starting."*
1. Click **More info**.
2. Click **Run anyway**.

### Step 3: Complete Setup
1. **Installation Path**:
   - By default, Just Talk installs into your user profile directory (`%LOCALAPPDATA%\Programs\Just Talk`).
   - This means **no Administrator password or UAC prompt is required!**
2. **Tasks & Shortcuts**:
   - Check **Create a desktop shortcut** (checked by default).
   - Check **Launch Just Talk automatically on Windows startup** to have push-to-talk always ready.
3. Click **Install**.
   - The installer automatically unpacks binaries, installs the local Whisper model engine, and sets up Windows 10/11 taskbar integration.
4. On the final page, leave **Launch Just Talk** checked and click **Finish**.

---

## How to Uninstall Just Talk

Just Talk installs a dedicated uninstaller executable and registers full metadata in Windows settings.

### Method 1: Windows Settings (Standard)
1. Open **Settings** (Win + I) -> **Apps** -> **Installed apps** (or **Apps & features**).
2. Search for **Just Talk**.
3. Click the three dots `...` next to Just Talk and select **Uninstall**.
4. A confirmation dialog will ask if you want to proceed.
5. An optional prompt will ask:
   *"Do you also want to remove your local Just Talk configuration settings and history?"*
   - Select **Yes** to completely wipe all cached models and databases.
   - Select **No** to retain your API keys and history for future reinstalls.

### Method 2: Start Menu Shortcut
1. Open the **Start Menu**.
2. Scroll to the **Just Talk** folder.
3. Click **Uninstall Just Talk**.

### Method 3: Direct Uninstaller File
1. Navigate to:
   ```
   %LOCALAPPDATA%\Programs\Just Talk
   ```
2. Double-click `uninstall.exe` (or `unins000.exe`).

---

## Method 2: Build & Package from Source (For Developers)

If you are developing or compiling the Windows build yourself:

### Step 1: Prerequisites
1. **Python 3.10+** (or [uv](https://astral.sh/uv)):
   ```powershell
   winget install astral-sh.uv
   ```
2. **Inno Setup 6** (for compiling the installer):
   ```powershell
   choco install innosetup -y
   # or: winget install JRSoftware.InnoSetup
   ```

### Step 2: Run the One-Click Build Script
Open PowerShell in the project root directory and run:
```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build_exe.ps1
```
Or from Command Prompt (CMD):
```cmd
packaging\windows\build_exe.bat
```

This automated script performs:
1. Syncs all Python dependencies via `uv`.
2. Generates Windows `.ico` icons and branded installer artwork (`wizard_sidebar.bmp` and `wizard_small.bmp`).
3. Compiles the standalone application folder using PyInstaller (`dist\JustTalk\JustTalk.exe`).
4. Invokes Inno Setup to create the self-contained installer (`dist\windows_installer\JustTalk-Setup-1.0.0.exe`).
5. Copies the finished installer to `packaging\windows\JustTalk-Setup-1.0.0.exe`.

---

## Windows 10/11 Taskbar Pinning (AppUserModelID)

Just Talk registers an explicit Windows `AppUserModelID`:
```
JustTalk.Desktop.VoiceInput.1.0
```
When you right-click the taskbar icon and click **Pin to taskbar**, Windows keeps the app pinned under its custom icon rather than reverting to a generic Python or PyInstaller executable icon.
