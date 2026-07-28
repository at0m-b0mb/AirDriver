"""Vector icons drawn with QPainter — deliberately *not* emoji.

A minimal Kali/Parrot install has no emoji font. Any 🔧/📚/🩺/⬇ in a button
renders as an empty tofu box (or nothing at all), which is exactly how buttons
end up looking broken on the machines this tool is built for. Everything here is
drawn from paths instead, so it looks identical on a bare box and a full desktop.

Usage:

    from . import icons
    btn.setIcon(icons.icon("refresh"))
    btn.setIconSize(icons.SIZE)

Icons are drawn on a 100x100 logical grid and scaled, so they stay crisp at any
size and on HiDPI screens.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme as T

SIZE = QSize(16, 16)
_CACHE: dict[tuple, QIcon] = {}


# --------------------------------------------------------------------------- #
# drawing helpers (all on a 100x100 grid)                                     #
# --------------------------------------------------------------------------- #
def _stroke(p: QPainter, colour: QColor, width: float = 9.0) -> None:
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)


def _poly(p: QPainter, pts: list[tuple[float, float]], close: bool = False) -> None:
    path = QPainterPath(QPointF(*pts[0]))
    for xy in pts[1:]:
        path.lineTo(QPointF(*xy))
    if close:
        path.closeSubpath()
    p.drawPath(path)


# --------------------------------------------------------------------------- #
# the icons                                                                   #
# --------------------------------------------------------------------------- #
def _refresh(p: QPainter, c: QColor) -> None:
    """Circular arrow — rescan."""
    _stroke(p, c, 10)
    p.drawArc(QRectF(18, 18, 64, 64), 40 * 16, 280 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawPath(_tri([(60, 6), (94, 16), (72, 42)]))   # arrowhead on the open end


def _tri(pts):
    path = QPainterPath(QPointF(*pts[0]))
    for xy in pts[1:]:
        path.lineTo(QPointF(*xy))
    path.closeSubpath()
    return path


def _download(p: QPainter, c: QColor) -> None:
    """Arrow into a tray — install."""
    _stroke(p, c, 10)
    _poly(p, [(50, 10), (50, 58)])
    _poly(p, [(20, 82), (80, 82)])
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawPath(_tri([(28, 46), (72, 46), (50, 72)]))


def _check(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 12)
    _poly(p, [(16, 52), (40, 76), (84, 24)])


def _trash(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 9)
    _poly(p, [(16, 26), (84, 26)])
    _poly(p, [(40, 16), (60, 16)])
    _poly(p, [(26, 26), (30, 88), (70, 88), (74, 26)])
    _poly(p, [(42, 40), (44, 74)])
    _poly(p, [(58, 40), (56, 74)])


def _wrench(p: QPainter, c: QColor) -> None:
    """Spanner — driver management."""
    _stroke(p, c, 11)
    path = QPainterPath()
    path.moveTo(72, 14)
    path.arcTo(QRectF(46, 10, 44, 44), 60, 250)   # open jaw
    p.drawPath(path)
    _poly(p, [(58, 46), (22, 84)])


def _book(p: QPainter, c: QColor) -> None:
    """Open book — the chipset catalogue."""
    _stroke(p, c, 9)
    _poly(p, [(50, 28), (50, 84)])
    path = QPainterPath(QPointF(50, 28))
    path.cubicTo(38, 16, 24, 16, 12, 20)
    path.lineTo(12, 76)
    path.cubicTo(26, 72, 38, 74, 50, 84)
    p.drawPath(path)
    path2 = QPainterPath(QPointF(50, 28))
    path2.cubicTo(62, 16, 76, 16, 88, 20)
    path2.lineTo(88, 76)
    path2.cubicTo(74, 72, 62, 74, 50, 84)
    p.drawPath(path2)


def _pulse(p: QPainter, c: QColor) -> None:
    """Heartbeat line — diagnose."""
    _stroke(p, c, 10)
    _poly(p, [(8, 52), (28, 52), (40, 20), (56, 82), (68, 52), (92, 52)])


def _clipboard(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 9)
    p.drawRoundedRect(QRectF(22, 20, 56, 68), 8, 8)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(38, 10, 24, 18), 4, 4)
    p.setBrush(Qt.NoBrush)
    _poly(p, [(36, 48), (64, 48)])
    _poly(p, [(36, 64), (58, 64)])


def _document(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 9)
    _poly(p, [(24, 10), (60, 10), (78, 30), (78, 90), (24, 90)], close=True)
    _poly(p, [(58, 10), (58, 32), (78, 32)])
    _poly(p, [(36, 52), (66, 52)])
    _poly(p, [(36, 68), (66, 68)])


def _question(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 9)
    p.drawEllipse(QRectF(12, 12, 76, 76))
    path = QPainterPath(QPointF(36, 38))
    path.cubicTo(36, 20, 68, 20, 64, 42)
    path.cubicTo(61, 56, 50, 54, 50, 66)
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(44, 74, 12, 12))


def _waves(p: QPainter, c: QColor) -> None:
    """Radiating arcs — monitor mode / signal."""
    _stroke(p, c, 10)
    for r in (18, 34, 50):
        p.drawArc(QRectF(50 - r, 62 - r, r * 2, r * 2), 35 * 16, 110 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(43, 55, 14, 14))


def _stop(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 9)
    p.drawEllipse(QRectF(14, 14, 72, 72))
    _poly(p, [(34, 34), (66, 66)])


def _flask(p: QPainter, c: QColor) -> None:
    """Test / injection self-test."""
    _stroke(p, c, 9)
    _poly(p, [(38, 10), (38, 42), (18, 84), (82, 84), (62, 42), (62, 10)])
    _poly(p, [(32, 10), (68, 10)])
    _poly(p, [(30, 62), (70, 62)])


def _list(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 10)
    for y in (24, 50, 76):
        _poly(p, [(38, y), (86, y)])
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    for y in (24, 50, 76):
        p.drawEllipse(QRectF(12, y - 6, 12, 12))


def _upload(p: QPainter, c: QColor) -> None:
    """Arrow out of a tray — report/share an adapter upstream."""
    _stroke(p, c, 10)
    _poly(p, [(50, 88), (50, 40)])
    _poly(p, [(20, 16), (80, 16)])
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawPath(_tri([(28, 52), (72, 52), (50, 26)]))


def _warning(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 9)
    _poly(p, [(50, 12), (92, 84), (8, 84)], close=True)
    _poly(p, [(50, 38), (50, 60)])
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(44, 68, 11, 11))


_PAINTERS = {
    "refresh": _refresh, "install": _download, "check": _check, "trash": _trash,
    "wrench": _wrench, "book": _book, "pulse": _pulse, "clipboard": _clipboard,
    "document": _document, "question": _question, "waves": _waves, "stop": _stop,
    "flask": _flask, "list": _list, "upload": _upload, "warning": _warning,
}


def pixmap(name: str, size: int = 16, colour: str = T.TEXT) -> QPixmap:
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    # The pixmap is size*dpr device pixels but carries a devicePixelRatio, so the
    # painter already works in `size` logical pixels — scaling by dpr as well
    # would draw at twice the size and clip the icon.
    painter.scale(size / 100.0, size / 100.0)
    fn = _PAINTERS.get(name)
    if fn:
        fn(painter, QColor(colour))
    painter.end()
    return pm


def icon(name: str, size: int = 16, colour: str = T.TEXT) -> QIcon:
    """A cached QIcon for ``name``. Unknown names give an empty (harmless) icon."""
    key = (name, size, colour)
    if key not in _CACHE:
        ico = QIcon(pixmap(name, size, colour))
        # Qt dims disabled icons automatically; give it a dim version explicitly
        # so a disabled button doesn't look like a rendering failure.
        ico.addPixmap(pixmap(name, size, T.DIM), QIcon.Disabled)
        _CACHE[key] = ico
    return _CACHE[key]


def dot(colour: str, size: int = 12) -> QPixmap:
    """A filled status dot with a soft halo — replaces the '●' character, which
    is another glyph that can go missing on a stripped-down font set."""
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / 100.0, size / 100.0)
    halo = QColor(colour)
    halo.setAlpha(60)
    p.setPen(Qt.NoPen)
    p.setBrush(halo)
    p.drawEllipse(QRectF(6, 6, 88, 88))
    p.setBrush(QColor(colour))
    p.drawEllipse(QRectF(26, 26, 48, 48))
    p.end()
    return pm


def available() -> list[str]:
    return sorted(_PAINTERS)
