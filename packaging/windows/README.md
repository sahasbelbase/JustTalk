# Just Talk — Windows Installer & Packaging

This directory contains the automated packaging scripts and configurations for building the **Just Talk Windows Desktop Application and Installer**.

---

## Features

- **Modern Installer Wizard**:
  - High-resolution custom branding (`wizard_sidebar.bmp` and `wizard_small.bmp`).
  - Seamless installation to per-user directory (`%LOCALAPPDATA%\Programs\Just Talk` or `Program Files`) without requiring administrator elevation.
  - Optional Desktop shortcut and "Start on Windows boot" integration.
- **Dedicated Standalone Uninstaller**:
  - Automatically writes `uninstall.exe` directly inside the installation directory.
  - Registers full metadata in Windows **Installed Apps** (Settings > Apps > Installed apps) and Control Panel (**Add or Remove Programs**).
  - Clean uninstall with an optional prompt to purge local settings and transcription history.
- **Windows 10/11 Taskbar Pinning (AppUserModelID)**:
  - Configures `AppUserModelID: JustTalk.Desktop.VoiceInput.1.0` so pinning Just Talk to the Taskbar or Start Menu preserves the custom high-res icon and never reverts to a generic Python or PyInstaller executable.

---

## Directory Structure

```
packaging/windows/
├── build_exe.ps1             # Automated PowerShell build script (Recommended)
├── build_exe.bat             # Automated Windows Command Prompt batch build script
├── installer.iss             # Modern Inno Setup installer script
├── installer.nsi             # Modern NSIS (Nullsoft) alternative installer script
├── generate_wizard_assets.py # Generates 328x628 sidebar & 110x110 header bitmaps
├── wizard_sidebar.bmp        # Branded obsidian sidebar artwork
└── wizard_small.bmp          # Branded header icon artwork
```

---

## How to Build on Windows

### Prerequisites
1. **Python 3.10+** (or [uv](https://astral.sh/uv)):
   ```powershell
   winget install astral-sh.uv
   ```
2. **Inno Setup 6** (for `.exe` setup installer):
   ```powershell
   choco install innosetup -y
   # or: winget install JRSoftware.InnoSetup
   ```

### 1. Build via PowerShell (One-Click)
```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build_exe.ps1
```

### 2. Build via Command Prompt (CMD)
```cmd
packaging\windows\build_exe.bat
```

### Build Outputs
- **Standalone Folder**: `dist\JustTalk\JustTalk.exe`
- **Modern Setup Installer**: `dist\windows_installer\JustTalk-Setup-1.0.0.exe` (copied to `packaging\windows\JustTalk-Setup-1.0.0.exe`)

---

## Automated CI/CD
Windows builds are automatically run via GitHub Actions (`.github/workflows/build.yml`) on every push to `main` and release tags, producing downloadable Windows installer artifacts.
