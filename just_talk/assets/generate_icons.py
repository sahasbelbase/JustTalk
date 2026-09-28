"""Generate high-resolution application icons for macOS (.icns) and Windows (.ico)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image


def generate_all_icons(master_path: Path | None = None) -> None:
    """Generate macOS .icns, Windows .ico, and PNG icon assets from master image."""
    assets_dir = Path(__file__).resolve().parent
    assets_dir.mkdir(parents=True, exist_ok=True)

    if master_path is None or not master_path.exists():
        master_path = assets_dir / "icon_master.png"

    if not master_path.exists():
        raise FileNotFoundError(f"Master icon image not found at {master_path}")

    master = Image.open(master_path).convert("RGBA")

    # 1. Standard 512x512 PNG
    png_path = assets_dir / "icon.png"
    icon_512 = master.resize((512, 512), Image.Resampling.LANCZOS)
    icon_512.save(str(png_path), format="PNG")
    print(f"Generated {png_path} (512x512)")

    # 2. Multi-resolution Windows ICO (16, 24, 32, 48, 64, 128, 256)
    ico_path = assets_dir / "icon.ico"
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon_512.save(str(ico_path), format="ICO", sizes=ico_sizes)
    print(f"Generated {ico_path} with standard Windows sizes")

    # 3. macOS ICNS & Iconset
    icns_path = assets_dir / "icon.icns"
    iconset_dir = assets_dir / "icon.iconset"
    iconset_dir.mkdir(exist_ok=True)

    specs = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (64, "icon_64x64.png"),
        (128, "icon_64x64@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    for sz, name in specs:
        resized = master.resize((sz, sz), Image.Resampling.LANCZOS)
        resized.save(iconset_dir / name, format="PNG")

    if sys.platform == "darwin":
        try:
            subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)], check=True)
            print(f"Generated native {icns_path} via iconutil")
        except Exception as e:
            print(f"iconutil fallback: {e}")
            icon_512.save(str(icns_path), format="ICNS")
    else:
        try:
            icon_512.save(str(icns_path), format="ICNS")
            print(f"Generated {icns_path}")
        except Exception:
            pass


def main():
    generate_all_icons()


if __name__ == "__main__":
    main()
