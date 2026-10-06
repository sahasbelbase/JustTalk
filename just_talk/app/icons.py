"""Monochrome line icons (24px grid, 1.5px stroke) rendered from inline SVG.

One consistent icon set instead of emoji: emoji render differently per OS, can't be
tinted to the theme, and read as decoration rather than UI.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Neutral grey that reads on both light and dark surfaces, and the brand accent.
ICON_MUTED = "#8E8E93"
ICON_ACCENT = "#6C8EEF"

_PATHS = {
    "home": '<path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z"/>',
    "history": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4.5l3 1.75"/>',
    "conventions": '<path d="M5 6h14M5 10.5h9M5 15h14M5 19.5h9"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/>',
    "mic": '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M6 11.5a6 6 0 0 0 12 0M12 17.5V20.5"/>',
    "stop": '<rect x="7" y="7" width="10" height="10" rx="1.5"/>',
    "chevron-down": '<path d="m7 10 5 5 5-5"/>',
    "chevron-right": '<path d="m10 7 5 5-5 5"/>',
    "download": '<path d="M12 4v11m-4.5-4.5L12 15l4.5-4.5M5 19.5h14"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/>',
    "external": '<path d="M9 5H5.5A1.5 1.5 0 0 0 4 6.5v12A1.5 1.5 0 0 0 5.5 20h12a1.5 1.5 0 0 0 1.5-1.5V15M14 4h6v6M20 4l-9 9"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="m7 7 10 10M17 7 7 17"/>',
}


@lru_cache(maxsize=128)
def pixmap(name: str, color: str = ICON_MUTED, size: int = 18) -> QPixmap:
    """Render icon ``name`` in ``color`` at ``size`` logical pixels (crisp on Retina)."""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
        f"{_PATHS[name]}</svg>"
    )
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app is not None else 2.0
    dpr = max(dpr, 2.0)
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, pm.width(), pm.height()))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = ICON_MUTED, active_color: str = ICON_ACCENT, size: int = 18) -> QIcon:
    """Icon that switches to ``active_color`` when its button is checked."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(name, active_color, size), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(pixmap(name, active_color, size), QIcon.Mode.Active, QIcon.State.On)
    return ic
