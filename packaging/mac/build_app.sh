#!/usr/bin/env bash
# Automated build script for JustTalk macOS Application (.app & .dmg)
set -e

echo "=== Building Just Talk for macOS ==="
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"
export PATH="$HOME/.local/bin:$PROJECT_DIR/.venv/bin:$PATH"

# 1. Generate icon assets if not present
echo "--> Generating icons..."
if command -v uv >/dev/null 2>&1; then
    uv run python just_talk/assets/generate_icons.py
    echo "--> Compiling application with PyInstaller via uv..."
    uv run pyinstaller --clean -y packaging/justtalk.spec
else
    python just_talk/assets/generate_icons.py
    echo "--> Compiling application with PyInstaller..."
    pyinstaller --clean -y packaging/justtalk.spec
fi

APP_PATH="dist/JustTalk.app"

if [ -d "$APP_PATH" ]; then
    echo "--> Verifying application bundle..."
    # Ensure Info.plist is in place
    cp packaging/mac/Info.plist "$APP_PATH/Contents/Info.plist"
    # Ensure AppIcon.icns is in Resources
    mkdir -p "$APP_PATH/Contents/Resources"
    cp just_talk/assets/icon.icns "$APP_PATH/Contents/Resources/AppIcon.icns"

    # Crucial: Re-sign the bundle after copying Info.plist and AppIcon.icns so the signature seal is valid!
    SIGN_IDENTITY="-"
    if security find-identity -v -p codesigning | grep -q "JustTalk Development"; then
        SIGN_IDENTITY="JustTalk Development"
        echo "--> Signing with stable certificate 'JustTalk Development' (persists TCC permissions across rebuilds)..."
    else
        echo "--> Signing application bundle with ad-hoc identifier com.justtalk.desktop..."
    fi
    codesign --force --deep --sign "$SIGN_IDENTITY" --entitlements packaging/mac/entitlements.plist --identifier "com.justtalk.desktop" "$APP_PATH"

    echo "--> JustTalk.app successfully built and signed at: $APP_PATH"

    # 3. Create DMG with drag-to-Applications link
    DMG_PATH="dist/JustTalk-macOS.dmg"
    STAGING_DIR="dist/dmg_staging"
    rm -rf "$STAGING_DIR" "$DMG_PATH"
    mkdir -p "$STAGING_DIR"
    cp -R "$APP_PATH" "$STAGING_DIR/"
    ln -s /Applications "$STAGING_DIR/Applications"

    echo "--> Packaging into $DMG_PATH..."
    hdiutil create -volname "Just Talk" -srcfolder "$STAGING_DIR" -ov -format UDZO "$DMG_PATH"
    rm -rf "$STAGING_DIR"

    # Copy DMG to packaging/mac folder as requested
    PKG_MAC_DMG="packaging/mac/JustTalk-macOS.dmg"
    cp "$DMG_PATH" "$PKG_MAC_DMG"
    echo "--> Copied DMG to: $PKG_MAC_DMG"

    echo "=== Build Complete! Installer ready at $DMG_PATH and $PKG_MAC_DMG ==="
else
    echo "Error: $APP_PATH was not created!"
    exit 1
fi
