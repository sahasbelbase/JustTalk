@echo off
REM =========================================================================
REM Just Talk — One-Click Windows Launcher (Zero Installation Required)
REM =========================================================================
title Just Talk
cd /d "%~dp0"

echo ===================================================
echo               Launching Just Talk...
echo ===================================================

REM Check if uv is in PATH
where uv >nul 2>nul
if %ERRORLEVEL% neq 0 (
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    ) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
        set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
    ) else (
        echo [1/2] Setting up lightweight runner...
        powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
    )
)

echo [2/2] Starting voice keyboard...
uv run python -m just_talk.app.main
