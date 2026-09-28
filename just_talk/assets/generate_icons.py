"""Generate high-resolution application icons for macOS (.icns) and Windows (.ico)."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def create_base_icon(size: int = 512) -> Image.Image:
    """Render a crisp, modern vector-style microphone/soundwave icon."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # 1. Background rounded rectangle with modern dark indigo gradient
    pad = int(size * 0.08)
    rect = [pad, pad, size - pad, size - pad]
    radius = int(size * 0.22)

    # Draw rounded rectangle
    draw.rounded_rectangle(rect, radius=radius, fill=(24, 24, 32, 255), outline=(56, 56, 75, 255), width=int(size * 0.015))

    # Inner subtle glow
    inner_pad = pad + int(size * 0.02)
    inner_rect = [inner_pad, inner_pad, size - inner_pad, size - inner_pad]
    draw.rounded_rectangle(inner_rect, radius=int(radius * 0.9), outline=(75, 85, 110, 80), width=int(size * 0.01))

    # 2. Draw modern stylized microphone and audio wave bars in vibrant cyan/electric blue
    center_x = size // 2
    center_y = int(size * 0.46)

    # Mic Capsule
    cap_w = int(size * 0.16)
    cap_h = int(size * 0.30)
    cap_left = center_x - cap_w // 2
    cap_top = center_y - cap_h // 2
    cap_rect = [cap_left, cap_top, cap_left + cap_w, cap_top + cap_h]
    draw.rounded_rectangle(cap_rect, radius=cap_w // 2, fill=(59, 130, 246, 255))

    # Mic Capsule Highlight (Glass sheen)
    sheen_rect = [cap_left + 4, cap_top + 4, cap_left + cap_w - 4, cap_top + cap_h // 2]
    draw.rounded_rectangle(sheen_rect, radius=cap_w // 2, fill=(96, 165, 250, 220))

    # Mic U-Shaped Cradle
    cradle_w = int(size * 0.28)
    cradle_h = int(size * 0.28)
    cradle_rect = [center_x - cradle_w // 2, center_y - int(size * 0.04), center_x + cradle_w // 2, center_y + cradle_h - int(size * 0.04)]
    draw.arc(cradle_rect, start=0, end=180, fill=(244, 244, 245, 255), width=int(size * 0.035))

    # Mic Stand Vertical Stem
    stem_top = center_y + cradle_h // 2 - int(size * 0.04)
    stem_bottom = stem_top + int(size * 0.14)
    draw.line([(center_x, stem_top), (center_x, stem_bottom)], fill=(244, 244, 245, 255), width=int(size * 0.035))

    # Mic Base Horizontal Line
    base_w = int(size * 0.22)
    draw.line([(center_x - base_w // 2, stem_bottom), (center_x + base_w // 2, stem_bottom)], fill=(244, 244, 245, 255), width=int(size * 0.035))

    # 3. Flanking Sound Waves (left & right)
    wave_color = (6, 182, 212, 240)  # Cyan
    bar_width = int(size * 0.025)

    # Left bars
    draw.rounded_rectangle([center_x - int(size * 0.24) - bar_width, center_y - int(size * 0.10), center_x - int(size * 0.24), center_y + int(size * 0.10)], radius=bar_width//2, fill=wave_color)
    draw.rounded_rectangle([center_x - int(size * 0.32) - bar_width, center_y - int(size * 0.05), center_x - int(size * 0.32), center_y + int(size * 0.05)], radius=bar_width//2, fill=(wave_color[0], wave_color[1], wave_color[2], 180))

    # Right bars
    draw.rounded_rectangle([center_x + int(size * 0.24), center_y - int(size * 0.10), center_x + int(size * 0.24) + bar_width, center_y + int(size * 0.10)], radius=bar_width//2, fill=wave_color)
    draw.rounded_rectangle([center_x + int(size * 0.32), center_y - int(size * 0.05), center_x + int(size * 0.32) + bar_width, center_y + int(size * 0.05)], radius=bar_width//2, fill=(wave_color[0], wave_color[1], wave_color[2], 180))

    return image


def main():
    assets_dir = Path(__file__).resolve().parent
    assets_dir.mkdir(parents=True, exist_ok=True)

    base_icon = create_base_icon(512)

    # 1. Save standard PNG
    png_path = assets_dir / "icon.png"
    base_icon.save(str(png_path), format="PNG")
    print(f"Generated {png_path}")

    # 2. Save multi-resolution Windows ICO (16, 24, 32, 48, 64, 128, 256)
    ico_path = assets_dir / "icon.ico"
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base_icon.save(str(ico_path), format="ICO", sizes=ico_sizes)
    print(f"Generated {ico_path}")

    # 3. Save macOS ICNS
    icns_path = assets_dir / "icon.icns"
    if sys.platform == "darwin":
        # On macOS, generate iconset using sips and iconutil for 100% native Apple compliance
        iconset_dir = assets_dir / "icon.iconset"
        iconset_dir.mkdir(exist_ok=True)
        sizes = [16, 32, 64, 128, 256, 512]
        for s in sizes:
            resized = base_icon.resize((s, s), Image.Resampling.LANCZOS)
            resized.save(str(iconset_dir / f"icon_{s}x{s}.png"))
            if s * 2 <= 1024:
                resized_2x = base_icon.resize((s * 2, s * 2), Image.Resampling.LANCZOS)
                resized_2x.save(str(iconset_dir / f"icon_{s}x{s}@2x.png"))

        try:
            subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)], check=True)
            print(f"Generated native {icns_path} via iconutil")
        except Exception as e:
            print(f"iconutil fallback: {e}")
            base_icon.save(str(icns_path), format="ICNS")
    else:
        try:
            base_icon.save(str(icns_path), format="ICNS")
            print(f"Generated {icns_path}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
