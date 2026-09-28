@echo off
REM =========================================================================
REM Automated Windows Build Script for Just Talk (PyInstaller + Inno Setup)
REM =========================================================================
setlocal enabledelayedexpansion

echo === Building Just Talk for Windows ===
cd /d "%~dp0\..\.."

REM 1. Install dependencies
echo --> Verifying Python environment...
uv sync

REM 2. Generate icon assets if missing
echo --> Generating icon assets...
uv run python just_talk/assets/generate_icons.py

REM 3. Compile standalone binary with PyInstaller
echo --> Compiling with PyInstaller...
uv run pyinstaller --noconfirm --clean packaging/justtalk.spec

if not exist "dist\JustTalk\JustTalk.exe" (
    echo [ERROR] PyInstaller failed to produce dist\JustTalk\JustTalk.exe
    exit /b 1
)

echo --> JustTalk.exe successfully built in dist\JustTalk\

REM 4. Build Windows Inno Setup installer if iscc is available
where iscc >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo --> Building Inno Setup Installer...
    iscc packaging\windows\installer.iss
    echo === Windows Installer created at dist\windows_installer\ ===
) else (
    echo [WARNING] 'iscc' (Inno Setup Compiler) not found in PATH.
    echo Standalone executable is available at: dist\JustTalk\JustTalk.exe
    echo To build installer: install Inno Setup 6 and run 'iscc packaging\windows\installer.iss'
)

echo === Build Complete! ===
