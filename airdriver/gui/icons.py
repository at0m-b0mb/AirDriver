"""Vector icons drawn with QPainter — deliberately *not* emoji, and deliberately
*not* baked into a fixed-size bitmap.

Two separate failure modes put blank//faint graphics on buttons, and this module
exists to close both:

1. **No emoji font.** A minimal Kali/Parrot install has none, so any 🔧/📚/🩺/⬇
   in a button label renders as an empty tofu box. Everything here is drawn from
   paths instead, so it looks identical on a bare box and a full desktop.

2. **One baked raster at the wrong scale.** The previous version rendered each
   icon once into a 32x32 pixmap and handed that to ``QIcon``. ``QIcon`` then
   advertised a *32px* icon, so at the 16px icon size the buttons ask for, Qt
   downscaled it — turning a ~1.5px antialiased stroke into a washed-out smear.
   On fractional desktop scaling (1.25x/1.5x, common under Wayland) it got worse
   still. Icons are now painted on demand through a ``QIconEngine`` at exactly
   the size and device-pixel-ratio Qt asks for, so they are crisp everywhere.

Usage:

    from . import icons
    btn.setIcon(icons.icon("refresh"))
    btn.setIconSize(icons.SIZE)

Icons are drawn on a 100x100 logical grid and mapped onto the target rect, so
they stay sharp at any size and on any HiDPI/fractional-scaling setup.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QIcon, QIconEngine, QPainter, QPainterPath,
                           QPen, QPixmap)

from . import theme as T

# 18px reads clearly next to the 13px UI font without crowding the label. The
# old 16px was small enough that thin strokes disappeared on low-DPI screens.
SIZE = QSize(18, 18)
_CACHE: dict[tuple, QIcon] = {}


# --------------------------------------------------------------------------- #
# drawing helpers (all on a 100x100 grid)                                     #
# --------------------------------------------------------------------------- #
# Strokes are deliberately chunky: at an 18px render a width of 10 grid units is
# only ~1.8 device pixels, which is the minimum that survives antialiasing on a
# 1x screen without looking like a grey suggestion.
def _stroke(p: QPainter, colour: QColor, width: float = 10.0) -> None:
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


def _tri(pts):
    path = QPainterPath(QPointF(*pts[0]))
    for xy in pts[1:]:
        path.lineTo(QPointF(*xy))
    path.closeSubpath()
    return path


def _fill_tri(p: QPainter, c: QColor, pts) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawPath(_tri(pts))


# --------------------------------------------------------------------------- #
# the icons                                                                   #
# --------------------------------------------------------------------------- #
def _refresh(p: QPainter, c: QColor) -> None:
    """Circular arrow — rescan.

    The arrowhead is anchored *on* the open end of the arc. It used to be placed
    by eye well above it, which drew a circle with a detached blob floating next
    to it rather than anything resembling an arrow.
    """
    _stroke(p, c, 11)
    # Centre (50,50) r=30. Sweep 270 deg starting at 60 deg, so the gap sits at
    # the top-right and the arc terminates exactly where the head is drawn.
    p.drawArc(QRectF(20, 20, 60, 60), 60 * 16, 270 * 16)
    # Arc start point at 60 deg = (50 + 30*cos60, 50 - 30*sin60) = (65, 24).
    _fill_tri(p, c, [(65, 8), (65, 40), (90, 24)])


def _download(p: QPainter, c: QColor) -> None:
    """Arrow into a tray — install."""
    _stroke(p, c, 11)
    _poly(p, [(50, 8), (50, 54)])
    _poly(p, [(18, 84), (82, 84)])
    _fill_tri(p, c, [(26, 44), (74, 44), (50, 74)])


def _check(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 13)
    _poly(p, [(14, 52), (40, 78), (86, 22)])


def _trash(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 10)
    _poly(p, [(14, 26), (86, 26)])
    _poly(p, [(38, 14), (62, 14)])
    _poly(p, [(24, 26), (29, 88), (71, 88), (76, 26)])
    _poly(p, [(42, 42), (44, 74)])
    _poly(p, [(58, 42), (56, 74)])


def _wrench(p: QPainter, c: QColor) -> None:
    """Spanner — driver management.

    Drawn as an open ring (the jaw) plus a handle running to the lower-left. The
    previous ``arcTo`` construction produced an unclosed hook that read as a
    random squiggle at button size.
    """
    _stroke(p, c, 12)
    # Jaw: ring centred (68,34) r=18, 300 deg of sweep so the 60 deg gap opens
    # up-and-right, away from the handle.
    p.drawArc(QRectF(50, 16, 36, 36), 75 * 16, 300 * 16)
    # Handle: from the ring's lower-left edge down to the bottom-left corner.
    _poly(p, [(55, 47), (24, 80)])


def _book(p: QPainter, c: QColor) -> None:
    """Open book — the chipset catalogue."""
    _stroke(p, c, 10)
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
    _stroke(p, c, 11)
    _poly(p, [(6, 52), (28, 52), (40, 18), (56, 84), (68, 52), (94, 52)])


def _clipboard(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 10)
    p.drawRoundedRect(QRectF(22, 20, 56, 68), 8, 8)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(38, 10, 24, 18), 4, 4)
    p.setBrush(Qt.NoBrush)
    _poly(p, [(36, 50), (64, 50)])
    _poly(p, [(36, 66), (58, 66)])


def _document(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 10)
    _poly(p, [(24, 10), (60, 10), (78, 30), (78, 90), (24, 90)], close=True)
    _poly(p, [(58, 10), (58, 32), (78, 32)])
    _poly(p, [(36, 52), (66, 52)])
    _poly(p, [(36, 68), (66, 68)])


def _question(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 10)
    p.drawEllipse(QRectF(12, 12, 76, 76))
    path = QPainterPath(QPointF(36, 38))
    path.cubicTo(36, 20, 68, 20, 64, 42)
    path.cubicTo(61, 56, 50, 54, 50, 64)
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(44, 72, 13, 13))


def _waves(p: QPainter, c: QColor) -> None:
    """Radiating arcs — monitor mode / signal."""
    _stroke(p, c, 11)
    for r in (20, 36, 52):
        p.drawArc(QRectF(50 - r, 66 - r, r * 2, r * 2), 35 * 16, 110 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(42, 58, 16, 16))


def _stop(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 10)
    p.drawEllipse(QRectF(14, 14, 72, 72))
    _poly(p, [(33, 33), (67, 67)])


def _flask(p: QPainter, c: QColor) -> None:
    """Test / injection self-test."""
    _stroke(p, c, 10)
    _poly(p, [(38, 10), (38, 42), (16, 84), (84, 84), (62, 42), (62, 10)])
    _poly(p, [(31, 10), (69, 10)])
    _poly(p, [(28, 62), (72, 62)])


def _list(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 11)
    for y in (24, 50, 76):
        _poly(p, [(38, y), (88, y)])
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    for y in (24, 50, 76):
        p.drawEllipse(QRectF(10, y - 7, 14, 14))


def _upload(p: QPainter, c: QColor) -> None:
    """Arrow out of a tray — report/share an adapter upstream."""
    _stroke(p, c, 11)
    _poly(p, [(50, 92), (50, 46)])
    _poly(p, [(18, 16), (82, 16)])
    _fill_tri(p, c, [(26, 56), (74, 56), (50, 26)])


def _warning(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 10)
    _poly(p, [(50, 12), (92, 84), (8, 84)], close=True)
    _poly(p, [(50, 40), (50, 60)])
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(44, 68, 12, 12))


def _broom(p: QPainter, c: QColor) -> None:
    """Sweep — the 'clean everything out' uninstall action."""
    _stroke(p, c, 11)
    _poly(p, [(78, 12), (46, 48)])          # handle
    _stroke(p, c, 10)
    _poly(p, [(24, 44), (60, 76)], close=False)   # brush head (top edge)
    _poly(p, [(18, 54), (30, 88)])
    _poly(p, [(36, 62), (44, 92)])
    _poly(p, [(54, 68), (58, 88)])


def _chip(p: QPainter, c: QColor) -> None:
    """A silicon die with legs — chipset / hardware."""
    _stroke(p, c, 10)
    p.drawRoundedRect(QRectF(28, 28, 44, 44), 6, 6)
    for v in (42, 58):
        _poly(p, [(v, 10), (v, 28)])        # top legs
        _poly(p, [(v, 72), (v, 90)])        # bottom legs
        _poly(p, [(10, v), (28, v)])        # left legs
        _poly(p, [(72, v), (90, v)])        # right legs


def _shield(p: QPainter, c: QColor) -> None:
    """Secure Boot / signing."""
    _stroke(p, c, 10)
    path = QPainterPath(QPointF(50, 10))
    path.lineTo(84, 24)
    path.lineTo(84, 52)
    path.cubicTo(84, 74, 68, 84, 50, 92)
    path.cubicTo(32, 84, 16, 74, 16, 52)
    path.lineTo(16, 24)
    path.closeSubpath()
    p.drawPath(path)


def _plug(p: QPainter, c: QColor) -> None:
    """USB plug — 'adapter'."""
    _stroke(p, c, 10)
    _poly(p, [(50, 92), (50, 44)])
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(40, 8, 20, 20))
    _stroke(p, c, 10)
    _poly(p, [(50, 62), (26, 46), (26, 30)])
    _poly(p, [(50, 74), (74, 54), (74, 34)])
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(20, 22, 13, 13))
    p.drawEllipse(QRectF(67, 26, 15, 15))


def _eye(p: QPainter, c: QColor) -> None:
    """Preview — look at the plan without running it."""
    _stroke(p, c, 10)
    path = QPainterPath(QPointF(6, 50))
    path.cubicTo(26, 20, 74, 20, 94, 50)
    path.cubicTo(74, 80, 26, 80, 6, 50)
    path.closeSubpath()
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(39, 39, 22, 22))


_PAINTERS = {
    "refresh": _refresh, "install": _download, "check": _check, "trash": _trash,
    "wrench": _wrench, "book": _book, "pulse": _pulse, "clipboard": _clipboard,
    "document": _document, "question": _question, "waves": _waves, "stop": _stop,
    "flask": _flask, "list": _list, "upload": _upload, "warning": _warning,
    "broom": _broom, "chip": _chip, "shield": _shield, "plug": _plug,
    "eye": _eye,
}


# --------------------------------------------------------------------------- #
# resolution-independent icon engine                                          #
# --------------------------------------------------------------------------- #
def draw(painter: QPainter, name: str, colour: str, rect: QRectF) -> None:
    """Paint icon ``name`` into ``rect`` (logical coordinates)."""
    fn = _PAINTERS.get(name)
    if fn is None:
        return
    side = min(rect.width(), rect.height())
    if side <= 0:
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    # Centre the 100x100 grid inside the requested rect.
    painter.translate(rect.x() + (rect.width() - side) / 2.0,
                      rect.y() + (rect.height() - side) / 2.0)
    painter.scale(side / 100.0, side / 100.0)
    fn(painter, QColor(colour))
    painter.restore()


class _Engine(QIconEngine):
    """Paints on demand at exactly the size/DPR Qt asks for.

    This is what keeps the icons sharp on HiDPI and fractional-scaling desktops:
    nothing is ever rasterised at one fixed size and rescaled.
    """

    def __init__(self, name: str, colour: str, disabled_colour: str):
        super().__init__()
        self._name = name
        self._colour = colour
        self._disabled = disabled_colour

    def _colour_for(self, mode) -> str:
        return self._disabled if mode == QIcon.Disabled else self._colour

    # Telling Qt we can render at the exact requested size stops it from
    # substituting (and then scaling) some other "closest available" size.
    def actualSize(self, size: QSize, mode, state) -> QSize:
        return size

    def availableSizes(self, mode=QIcon.Normal, state=QIcon.Off):
        return [QSize(n, n) for n in (16, 18, 20, 22, 24, 32, 48, 64)]

    def paint(self, painter: QPainter, rect, mode, state) -> None:
        draw(painter, self._name, self._colour_for(mode), QRectF(rect))

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size: QSize, mode, state, scale: float) -> QPixmap:
        # Qt hands us the *logical* size and the target device-pixel-ratio; the
        # returned pixmap is expected to be size*scale actual pixels, tagged with
        # that ratio. Allocating only `size` here is precisely the mistake that
        # throws away the HiDPI detail and leaves icons looking washed out.
        scale = float(scale) or 1.0
        dev = QSize(max(1, round(size.width() * scale)),
                    max(1, round(size.height() * scale)))
        pm = QPixmap(dev)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        # QPainter on a pixmap carrying a devicePixelRatio already works in
        # logical units, so draw into the logical rect.
        draw(p, self._name, self._colour_for(mode),
             QRectF(0, 0, size.width(), size.height()))
        p.end()
        return pm

    def clone(self) -> "QIconEngine":
        return _Engine(self._name, self._colour, self._disabled)


def icon(name: str, colour: str = T.TEXT, disabled: str = T.DIM) -> QIcon:
    """A cached, resolution-independent QIcon for ``name``.

    Unknown names give an empty (harmless) icon rather than raising, so a typo
    can never take the window down — the accompanying test catches those.
    """
    key = (name, colour, disabled)
    if key not in _CACHE:
        _CACHE[key] = QIcon(_Engine(name, colour, disabled))
    return _CACHE[key]


def pixmap(name: str, size: int = 18, colour: str = T.TEXT) -> QPixmap:
    """A standalone pixmap — for QLabel and the window icon."""
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    draw(p, name, colour, QRectF(0, 0, size, size))
    p.end()
    return pm


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
