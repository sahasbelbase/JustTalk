@echo off
REM =========================================================================
REM Automated Windows Build Script for Just Talk (PyInstaller + Inno Setup)
REM =========================================================================
setlocal enabledelayedexpansion

echo === Building Just Talk for Windows ===
cd /d "%~dp0\..\.."

REM 1. Install dependencies
echo --> Verifying Python environment...
where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv sync
) else (
    python -m pip install -e .
)

REM 2. Generate icon assets and installer artwork
echo --> Generating icon assets and installer artwork...
where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run python just_talk/assets/generate_icons.py
    uv run python packaging/windows/generate_wizard_assets.py
) else (
    python just_talk/assets/generate_icons.py
    python packaging/windows/generate_wizard_assets.py
)

REM 3. Compile standalone binary with PyInstaller
echo --> Compiling with PyInstaller...
where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run pyinstaller --noconfirm --clean packaging/justtalk.spec
) else (
    pyinstaller --noconfirm --clean packaging/justtalk.spec
)

if not exist "dist\JustTalk\JustTalk.exe" (
    echo [ERROR] PyInstaller failed to produce dist\JustTalk\JustTalk.exe
    exit /b 1
)

echo --> JustTalk.exe successfully built in dist\JustTalk\

REM 4. Build Windows Inno Setup installer if iscc is available
set ISCC_CMD=iscc
where iscc >nul 2>nul
if %ERRORLEVEL% neq 0 (
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
        set ISCC_CMD="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    ) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
        set ISCC_CMD="C:\Program Files\Inno Setup 6\ISCC.exe"
    ) else (
        set ISCC_CMD=none
    )
)

if not "%ISCC_CMD%"=="none" (
    echo --> Building Inno Setup Installer...
    %ISCC_CMD% packaging\windows\installer.iss
    if exist "dist\windows_installer\JustTalk-Setup-1.0.0.exe" (
        copy /y "dist\windows_installer\JustTalk-Setup-1.0.0.exe" "packaging\windows\JustTalk-Setup-1.0.0.exe" >nul
        echo === Windows Installer created at dist\windows_installer\ and packaging\windows\ ===
    )
) else (
    echo [WARNING] 'iscc' (Inno Setup Compiler) not found in PATH or standard Program Files.
    echo Standalone executable is available at: dist\JustTalk\JustTalk.exe
    echo To build installer: install Inno Setup 6 and run 'iscc packaging\windows\installer.iss'
)

echo === Build Complete! ===
