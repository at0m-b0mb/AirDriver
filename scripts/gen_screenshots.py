#!/usr/bin/env python3
"""Regenerate the GUI screenshots in docs/screenshots/ headlessly.

Run it with the offscreen Qt backend so it needs no display and uses AirDriver's
demo adapters (the same view users see on a non-Linux box):

    QT_QPA_PLATFORM=offscreen python scripts/gen_screenshots.py

Produces:
  docs/screenshots/gui-overview.png       — main window, adapter selected
  docs/screenshots/gui-install-plan.png   — unknown adapter + previewed plan
  docs/screenshots/gui-chipsets.png       — searchable chipset browser
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AIRDRIVER_FORCE_GUI"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402

from airdriver.gui import theme as T  # noqa: E402
from airdriver.gui.main_window import MainWindow  # noqa: E402

OUT = ROOT / "docs" / "screenshots"


def _settle(app: QApplication, ms: int = 1800) -> None:
    """Pump the event loop so the background scan worker finishes and paints."""
    from PySide6.QtCore import QElapsedTimer
    t = QElapsedTimer()
    t.start()
    while t.elapsed() < ms:
        app.processEvents()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    # Match airdriver.gui.app exactly, so the screenshots show what a Linux user
    # actually sees rather than whatever style the host machine defaults to.
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(["Inter", "Cantarell", "Noto Sans", "DejaVu Sans", "sans-serif"])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(T.stylesheet())

    win = MainWindow()
    win.resize(1160, 760)
    win.show()
    _settle(app)

    # 1) Overview — first (known) adapter auto-selected.
    win.grab().save(str(OUT / "gui-overview.png"))
    print("wrote", OUT / "gui-overview.png")

    # 2) Unknown adapter selected + a previewed install plan in the log.
    unknown = next((a for a in win.adapters if not a.known), None)
    if unknown is not None:
        win.select_adapter(unknown)
    win.preview_plan()
    _settle(app, 400)
    win.grab().save(str(OUT / "gui-install-plan.png"))
    print("wrote", OUT / "gui-install-plan.png")

    # 3) The chipset browser, filtered — shows the breadth of the database.
    #    Built directly (rather than via the modal dialog) so this stays headless.
    _shot_chipsets(app, win)

    win.close()
    return 0


def _shot_chipsets(app, win):
    """Render the chipset-browser dialog without entering its modal loop."""
    from PySide6.QtWidgets import QDialog
    orig_exec = QDialog.exec
    captured = {}

    def fake_exec(self):
        captured["dlg"] = self
        return 0

    QDialog.exec = fake_exec
    try:
        win.show_chipsets()
        dlg = captured.get("dlg")
        if dlg is None:
            return
        dlg.resize(880, 620)
        dlg.show()
        _settle(app, 500)
        dlg.grab().save(str(OUT / "gui-chipsets.png"))
        print("wrote", OUT / "gui-chipsets.png")
        dlg.close()
    finally:
        QDialog.exec = orig_exec


if __name__ == "__main__":
    sys.exit(main())
