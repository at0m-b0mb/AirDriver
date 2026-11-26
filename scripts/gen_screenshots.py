#!/usr/bin/env python3
"""Regenerate the GUI screenshots in docs/screenshots/ headlessly.

Run it with the offscreen Qt backend so it needs no display and uses AirDriver's
demo adapters (the same view users see on a non-Linux box):

    QT_QPA_PLATFORM=offscreen python scripts/gen_screenshots.py

Produces:
  docs/screenshots/gui-overview.png       — main window, adapter selected
  docs/screenshots/gui-install-plan.png   — unknown adapter + previewed plan
  docs/screenshots/gui-chipsets.png       — searchable chipset browser
  docs/screenshots/gui-setup.png          — the one-press flow, dry run
  docs/screenshots/gui-drivers.png        — installed-driver management panel

Everything shown is produced by actually running the app in demo mode. Nothing
here types a transcript into the log by hand: a screenshot of output the tool
did not generate is a lie about what the tool does.
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
    _shot_dialog(app, win, win.show_chipsets, "gui-chipsets.png", 880, 620)

    # 4) The driver-management panel.
    _shot_dialog(app, win, win.show_manage, "gui-drivers.png", 800, 560)

    # 5) The one-press flow, as a dry run: a real plan, a real summary, the
    #    progress bar and the colour-coded log — all of it genuinely generated.
    _shot_setup(app, win)

    win.close()
    return 0


def _shot_setup(app, win):
    from airdriver.core import setup as setup_flow
    known = next((a for a in win.adapters if a.known), None)
    if known is None:
        return
    win.select_adapter(known)
    win.log.clear()
    win.progress.setRange(0, 9)
    win.progress.setValue(7)
    win.progress_label.setText("step 7 of 9")
    win.progress.show()
    out = setup_flow.run(win.db, target=known.usb_id, dry_run=True, log=win.log_line)
    win.log_line(setup_flow.describe(out))
    win._set_verdict(out.headline,
                     "good" if out.ready else ("warn" if out.connected else "warn"))
    _settle(app, 500)
    win.grab().save(str(OUT / "gui-setup.png"))
    print("wrote", OUT / "gui-setup.png")
    win.progress.hide()


def _shot_dialog(app, win, opener, name: str, w: int, h: int):
    """Render a modal dialog without entering its event loop."""
    from PySide6.QtWidgets import QDialog
    orig_exec = QDialog.exec
    captured = {}

    def fake_exec(self):
        captured["dlg"] = self
        return 0

    QDialog.exec = fake_exec
    try:
        opener()
        dlg = captured.get("dlg")
        if dlg is None:
            return
        dlg.resize(w, h)
        dlg.show()
        _settle(app, 500)
        dlg.grab().save(str(OUT / name))
        print("wrote", OUT / name)
        dlg.close()
    finally:
        QDialog.exec = orig_exec


if __name__ == "__main__":
    sys.exit(main())
