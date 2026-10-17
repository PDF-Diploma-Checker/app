"""Small stroke icon set drawn from inline SVG, so the UI needs no extra asset files."""

import os
import tempfile

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "search": '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
    "download": '<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>',
    "chevron-down": '<polyline points="6 9 12 15 18 9"/>',
    "arrow-left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<polyline points="5 12.5 10 17.5 19 7.5"/>',
    "alert": '<path d="M12 6v8M12 18.2v.1"/>',
    "circle": '<circle cx="12" cy="12" r="7"/>',
    "settings": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/>'
                '<circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "flag": '<path d="M4 22V4M4 4h13l-2 4 2 4H4"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
            '<polyline points="14 3 14 8 19 8"/>',
    "json": '<path d="M8 3H7a2 2 0 0 0-2 2v4a2 2 0 0 1-2 2 2 2 0 0 1 2 2v4a2 2 0 0 0 2 2h1'
            'M16 3h1a2 2 0 0 1 2 2v4a2 2 0 0 0 2 2 2 2 0 0 0-2 2v4a2 2 0 0 1-2 2h-1"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    "sort": '<path d="M7 4v16M3 16l4 4 4-4M17 20V4M13 8l4-4 4 4"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "logo": '<polyline points="5 12.5 10 17.5 19 7.5"/>',
}

_FILLED = {
    "more": '<circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/>',
}


def _svg(name, color, stroke):
    if name in _FILLED:
        body = f'<g fill="{color}" stroke="none">{_FILLED[name]}</g>'
    else:
        body = _PATHS[name]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )


def _dpr():
    screen = QGuiApplication.primaryScreen()
    return max(1.0, screen.devicePixelRatio()) if screen else 1.0


def pixmap(name, color="#6B7280", size=16, stroke=2.0):
    """Render the named icon to a crisp pixmap of `size` logical pixels."""
    ratio = _dpr()
    px = int(round(size * ratio))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke).encode("utf-8")))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name, color="#6B7280", size=16, stroke=2.0, disabled="#C4C9D2"):
    """QIcon with a normal and a greyed-out disabled state."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size, stroke), QIcon.Normal)
    ic.addPixmap(pixmap(name, disabled, size, stroke), QIcon.Disabled)
    return ic


def png_path(name, color, size=12, stroke=3.0):
    """Write the icon to a cached PNG and return its path, for QSS `image: url(...)` rules."""
    folder = os.path.join(tempfile.gettempdir(), "DiplomaChecker_icons")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}_{color.lstrip('#')}_{size}.png")
    if not os.path.exists(path):
        pixmap(name, color, size, stroke).save(path, "PNG")
    return path.replace("\\", "/")


def svg_file_pixmap(path, height=32):
    """Render an SVG file at the given logical height (keeps its aspect ratio). None if unreadable."""
    renderer = QSvgRenderer(path)
    if not renderer.isValid():
        return None
    default = renderer.defaultSize()
    ratio_wh = (default.width() / default.height()) if default.height() > 0 else 1.0
    ratio = _dpr()
    h_px = int(round(height * ratio))
    w_px = max(1, int(round(h_px * ratio_wh)))
    pm = QPixmap(w_px, h_px)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, w_px, h_px))
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm