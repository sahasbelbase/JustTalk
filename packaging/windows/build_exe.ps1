# =========================================================================
# Automated Windows PowerShell Build Script for Just Talk
# =========================================================================
$ErrorActionPreference = "Stop"

Write-Host "=== Building Just Talk for Windows ===" -ForegroundColor Cyan
$ProjectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location $ProjectRoot

# 1. Sync dependencies
Write-Host "--> Verifying Python environment with uv..." -ForegroundColor Yellow
uv sync

# 2. Generate icons
Write-Host "--> Generating icon assets..." -ForegroundColor Yellow
uv run python just_talk/assets/generate_icons.py

# 3. PyInstaller Build
Write-Host "--> Compiling with PyInstaller..." -ForegroundColor Yellow
uv run pyinstaller --noconfirm --clean packaging/justtalk.spec

if (-not (Test-Path "dist\JustTalk\JustTalk.exe")) {
    Write-Error "PyInstaller failed to build dist\JustTalk\JustTalk.exe"
}

Write-Host "--> Standalone executable built: dist\JustTalk\JustTalk.exe" -ForegroundColor Green

# 4. Inno Setup Compiler
$isccPath = Get-Command "iscc" -ErrorAction SilentlyContinue
if ($isccPath) {
    Write-Host "--> Compiling installer with Inno Setup..." -ForegroundColor Yellow
    iscc packaging\windows\installer.iss
    Write-Host "=== Windows Installer created at dist\windows_installer\ ===" -ForegroundColor Green
} else {
    Write-Host "[NOTE] Inno Setup compiler (iscc) not found in PATH." -ForegroundColor DarkYellow
    Write-Host "You can zip or run the standalone folder: dist\JustTalk\JustTalk.exe" -ForegroundColor DarkYellow
}
