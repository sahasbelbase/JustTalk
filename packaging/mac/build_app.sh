#!/usr/bin/env bash
# Automated build script for JustTalk macOS Application (.app & .dmg)
set -e

echo "=== Building Just Talk for macOS ==="
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

# 1. Generate icon assets if not present
echo "--> Generating icons..."
uv run python just_talk/assets/generate_icons.py

# 2. Compile standalone bundle via PyInstaller
echo "--> Compiling application with PyInstaller..."
uv run pyinstaller --clean -y packaging/justtalk.spec

APP_PATH="dist/JustTalk.app"

if [ -d "$APP_PATH" ]; then
    echo "--> Verifying application bundle..."
    # Ensure Info.plist is in place
    cp packaging/mac/Info.plist "$APP_PATH/Contents/Info.plist"
    # Ensure AppIcon.icns is in Resources
    mkdir -p "$APP_PATH/Contents/Resources"
    cp just_talk/assets/icon.icns "$APP_PATH/Contents/Resources/AppIcon.icns"

    # Crucial: Re-sign the bundle after copying Info.plist and AppIcon.icns so the signature seal is valid!
    echo "--> Signing application bundle with stable identifier com.justtalk.desktop..."
    codesign --force --deep --sign - --identifier "com.justtalk.desktop" "$APP_PATH"

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
    echo "=== Build Complete! Installer ready at $DMG_PATH ==="
else
    echo "Error: $APP_PATH was not created!"
    exit 1
fi
