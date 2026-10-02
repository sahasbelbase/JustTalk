# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for packaging Just Talk into a standalone binary / macOS .app bundle."""

import sys
from pathlib import Path

block_cipher = None
project_root = Path.cwd()

# Pick platform icon
if sys.platform == "darwin":
    app_icon = str(project_root / "just_talk" / "assets" / "icon.icns")
else:
    app_icon = str(project_root / "just_talk" / "assets" / "icon.ico")

from PyInstaller.utils.hooks import collect_data_files

datas = [
    (str(project_root / "just_talk" / "assets"), "just_talk/assets"),
]
datas += collect_data_files("faster_whisper")

hidden_imports = [
    "ctranslate2",
    "faster_whisper",
    "sounddevice",
    "pynput",
    "pynput.keyboard",
    "pynput.keyboard._darwin",
    "pynput.keyboard._win32",
    "keyring",
    "keyring.backends",
    "keyring.backends.macOS",
    "keyring.backends.Windows",
    "httpx",
    "huggingface_hub",
    "google_genai",
    "scipy",
    "scipy.signal",
    "onnxruntime",
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
]

if sys.platform == "darwin":
    hidden_imports += [
        "objc",
        "Foundation",
        "AppKit",
        "Quartz",
        "AVFoundation",
    ]

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "notebook", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JustTalk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed GUI application (no terminal popup)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=str(project_root / "packaging" / "mac" / "entitlements.plist"),
    icon=app_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="JustTalk",
)

if sys.platform == "darwin":
    info_plist_path = str(project_root / "packaging" / "mac" / "Info.plist")
    app = BUNDLE(
        coll,
        name="JustTalk.app",
        icon=app_icon,
        bundle_identifier="com.justtalk.desktop",
        info_plist=info_plist_path,
    )
