"""Generate modern high-resolution branding graphics for Windows Installer (Inno Setup / NSIS).

Produces:
  - packaging/windows/wizard_sidebar.bmp (328x628 24-bit RGB) for the welcome/finish pages.
  - packaging/windows/wizard_small.bmp (110x110 24-bit RGB) for the header pages.
"""

from __future__ import annotations

import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter


def create_wizard_sidebar(output_path: Path, assets_dir: Path) -> None:
    width = 328
    height = 628

    # 1. Base Dark Gradient Background (#0B0D13 to #161822)
    img = Image.new("RGB", (width, height), (11, 13, 19))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / float(height)
        r = int(11 + (22 - 11) * ratio)
        g = int(13 + (24 - 13) * ratio)
        b = int(19 + (34 - 19) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 2. Cyan & Violet Radial Glows for high-tech aesthetic
    glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)

    # Cyan aura behind pill
    glow_draw.ellipse(
        [(width // 2 - 120, 220 - 70), (width // 2 + 120, 220 + 70)],
        fill=(0, 210, 255, 38),
    )
    # Violet aura near bottom
    glow_draw.ellipse(
        [(width // 2 - 100, 360 - 60), (width // 2 + 100, 360 + 60)],
        fill=(138, 43, 226, 32),
    )
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=35))
    img.paste(Image.alpha_composite(Image.new("RGBA", (width, height), (0, 0, 0, 0)), glow_layer), (0, 0), glow_layer)

    # 3. Draw App Icon badge near top
    icon_master = assets_dir / "icon.png"
    if icon_master.exists():
        app_icon = Image.open(icon_master).convert("RGBA")
        app_icon = app_icon.resize((72, 72), Image.Resampling.LANCZOS)
        img.paste(app_icon, (width // 2 - 36, 68), app_icon)

    # 4. Floating Pill Preview in center
    pill_w = 230
    pill_h = 52
    pill_x = (width - pill_w) // 2
    pill_y = 230

    # Pill Shadow
    pill_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(pill_layer)
    p_draw.rounded_rectangle(
        [(pill_x - 3, pill_y - 3), (pill_x + pill_w + 3, pill_y + pill_h + 3)],
        radius=pill_h // 2 + 3,
        fill=(0, 0, 0, 90),
    )
    pill_layer = pill_layer.filter(ImageFilter.GaussianBlur(radius=6))
    img.paste(Image.alpha_composite(Image.new("RGBA", (width, height), (0, 0, 0, 0)), pill_layer), (0, 0), pill_layer)

    # Main Pill Body (Obsidian Dark with hairline border)
    p_main = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pm_draw = ImageDraw.Draw(p_main)
    pm_draw.rounded_rectangle(
        [(pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h)],
        radius=pill_h // 2,
        fill=(11, 12, 16, 245),
        outline=(255, 255, 255, 50),
        width=1,
    )

    # Cancel Button [✕] (Dark Gray Circle)
    cx, cy = pill_x + 26, pill_y + pill_h // 2
    pm_draw.ellipse([(cx - 13, cy - 13), (cx + 13, cy + 13)], fill=(52, 54, 60, 240))
    cr = 4
    pm_draw.line([(cx - cr, cy - cr), (cx + cr, cy + cr)], fill=(255, 255, 255, 240), width=2)
    pm_draw.line([(cx - cr, cy + cr), (cx + cr, cy - cr)], fill=(255, 255, 255, 240), width=2)

    # Confirm Button [✓] (White Circle)
    kx, ky = pill_x + pill_w - 26, pill_y + pill_h // 2
    pm_draw.ellipse([(kx - 13, ky - 13), (kx + 13, ky + 13)], fill=(255, 255, 255, 255))
    pm_draw.line([(kx - 4, ky + 1), (kx - 1, ky + 4)], fill=(11, 12, 16, 255), width=2)
    pm_draw.line([(kx - 1, ky + 4), (kx + 5, ky - 3)], fill=(11, 12, 16, 255), width=2)

    # 9 Sound Waveform Bars (symmetrical rounded bars)
    bar_weights = [0.30, 0.45, 0.65, 0.85, 1.0, 0.85, 0.65, 0.45, 0.30]
    bar_w = 3
    bar_gap = 4
    total_w = len(bar_weights) * bar_w + (len(bar_weights) - 1) * bar_gap
    start_bx = pill_x + (pill_w - total_w) // 2
    center_by = pill_y + pill_h // 2

    for i, w_val in enumerate(bar_weights):
        bh = max(6, int(w_val * 26))
        bx = start_bx + i * (bar_w + bar_gap)
        by1 = center_by - bh // 2
        by2 = center_by + bh // 2
        pm_draw.rounded_rectangle([(bx, by1), (bx + bar_w, by2)], radius=1, fill=(255, 255, 255, 245))

    img.paste(p_main, (0, 0), p_main)

    # 5. Typography
    fonts_dir = assets_dir / "fonts"
    bold_font_path = fonts_dir / "Lato-Bold.ttf"
    reg_font_path = fonts_dir / "Lato-Regular.ttf"

    try:
        title_font = ImageFont.truetype(str(bold_font_path), 24)
        subtitle_font = ImageFont.truetype(str(reg_font_path), 13)
        version_font = ImageFont.truetype(str(reg_font_path), 11)
    except Exception:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        version_font = ImageFont.load_default()

    draw = ImageDraw.Draw(img)

    # App Title
    title = "Just Talk"
    tb = draw.textbbox((0, 0), title, font=title_font)
    tw = tb[2] - tb[0]
    draw.text(((width - tw) // 2, 450), title, font=title_font, fill=(245, 245, 247))

    # Subtitle
    sub = "Instant AI Voice Dictation"
    sb = draw.textbbox((0, 0), sub, font=subtitle_font)
    sw = sb[2] - sb[0]
    draw.text(((width - sw) // 2, 485), sub, font=subtitle_font, fill=(160, 165, 178))

    # Feature tags
    tag = "Fast • Private • Multilingual"
    tb2 = draw.textbbox((0, 0), tag, font=version_font)
    tw2 = tb2[2] - tb2[0]
    draw.text(((width - tw2) // 2, 515), tag, font=version_font, fill=(100, 105, 120))

    # Version note
    ver = "v2.3.0 Desktop for Windows"
    vb = draw.textbbox((0, 0), ver, font=version_font)
    vw = vb[2] - vb[0]
    draw.text(((width - vw) // 2, 580), ver, font=version_font, fill=(75, 80, 95))

    # Save as 24-bit BMP
    img.save(str(output_path), format="BMP")
    print(f"Generated {output_path} ({width}x{height} BMP)")


def create_wizard_small(output_path: Path, assets_dir: Path) -> None:
    width = 110
    height = 110

    # Dark background matching header (#13151C)
    img = Image.new("RGB", (width, height), (19, 21, 28))
    icon_master = assets_dir / "icon.png"

    if icon_master.exists():
        app_icon = Image.open(icon_master).convert("RGBA")
        app_icon = app_icon.resize((84, 84), Image.Resampling.LANCZOS)
        # Center in 110x110
        offset_x = (width - 84) // 2
        offset_y = (height - 84) // 2
        img.paste(app_icon, (offset_x, offset_y), app_icon)

    img.save(str(output_path), format="BMP")
    print(f"Generated {output_path} ({width}x{height} BMP)")


def main():
    root = Path(__file__).resolve().parent
    assets_dir = root.parent.parent / "just_talk" / "assets"
    sidebar_bmp = root / "wizard_sidebar.bmp"
    small_bmp = root / "wizard_small.bmp"

    create_wizard_sidebar(sidebar_bmp, assets_dir)
    create_wizard_small(small_bmp, assets_dir)


if __name__ == "__main__":
    main()
