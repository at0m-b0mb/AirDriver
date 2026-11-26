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

import atexit
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


@atexit.register
def _shutdown_qt() -> None:
    """Tear Qt down on purpose, before the interpreter starts dismantling itself.

    Left alone, CPython frees the QApplication during its own shutdown, by
    which point the C++ side may already be looking at half-freed Python
    objects — on Linux/offscreen that is a **segfault after the tests have
    all passed**, which reads as "the GUI tests crashed CI" when in fact the
    suite printed OK and then died on the way out. Closing the windows and
    deleting the application here keeps the exit code meaningful.
    """
    global _APP
    app, _APP = _APP, None
    if app is None:
        return
    try:
        for widget in list(app.topLevelWidgets()):
            widget.close()
            widget.deleteLater()
        app.processEvents()
    except Exception:  # noqa: BLE001 — we are exiting; nothing left to report to
        pass
    try:
        import shiboken6
        shiboken6.delete(app)
    except Exception:  # noqa: BLE001
        pass


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


def _fixture_adapters():
    """Adapters to render, built here rather than taken from a scan.

    The first version of these tests leaned on AirDriver's demo adapters, which
    exist only where there is no sysfs — so they passed on a Mac and failed on
    CI, where the scan correctly returns nothing because a GitHub runner has no
    Wi-Fi. What is under test is the *rendering*, so the input is constructed.
    """
    from airdriver.core.chipset_db import ChipsetDB
    from airdriver.core.detector import Adapter, WirelessInterface

    db = ChipsetDB.load()
    known = db.get("rtl8812au")
    native = db.get("ar9271")
    out = [
        Adapter(bus="1", device="4", vid="0bda", pid="8812",
                description="Realtek RTL8812AU 802.11ac WLAN Adapter",
                chipset=known),
        Adapter(bus="1", device="6", vid="0cf3", pid="9271",
                description="Qualcomm Atheros AR9271 802.11n", chipset=native),
        Adapter(bus="1", device="7", vid="1234", pid="abcd",
                description="Generic 802.11ac WLAN Adapter (unknown)", chipset=None),
        # A contested id: in the database's meta, in no chipset.
        Adapter(bus="1", device="8", vid="148f", pid="760a",
                description="Ralink 760a", chipset=None),
    ]
    out[1].interface = WirelessInterface(name="wlan1", driver="ath9k_htc",
                                         mode="managed")
    return db, out


def _loaded(window):
    """A window with adapters rendered into it, whatever the host OS is."""
    db, adapters = _fixture_adapters()
    window.sysinfo = window.sysinfo or __import__(
        "airdriver.core.system", fromlist=["gather"]).gather(check_internet=False)
    window.adapters = adapters
    window._render_cards(adapters)
    return adapters


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
            self.assertIsNotNone(w.sysinfo, "the scan never reported system info")
            w.close()
            _settle(w)
            c.check(self, "closing the window")

    def test_selecting_every_adapter_renders(self):
        """The details pane is drawn from database values — including adapters
        that are deliberately *not* in the database."""
        with _Collector() as c:
            w = self._window(c)
            adapters = _loaded(w)
            _settle(w)
            for adapter in adapters:
                w.select_adapter(adapter)
                _settle(w)
                self.assertTrue(w.verdict_text.text().strip(),
                                "the verdict strip said nothing")
            c.check(self, "selecting an adapter")
            w.close()
            _settle(w)

    def test_a_contested_id_is_explained_not_called_unknown(self):
        with _Collector() as c:
            w = self._window(c)
            adapters = _loaded(w)
            contested = next(a for a in adapters if a.usb_id == "148f:760a")
            w.select_adapter(contested)
            _settle(w)
            c.check(self, "selecting a contested adapter")
            self.assertIn("claimed by two", w.detail_body.text())
            w.close()
            _settle(w)

    def test_the_most_capable_adapter_is_selected_first(self):
        """On a box with an internal card and a USB injector, the injector is
        what you came to set up — and the top card is the one auto-selected."""
        with _Collector() as c:
            w = self._window(c)
            _loaded(w)
            _settle(w)
            self.assertIsNotNone(w.selected)
            self.assertTrue(w.selected.known)
            self.assertEqual(w.selected.chipset.injection_quality, "excellent",
                             "a less capable adapter was auto-selected")
            c.check(self, "ranking the adapters")
            w.close()
            _settle(w)

    def test_preview_plan_and_log_colouring(self):
        with _Collector() as c:
            w = self._window(c)
            adapters = _loaded(w)
            w.select_adapter(adapters[0])
            w.preview_plan()
            _settle(w)
            self.assertIn("Plan:", w.log.toPlainText())
            # The log is appended as HTML for coloured lines; the plain text
            # must still come back out intact, or "Copy log" is worthless.
            w.log_line("  ✗ step failed (exit 1) — aborting.")
            w.log_line("  [airdriver] driver source ready")
            _settle(w)
            text = w.log.toPlainText()
            self.assertIn("✗ step failed (exit 1)", text)
            self.assertIn("[airdriver] driver source ready", text)
            c.check(self, "previewing the install plan")
            w.close()
            _settle(w)

    def test_the_progress_bar_follows_the_step_headers(self):
        with _Collector() as c:
            w = self._window(c)
            w._set_busy(True)
            w.log_line("[3/9] Install build prerequisites")
            _settle(w)
            self.assertEqual((w.progress.value(), w.progress.maximum()), (3, 9))
            self.assertIn("3 of 9", w.progress_label.text())
            w._set_busy(False)
            c.check(self, "driving the progress bar")
            w.close()
            _settle(w)

    def test_every_dialog_opens(self):
        """Each dialog interpolates values into rich text; a bad one throws
        inside a slot and would otherwise go unnoticed."""
        from PySide6.QtCore import QTimer as _T
        from PySide6.QtWidgets import QDialog
        with _Collector() as c:
            w = self._window(c)
            _loaded(w)
            for opener in (w.show_chipsets, w.show_help, w.show_manage):
                _T.singleShot(60, lambda: [d.accept() for d in w.findChildren(QDialog)])
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
            shown = [l for l in card.findChildren(QLabel) if payload in l.text()]
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
        from airdriver.gui.main_window import MainWindow
        with _Collector() as c:
            w = MainWindow()
            _settle(w)
            adapters = _loaded(w)
            known = next(a for a in adapters if a.known)
            object.__setattr__(known.chipset, "notes",
                               '<img src="http://attacker.invalid/n">')
            w.select_adapter(known)
            _settle(w)
            c.check(self, "rendering hostile database notes")
            # Escaped, so the markup survives as text rather than as a tag.
            self.assertIn("&lt;img", w.detail_body.text())
            w.close()
            _settle(w)


if __name__ == "__main__":
    unittest.main()
