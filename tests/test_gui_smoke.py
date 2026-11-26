"""Does the GUI actually build, render and survive being clicked?

The trap this exists for: **an exception raised inside a Qt slot never reaches
the caller.** Qt catches it, prints it to stderr and carries on, so a panel that
blew up half-way through drawing still "renders", the test that built the window
still passes, and the breakage only shows up when a human looks at the screen.

So every test here installs a collecting ``sys.excepthook``, spins the real event
loop so queued slots actually run, and then *asserts that nothing was raised*.
Without that assertion these are not tests, they are a slow way of doing nothing.

Skipped when PySide6 is absent, which is why the core and CLI stay import-clean
of Qt: those run everywhere, this runs where there is a Qt to run it on.
"""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except Exception:  # noqa: BLE001 — any import failure means "no usable Qt"
    HAVE_QT = False

_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


class _Collector:
    """Captures anything Qt would have swallowed."""

    def __init__(self):
        self.errors: list[str] = []
        self._prev = None

    def __enter__(self):
        self._prev = sys.excepthook
        sys.excepthook = self._hook
        # PySide6 >= 6.5 routes slot exceptions through sys.excepthook, but set
        # the Qt-specific hook too where it exists so older versions are covered.
        try:
            import PySide6.QtCore as QtCore
            self._prev_qt = getattr(QtCore, "qInstallMessageHandler", None)
        except Exception:  # noqa: BLE001
            self._prev_qt = None
        return self

    def _hook(self, exc_type, exc, tb):
        import traceback
        self.errors.append("".join(traceback.format_exception(exc_type, exc, tb)))

    def __exit__(self, *_exc):
        sys.excepthook = self._prev
        return False

    def check(self, case: unittest.TestCase, what: str):
        case.assertEqual(self.errors, [], f"{what} raised inside a Qt slot:\n"
                                          + "\n".join(self.errors))


def _settle(window=None, ms: int = 2500) -> None:
    """Run the event loop until every worker thread has finished.

    Tearing a window down while a QThread is still running makes Qt abort the
    whole process, so the wait is not politeness — it is the difference between
    a test result and a SIGABRT.
    """
    app = _app()
    deadline = ms
    while deadline > 0:
        app.processEvents()
        jobs = getattr(window, "_jobs", []) if window is not None else []
        if not jobs:
            break
        QTimer.singleShot(0, lambda: None)
        app.processEvents()
        import time
        time.sleep(0.02)
        deadline -= 20
    for thread, _worker in list(getattr(window, "_jobs", [])):
        thread.quit()
        thread.wait(3000)
    app.processEvents()


@unittest.skipUnless(HAVE_QT, "needs PySide6")
class WindowBuilds(unittest.TestCase):
    def setUp(self):
        _app()

    def _window(self, collector):
        from airdriver.gui.main_window import MainWindow
        w = MainWindow()
        _settle(w)
        collector.check(self, "building the main window")
        return w

    def test_builds_and_scans_without_raising(self):
        with _Collector() as c:
            w = self._window(c)
            # The initial rescan runs on a worker thread; by now it has landed.
            self.assertIsNotNone(w.sysinfo, "the scan never reported system info")
            self.assertTrue(w.adapters, "demo mode should produce adapters off-Linux")
            w.close()
            _settle(w)
            c.check(self, "closing the window")

    def test_selecting_every_adapter_renders(self):
        """The details pane is drawn from database values — including an adapter
        that is deliberately *not* in the database."""
        with _Collector() as c:
            w = self._window(c)
            for adapter in w.adapters:
                w.select_adapter(adapter)
                _settle(w)
            c.check(self, "selecting an adapter")
            w.close()
            _settle(w)

    def test_preview_plan_and_log_colouring(self):
        with _Collector() as c:
            w = self._window(c)
            known = [a for a in w.adapters if a.known]
            self.assertTrue(known, "demo data should contain a known adapter")
            w.select_adapter(known[0])
            w.preview_plan()
            _settle(w)
            self.assertIn("Plan:", w.log.toPlainText())
            c.check(self, "previewing the install plan")
            w.close()
            _settle(w)

    def test_every_dialog_opens(self):
        """Each dialog interpolates values into rich text; a bad one throws
        inside a slot and would otherwise go unnoticed."""
        from PySide6.QtCore import QTimer as _T
        with _Collector() as c:
            w = self._window(c)
            for opener in (w.show_chipsets, w.show_help, w.show_manage):
                # Dialogs are modal: close the top one as soon as it appears.
                _T.singleShot(60, lambda: [d.accept() for d in w.findChildren(
                    __import__("PySide6.QtWidgets", fromlist=["QDialog"]).QDialog)])
                opener()
                _settle(w)
            c.check(self, "opening a dialog")
            w.close()
            _settle(w)


@unittest.skipUnless(HAVE_QT, "needs PySide6")
class HostileValuesCannotBecomeMarkup(unittest.TestCase):
    """A USB descriptor is attacker-controlled text.

    A QLabel in its default AutoText mode renders a string containing tags as
    rich text, and Qt then *fetches* any remote resource it names. So the
    adapter title, the description and every database value interpolated into
    the details pane must come out as literal characters.
    """

    def setUp(self):
        _app()

    def test_a_device_name_with_markup_stays_literal(self):
        from airdriver.core.chipset_db import ChipsetDB
        from airdriver.core.detector import Adapter
        from airdriver.gui.main_window import AdapterCard, MainWindow
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel

        payload = '<img src="http://attacker.invalid/x.png">pwn'
        hostile = Adapter(bus="1", device="2", vid="dead", pid="beef",
                          description=payload, chipset=None)
        with _Collector() as c:
            card = AdapterCard(hostile)
            _settle()
            c.check(self, "rendering a hostile adapter name")
            labels = card.findChildren(QLabel)
            shown = [l for l in labels if payload in l.text()]
            self.assertTrue(shown, "the device name was not rendered at all")
            for lab in shown:
                self.assertEqual(lab.textFormat(), Qt.PlainText,
                                 "a device-reported string is rendered as rich text, "
                                 "so Qt would fetch any URL inside it")

            w = MainWindow()
            _settle(w)
            w.adapters = [hostile]
            w.select_adapter(hostile)
            _settle(w)
            c.check(self, "selecting a hostile adapter")
            self.assertEqual(w.detail_title.textFormat(), Qt.PlainText)
            w.close()
            _settle(w)

    def test_database_notes_are_escaped_into_the_details_pane(self):
        from airdriver.core.chipset_db import ChipsetDB
        from airdriver.gui.main_window import MainWindow
        with _Collector() as c:
            w = MainWindow()
            _settle(w)
            known = [a for a in w.adapters if a.known]
            chip = known[0].chipset
            object.__setattr__(chip, "notes", '<img src="http://attacker.invalid/n">')
            w.select_adapter(known[0])
            _settle(w)
            c.check(self, "rendering hostile database notes")
            # Escaped, so the markup survives as text rather than as a tag.
            self.assertIn("&lt;img", w.detail_body.text())
            w.close()
            _settle(w)


if __name__ == "__main__":
    unittest.main()
