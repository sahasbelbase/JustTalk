#!/usr/bin/env bash
# ==============================================================================
# Just Talk — macOS Environment Setup & Troubleshooting Script
# Handles Xcode Command Line Tools, Gatekeeper Quarantine, and TCC Permissions
# ==============================================================================

set -e

echo "=== Just Talk macOS Setup & Verification ==="

# 1. Check & Install Xcode Command Line Tools if missing
echo "--> Checking Xcode Command Line Tools..."
if xcode-select -p >/dev/null 2>&1; then
    echo "    ✓ Xcode Command Line Tools already installed at: $(xcode-select -p)"
else
    echo "    ! Xcode Command Line Tools not detected. Launching installer..."
    xcode-select --install
    echo "    Please complete the Xcode dialog installation prompt before continuing."
fi

# 2. Check /Applications/JustTalk.app
APP_PATH="/Applications/JustTalk.app"
if [ -d "$APP_PATH" ]; then
    echo "--> Verifying /Applications/JustTalk.app..."

    # Strip macOS Gatekeeper Quarantine flag
    echo "--> Removing Gatekeeper quarantine attribute (allows running without 'Unidentified Developer' alert)..."
    xattr -cr "$APP_PATH"
    echo "    ✓ Quarantine attribute cleared."

    # Verify Code Signature & Entitlements
    echo "--> Verifying application code signature..."
    codesign -v --deep "$APP_PATH" 2>&1 || {
        echo "    ! Signature check returned warning, re-signing bundle ad-hoc with audio entitlements..."
        codesign --force --deep --sign "-" --entitlements "packaging/mac/entitlements.plist" --identifier "com.justtalk.desktop" "$APP_PATH"
    }
    echo "    ✓ Code signature verified."

    # Verify Entitlements include microphone
    echo "--> Checking microphone entitlement..."
    if codesign -d --entitlements :- "$APP_PATH" 2>&1 | grep -q "com.apple.security.device.audio-input"; then
        echo "    ✓ Microphone entitlement (com.apple.security.device.audio-input) is active."
    else
        echo "    ! Re-applying microphone entitlement..."
        codesign --force --deep --sign "-" --entitlements "packaging/mac/entitlements.plist" --identifier "com.justtalk.desktop" "$APP_PATH"
    fi
else
    echo "--> Note: /Applications/JustTalk.app is not yet installed."
    echo "    If you built the app, copy it from dist/JustTalk.app or mount dist/JustTalk-macOS.dmg."
fi

# 3. macOS Privacy & Security Permissions Helper
echo ""
echo "=== Required macOS Permissions ==="
echo "Just Talk requires two standard macOS permissions to function across all applications:"
echo "  1. Microphone: To capture and transcribe your spoken voice."
echo "  2. Accessibility: To detect the global Fn/Option shortcut, locate your text caret, and paste formatted text."
echo ""
echo "To check or grant permissions manually:"
echo "  Open System Settings -> Privacy & Security:"
echo "    • Microphone -> Enable 'Just Talk'"
echo "    • Accessibility -> Enable 'Just Talk'"
echo "    • Input Monitoring -> Enable 'Just Talk' (if prompted)"
echo ""
echo "If macOS ever blocks microphone or hotkeys after an update, reset with:"
echo "  tccutil reset Microphone com.justtalk.desktop"
echo "  tccutil reset Accessibility com.justtalk.desktop"
echo ""
echo "Setup complete! You can launch Just Talk with: open /Applications/JustTalk.app"
