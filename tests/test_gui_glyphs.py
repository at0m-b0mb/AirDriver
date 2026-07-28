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


if __name__ == "__main__":
    unittest.main()
