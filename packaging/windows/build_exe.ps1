# =========================================================================
# Automated Windows PowerShell Build Script for Just Talk
# Builds standalone executable and high-resolution setup installer
# =========================================================================
$ErrorActionPreference = "Stop"

Write-Host "=== Building Just Talk for Windows ===" -ForegroundColor Cyan
$ProjectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location $ProjectRoot

# 1. Sync dependencies
Write-Host "--> Verifying Python environment with uv..." -ForegroundColor Yellow
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    uv sync
} else {
    python -m pip install -e .
}

# 2. Generate icons and installer branding assets
Write-Host "--> Generating application icons and modern installer graphics..." -ForegroundColor Yellow
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    uv run python just_talk/assets/generate_icons.py
    uv run python packaging/windows/generate_wizard_assets.py
} else {
    python just_talk/assets/generate_icons.py
    python packaging/windows/generate_wizard_assets.py
}

# 3. PyInstaller Build
Write-Host "--> Compiling standalone binary with PyInstaller..." -ForegroundColor Yellow
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    uv run pyinstaller --noconfirm --clean packaging/justtalk.spec
} else {
    pyinstaller --noconfirm --clean packaging/justtalk.spec
}

if (-not (Test-Path "dist\JustTalk\JustTalk.exe")) {
    Write-Error "PyInstaller failed to build dist\JustTalk\JustTalk.exe"
}

Write-Host "--> Standalone executable built: dist\JustTalk\JustTalk.exe" -ForegroundColor Green

# 4. Inno Setup Compiler
$isccPath = Get-Command "iscc" -ErrorAction SilentlyContinue
if (-not $isccPath) {
    # Check default Inno Setup installation directory
    if (Test-Path "C:\Program Files (x86)\Inno Setup 6\ISCC.exe") {
        $isccPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    } elseif (Test-Path "C:\Program Files\Inno Setup 6\ISCC.exe") {
        $isccPath = "C:\Program Files\Inno Setup 6\ISCC.exe"
    }
}

if ($isccPath) {
    Write-Host "--> Compiling modern branded installer with Inno Setup..." -ForegroundColor Yellow
    & $isccPath packaging\windows\installer.iss

    $InstallerExe = Get-ChildItem -Path "dist\windows_installer\*.exe" | Select-Object -Last 1
    if ($InstallerExe) {
        Copy-Item $InstallerExe.FullName -Destination "packaging\windows\JustTalk-Setup-1.0.0.exe" -Force
        Write-Host "=== Windows Installer ready at: $($InstallerExe.FullName) and packaging\windows\JustTalk-Setup-1.0.0.exe ===" -ForegroundColor Green
    }
} else {
    Write-Host "[NOTE] Inno Setup compiler (iscc) not found in PATH." -ForegroundColor DarkYellow
    Write-Host "To build installer: choco install innosetup or download from jrsoftware.org" -ForegroundColor DarkYellow
}

Write-Host "=== Windows Build Workflow Finished! ===" -ForegroundColor Cyan
