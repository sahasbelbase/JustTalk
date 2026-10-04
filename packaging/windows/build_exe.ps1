# =========================================================================
# Automated Windows PowerShell Build Script for Just Talk
# Builds standalone executable and high-resolution setup installer
# =========================================================================
$ErrorActionPreference = "Continue"

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
if ($LASTEXITCODE -ne 0) {
    Write-Error "Dependency installation failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
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
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller compilation failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

if (-not (Test-Path "dist\JustTalk\JustTalk.exe")) {
    Write-Error "PyInstaller failed to build dist\JustTalk\JustTalk.exe"
    exit 1
}

Write-Host "--> Standalone executable built: dist\JustTalk\JustTalk.exe" -ForegroundColor Green

# 4. Inno Setup Compiler
$isccCmd = Get-Command "iscc" -ErrorAction SilentlyContinue
$isccPath = $null
if ($isccCmd) {
    $isccPath = $isccCmd.Source
} else {
    $searchCandidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "C:\ProgramData\chocolatey\bin\iscc.exe",
        "C:\ProgramData\chocolatey\lib\innosetup\tools\ISCC.exe"
    )
    foreach ($candidate in $searchCandidates) {
        if (Test-Path $candidate) {
            $isccPath = $candidate
            break
        }
    }
}

if (-not $isccPath) {
    Write-Error "Inno Setup compiler (iscc.exe) was not found in PATH or standard installation locations!"
    exit 1
}

Write-Host "--> Using Inno Setup compiler: $isccPath" -ForegroundColor Green
Write-Host "--> Compiling modern branded installer with Inno Setup..." -ForegroundColor Yellow
& "$isccPath" "packaging\windows\installer.iss"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup compilation failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$InstallerExe = Get-ChildItem -Path "dist\windows_installer\*.exe" | Select-Object -Last 1
if ($InstallerExe) {
    # Ensure packaging/windows and dist root both have the standardized latest installer
    Copy-Item $InstallerExe.FullName -Destination "dist\JustTalk-Windows.exe" -Force
    Copy-Item $InstallerExe.FullName -Destination "dist\windows_installer\JustTalk-Windows.exe" -Force
    Copy-Item $InstallerExe.FullName -Destination "packaging\windows\JustTalk-Windows.exe" -Force
    # Backwards compatibility copies
    Copy-Item $InstallerExe.FullName -Destination "dist\JustTalk-Setup.exe" -Force
    Copy-Item $InstallerExe.FullName -Destination "packaging\windows\JustTalk-Setup-1.0.0.exe" -Force
    Write-Host "=== Windows Installer ready at: $($InstallerExe.FullName) ===" -ForegroundColor Green
} else {
    Write-Error "Inno Setup completed but no installer executable was found in dist\windows_installer\"
    exit 1
}

Write-Host "=== Windows Build Workflow Finished Successfully! ===" -ForegroundColor Cyan
