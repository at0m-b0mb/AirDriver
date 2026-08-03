"""Guard against the "buttons have no graphics" regression.

A minimal Kali/Parrot install ships DejaVu and *no emoji font*. Any emoji in a
widget label renders as an empty tofu box, so the app looks broken on exactly
the machines it targets. This has regressed once already — these tests make it
impossible to reintroduce without a failing build.

Pure source-scanning, so it runs in CI without Qt.
"""
import re
import unittest
from pathlib import Path

GUI = Path(__file__).resolve().parent.parent / "airdriver" / "gui"
CORE = Path(__file__).resolve().parent.parent / "airdriver" / "core"

# What a bare Kali/Parrot font set (fonts-dejavu-core) genuinely cannot render.
#
# Plain ✓ U+2713 and ✗ U+2717 are deliberately NOT banned: DejaVu Sans and DejaVu
# Sans Mono both carry them, they've shipped in AirDriver's CLI output since v0.1,
# and they read better than "[ok]". What breaks is the emoji planes — nothing in a
# default Linux font set covers those — plus the heavy/emoji-presentation variants
# below, which fall back to emoji rendering when any emoji font *is* installed.
RISKY = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emoji & pictographs (🔧 📚 🩺 📋 …)
    "☀-⛿"           # misc symbols (⚠ ☠ …)
    "⬀-⯿"           # misc symbols and arrows (⬇ ⬆ …)
    "⟰-⟿"           # supplemental arrows-A (⟳)
    "️"                  # variation selector-16 (forces emoji presentation)
    "✔✖➕➖❌❗➡"   # heavy/emoji dingbats
    "]")


def _offending(path: Path) -> list[tuple[int, str, str]]:
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        # Comments and docstring prose may legitimately mention the problem.
        if stripped.startswith("#"):
            continue
        for m in RISKY.finditer(line):
            out.append((n, m.group(), line.strip()[:90]))
    return out


class NoRiskyGlyphs(unittest.TestCase):
    def test_gui_sources_are_emoji_free(self):
        problems = []
        for f in sorted(GUI.glob("*.py")):
            if f.name == "icons.py":
                continue      # its docstring names the very glyphs it replaces
            for n, ch, ctx in _offending(f):
                problems.append(f"{f.name}:{n}: {ch!r} in: {ctx}")
        self.assertEqual(problems, [], "\nUse airdriver/gui/icons.py instead of emoji:\n"
                         + "\n".join(problems))

    def test_log_output_is_emoji_free(self):
        """installer/manage text lands in the GUI's monospace log, where symbol
        coverage is even thinner than the UI font's."""
        problems = []
        for name in ("installer.py", "manage.py", "contribute.py"):
            f = CORE / name
            if f.exists():
                problems += [f"{name}:{n}: {ch!r} in: {ctx}"
                             for n, ch, ctx in _offending(f)]
        self.assertEqual(problems, [], "\n".join(problems))


class IconSet(unittest.TestCase):
    """Every icon a widget asks for must actually exist, or the button renders
    blank — the same failure mode, just via a typo."""

    def test_every_requested_icon_exists(self):
        src = (GUI / "main_window.py").read_text(encoding="utf-8")
        requested = set(re.findall(r'icons\.icon\(\s*"([a-z_]+)"', src))
        # names passed through the header-button table
        requested |= set(re.findall(r'"(?:btn_\w+)",\s*[^,]+,\s*"([a-z_]+)"', src))
        icons_src = (GUI / "icons.py").read_text(encoding="utf-8")
        block = icons_src.split("_PAINTERS = {", 1)[1].split("}", 1)[0]
        painters = set(re.findall(r'"([a-z_]+)"\s*:\s*_\w+', block))
        missing = sorted(requested - painters)
        self.assertEqual(missing, [], f"main_window asks for icons that don't exist: {missing}")
        self.assertTrue(requested, "no icons found — did the call style change?")


try:  # Qt is an optional extra; these tests simply skip without it.
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    _HAVE_QT = True
except ImportError:  # pragma: no cover - depends on the environment
    _HAVE_QT = False


@unittest.skipUnless(_HAVE_QT, "needs PySide6")
class IconRendering(unittest.TestCase):
    """Icons must actually put pixels on the button, at every scale factor.

    The v0.5 icons were rasterised once into a fixed 32px pixmap, so Qt rescaled
    them for the 16px icon size the buttons requested and again for HiDPI —
    which is how they ended up faint or invisible depending on the desktop's
    scaling. These tests pin the resolution-independent behaviour.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from airdriver.gui import icons
        cls.icons = icons

    def _opaque(self, pixmap) -> int:
        img = pixmap.toImage()
        return sum(1 for y in range(img.height()) for x in range(img.width())
                   if img.pixelColor(x, y).alpha() > 8)

    def test_every_icon_draws_something(self):
        blank = []
        for name in self.icons.available():
            pm = self.icons.icon(name).pixmap(QSize(18, 18))
            if self._opaque(pm) == 0:
                blank.append(name)
        self.assertEqual(blank, [], f"icons render as empty pixmaps: {blank}")

    def test_pixmap_honours_the_requested_device_pixel_ratio(self):
        """At dpr=2 an 18px icon must come back as a real 36px bitmap, not an
        18px one stretched — that upscale is the 'washed out' bug."""
        ico = self.icons.icon("refresh")
        for dpr, expect in ((1.0, 18), (1.5, 27), (2.0, 36)):
            pm = ico.pixmap(QSize(18, 18), dpr)
            self.assertEqual((pm.width(), pm.height()), (expect, expect),
                             f"dpr={dpr}: expected {expect}px of real pixels")
            self.assertAlmostEqual(pm.devicePixelRatio(), dpr, places=3)

    def test_higher_dpr_carries_more_detail(self):
        ico = self.icons.icon("wrench")
        low = self._opaque(ico.pixmap(QSize(18, 18), 1.0))
        high = self._opaque(ico.pixmap(QSize(18, 18), 2.0))
        self.assertGreater(high, low * 2,
                           "the 2x pixmap is not carrying extra detail")

    def test_disabled_mode_still_renders(self):
        """A disabled button must show a dimmed icon, not a blank space."""
        for name in ("install", "trash", "refresh"):
            pm = self.icons.icon(name).pixmap(QSize(18, 18), 1.0, QIcon.Disabled)
            self.assertGreater(self._opaque(pm), 0, f"{name} vanishes when disabled")


if __name__ == "__main__":
    unittest.main()
