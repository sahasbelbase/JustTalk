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
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "pause": '<path d="M9 6v12M15 6v12"/>',
    "play": '<path d="M8 5.5v13l10-6.5z"/>',
    "skip": '<path d="m6 6 7 6-7 6M17 6v12"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h.01M18 14h.01M10 14h4"/>',
    "memory": '<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9h6v6H9zM9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/>',
    "sparkles": '<path d="m12 3 1.9 4.8L18.7 9.7l-3.8 3.7.9 5.3-4.8-2.5-4.8 2.5.9-5.3-3.8-3.7 4.8-1.9z"/>',
    "language": '<circle cx="12" cy="12" r="9"/><path d="M3.6 9h16.8M3.6 15h16.8M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "delete": '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M10 11v6M14 11v6"/>',
    "soundwave": '<path d="M2 10v4M6 7v10M10 4v16M14 8v8M18 5v14M22 10v4"/>',
    "neurology": '<path d="M12 2a4 4 0 0 0-4 4c0 1.2.5 2.3 1.3 3A4 4 0 0 0 6 12a4 4 0 0 0 2 3.5 4 4 0 0 0 4 6.5 4 4 0 0 0 4-6.5 4 4 0 0 0 2-3.5 4 4 0 0 0-3.3-3A4 4 0 0 0 12 2z"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "volume": '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>',
    "arrow-down": '<line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>',
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
