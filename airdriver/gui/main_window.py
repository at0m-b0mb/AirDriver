"""The AirDriver main window.

Layout:
  ┌ Header: logo · title · Rescan ───────────────────────────────┐
  │ Status strip: distro · kernel · headers · dkms · secure boot │
  ├───────────────┬──────────────────────────────────────────────┤
  │ Adapter cards │ Details + options + actions                   │
  │  (scrollable) │ Live install log console                      │
  └───────────────┴──────────────────────────────────────────────┘

Long operations (scan, install) run on worker threads so the UI never freezes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, QObject, Signal, QSize, QUrl, QRectF, QTimer
from PySide6.QtGui import QFont, QDesktopServices, QPixmap, QPainter, QPen, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QTextBrowser, QVBoxLayout, QWidget,
)

from .. import __version__, __codename__
from ..core import detector, report as rep, system, verify
from ..core.chipset_db import Chipset, ChipsetDB
from ..core.detector import Adapter
from ..core.installer import Executor, build_plan, build_remove_plan
from . import theme as T

REPO_URL = "https://github.com/at0m-b0mb/AirDriver"


def make_logo(size: int = 30) -> QPixmap:
    """A crisp vector 'transmitting signal' mark — no emoji-font dependency."""
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    cx, cy = size / 2, size * 0.66
    # expanding arcs
    for i, r in enumerate((size * 0.18, size * 0.32, size * 0.46)):
        col = QColor(T.ACCENT)
        col.setAlpha(255 - i * 70)
        p.setPen(QPen(col, size * 0.075))
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        p.drawArc(rect, 55 * 16, 70 * 16)
    # emitter dot
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(T.ACCENT))
    d = size * 0.13
    p.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))
    p.end()
    return pm


# --------------------------------------------------------------------------- #
# Workers                                                                     #
# --------------------------------------------------------------------------- #
class ScanWorker(QObject):
    done = Signal(object, object)  # SystemInfo, list[Adapter]

    def __init__(self, db: ChipsetDB):
        super().__init__()
        self.db = db

    def run(self):
        info = system.gather()
        adapters = detector.detect(self.db)
        self.done.emit(info, adapters)


class InstallWorker(QObject):
    line = Signal(str)
    done = Signal(bool)

    def __init__(self, plan, info, dry_run: bool):
        super().__init__()
        self.plan, self.info, self.dry_run = plan, info, dry_run

    def run(self):
        ok = Executor(self.info, dry_run=self.dry_run).run(
            self.plan, log=lambda s: self.line.emit(s))
        self.done.emit(ok)


class VerifyWorker(QObject):
    """Runs the (slightly slow: lsmod/iw/dmesg) post-install health check."""
    done = Signal(object)  # verify.Health

    def __init__(self, chip: Chipset, info, usb_id):
        super().__init__()
        self.chip, self.info, self.usb_id = chip, info, usb_id

    def run(self):
        self.done.emit(verify.check(self.chip, self.info, usb_id=self.usb_id))


class DiagnoseWorker(QObject):
    """Gathers the full diagnostic snapshot (rfkill/dmesg/dkms…) off the UI thread."""
    done = Signal(str)

    def __init__(self, db: ChipsetDB):
        super().__init__()
        self.db = db

    def run(self):
        from ..core import diagnose
        self.done.emit(diagnose.snapshot(self.db))


# --------------------------------------------------------------------------- #
# Small widgets                                                               #
# --------------------------------------------------------------------------- #
def _chip(text: str, colour: str | None = None, tip: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("Pill")
    if colour:
        lab.setStyleSheet(f"#Pill{{color:{colour};border-color:{colour};}}")
    if tip:
        lab.setToolTip(tip)
    return lab


class AdapterCard(QFrame):
    clicked = Signal(object)  # emits the Adapter

    def __init__(self, adapter: Adapter):
        super().__init__()
        self.adapter = adapter
        self.setObjectName("Card")
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{T.GOOD if adapter.known else T.DANGER};font-size:14px;")
        title = QLabel(adapter.title)
        title.setObjectName("H2")
        title.setWordWrap(True)
        top.addWidget(dot, 0)
        top.addWidget(title, 1)
        lay.addLayout(top)

        sub = QLabel(f"{adapter.usb_id}  ·  {adapter.transport.upper()}"
                     + ("  ·  demo" if adapter.is_demo else ""))
        sub.setObjectName("Dim")
        lay.addWidget(sub)

        status = QLabel(adapter.status)
        status.setObjectName("Dim")
        status.setWordWrap(True)
        lay.addWidget(status)

        if adapter.chipset:
            badges = QHBoxLayout()
            badges.setSpacing(6)
            c = adapter.chipset
            badges.addWidget(_chip("monitor" if c.monitor_mode else "no monitor",
                                   T.GOOD if c.monitor_mode else T.DIM))
            badges.addWidget(_chip("injection" if c.injection else "no injection",
                                   T.GOOD if c.injection else T.DIM))
            badges.addWidget(_chip(c.injection_quality, T.CYAN,
                                   tip="Injection reliability"))
            badges.addStretch(1)
            lay.addLayout(badges)

    def set_selected(self, sel: bool):
        self.setProperty("selected", sel)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        self.clicked.emit(self.adapter)
        super().mousePressEvent(e)


# --------------------------------------------------------------------------- #
# Main window                                                                 #
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = ChipsetDB.load()
        self.sysinfo = None
        self.adapters: list[Adapter] = []
        self.selected: Adapter | None = None
        self.cards: list[AdapterCard] = []
        # Strong references to in-flight (QThread, worker) pairs. Keeping them
        # here until the thread truly finishes is what prevents Python from
        # garbage-collecting a still-running QThread (which makes Qt abort).
        self._jobs: list[tuple[QThread, QObject]] = []
        self._scanning = False
        self._installing = False
        # When set, a finished install auto-runs verification for (chip, usb_id).
        self._verify_after: tuple[Chipset, str] | None = None

        self.setWindowTitle(f"AirDriver {__version__}")
        self.setWindowIcon(QIcon(make_logo(64)))
        self.resize(1080, 720)
        self.setMinimumSize(QSize(900, 600))

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(18, 14, 18, 18)
        body_l.setSpacing(14)
        self.status_strip = QFrame()
        self.status_strip.setObjectName("StatusStrip")
        self.status_strip_l = QHBoxLayout(self.status_strip)
        self.status_strip_l.setContentsMargins(14, 10, 14, 10)
        self.status_strip_l.setSpacing(8)
        body_l.addWidget(self.status_strip)
        body_l.addWidget(self._build_body(), 1)
        outer.addWidget(body, 1)
        outer.addWidget(self._build_footer())

        self.rescan()

    # ---- footer ------------------------------------------------------------
    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setObjectName("Footer")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(18, 8, 18, 8)
        tip = QLabel("Tip: pick an adapter, review the plan, then Install. "
                     "Use Dry run to preview safely.")
        tip.setObjectName("Dim")
        link = QLabel(f'<a style="color:{T.CYAN};text-decoration:none" '
                      f'href="{REPO_URL}">github.com/at0m-b0mb/AirDriver</a>')
        link.setOpenExternalLinks(True)
        link.setTextFormat(Qt.RichText)
        lay.addWidget(tip)
        lay.addStretch(1)
        lay.addWidget(link)
        return f

    # ---- header ------------------------------------------------------------
    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setObjectName("Header")
        lay = QHBoxLayout(h)
        lay.setContentsMargins(18, 14, 18, 14)
        logo = QLabel()
        logo.setPixmap(make_logo(30))
        title = QLabel("AirDriver")
        title.setObjectName("H1")
        ver = QLabel(f"v{__version__} · {__codename__}")
        ver.setObjectName("Dim")
        ver.setStyleSheet(f"color:{T.DIM};")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(title)
        col.addWidget(ver)
        lay.addWidget(logo)
        lay.addSpacing(6)
        lay.addLayout(col)
        lay.addStretch(1)
        self.btn_diag = QPushButton("🩺 Diagnose")
        self.btn_diag.setToolTip("Collect a full diagnostic snapshot (copied to clipboard) to share when stuck")
        self.btn_diag.clicked.connect(self.run_diagnose)
        lay.addWidget(self.btn_diag)
        self.btn_help = QPushButton("?  Help")
        self.btn_help.setToolTip("Quick start, troubleshooting, and the project page")
        self.btn_help.clicked.connect(self.show_help)
        lay.addWidget(self.btn_help)
        self.btn_rescan = QPushButton("⟳  Rescan")
        self.btn_rescan.setToolTip("Re-scan the USB/PCI bus for adapters")
        self.btn_rescan.clicked.connect(self.rescan)
        lay.addWidget(self.btn_rescan)
        return h

    # ---- body --------------------------------------------------------------
    def _build_body(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        # Left: adapter list
        left = QVBoxLayout()
        left.setSpacing(8)
        lbl = QLabel("Detected adapters")
        lbl.setObjectName("H2")
        left.addWidget(lbl)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards_host = QWidget()
        self.cards_l = QVBoxLayout(self.cards_host)
        self.cards_l.setContentsMargins(0, 0, 6, 0)
        self.cards_l.setSpacing(10)
        self.cards_l.addStretch(1)
        self.scroll.setWidget(self.cards_host)
        left.addWidget(self.scroll, 1)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(380)
        lay.addWidget(left_w)

        # Right: details + log
        lay.addWidget(self._build_right(), 1)
        return wrap

    def _build_right(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.detail_title = QLabel("Select an adapter")
        self.detail_title.setObjectName("H2")
        lay.addWidget(self.detail_title)

        self.detail_body = QLabel("Pick an adapter on the left to see chipset "
                                  "details and the install plan.")
        self.detail_body.setObjectName("Dim")
        self.detail_body.setWordWrap(True)
        self.detail_body.setTextFormat(Qt.RichText)
        lay.addWidget(self.detail_body)

        # Unknown-adapter identify row
        self.identify_row = QWidget()
        ir = QHBoxLayout(self.identify_row)
        ir.setContentsMargins(0, 0, 0, 0)
        ir.addWidget(QLabel("Identify as:"))
        self.identify_combo = QComboBox()
        for c in self.db.all():
            self.identify_combo.addItem(c.name, c.id)
        ir.addWidget(self.identify_combo, 1)
        self.identify_row.hide()
        lay.addWidget(self.identify_row)

        # Options
        opts = QHBoxLayout()
        opts.setSpacing(16)
        self.cb_offline = QCheckBox("Prefer offline driver")
        self.cb_offline.setToolTip("Use the bundled driver source instead of downloading.")
        self.cb_dkms = QCheckBox("Force DKMS build")
        self.cb_dkms.setToolTip("Build the out-of-tree driver even if an in-kernel one exists.")
        self.cb_dry = QCheckBox("Dry run")
        self.cb_dry.setToolTip("Show the plan and change nothing.")
        self.cb_dry.setChecked(False)
        for cb in (self.cb_offline, self.cb_dkms, self.cb_dry):
            opts.addWidget(cb)
        opts.addStretch(1)
        lay.addLayout(opts)

        # Action buttons
        actions = QHBoxLayout()
        self.btn_install = QPushButton("⬇  Install driver")
        self.btn_install.setObjectName("Primary")
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self.install_selected)
        self.btn_plan = QPushButton("Preview plan")
        self.btn_plan.setEnabled(False)
        self.btn_plan.clicked.connect(self.preview_plan)
        self.btn_verify = QPushButton("✔ Verify")
        self.btn_verify.setToolTip("Check the driver is built, loaded and bound to the adapter")
        self.btn_verify.setEnabled(False)
        self.btn_verify.clicked.connect(self.verify_selected)
        self.btn_remove = QPushButton("Remove driver")
        self.btn_remove.setObjectName("Ghost")
        self.btn_remove.setToolTip("Cleanly remove this driver (dkms/apt) so you can retry from scratch")
        self.btn_remove.setEnabled(False)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_copylog = QPushButton("Copy log")
        self.btn_copylog.setToolTip("Copy the activity log to the clipboard (handy for forum help threads)")
        self.btn_copylog.clicked.connect(self.copy_log)
        self.btn_report = QPushButton("Export report")
        self.btn_report.setToolTip("Write a JSON + Markdown diagnostic report")
        self.btn_report.clicked.connect(self.export_report)
        actions.addWidget(self.btn_install)
        actions.addWidget(self.btn_plan)
        actions.addWidget(self.btn_verify)
        actions.addStretch(1)
        actions.addWidget(self.btn_remove)
        actions.addWidget(self.btn_copylog)
        actions.addWidget(self.btn_report)
        lay.addLayout(actions)

        # Log console
        log_lbl = QLabel("Activity log")
        log_lbl.setObjectName("Dim")
        lay.addWidget(log_lbl)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Install output appears here…")
        lay.addWidget(self.log, 1)
        return w

    # ---- logging -----------------------------------------------------------
    def log_line(self, text: str):
        self.log.appendPlainText(text)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---- worker thread lifecycle ------------------------------------------
    def _start_worker(self, worker: QObject, on_done) -> None:
        """Run ``worker.run`` on its own QThread, safely.

        We keep a strong reference to both the thread and the worker in
        ``self._jobs`` until the thread emits ``finished`` — only then do we
        tear them down with ``deleteLater``. This is the crucial fix for the
        "QThread: Destroyed while thread is still running" abort that happened
        when an install finished and immediately triggered a rescan.
        """
        thread = QThread()
        worker.moveToThread(thread)
        self._jobs.append((thread, worker))
        thread.started.connect(worker.run)
        worker.done.connect(on_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda t=thread, w=worker: self._reap(t, w))
        thread.start()

    def _reap(self, thread: QThread, worker: QObject) -> None:
        thread.deleteLater()
        self._jobs = [(t, w) for (t, w) in self._jobs if t is not thread]

    def closeEvent(self, event):
        # Don't let the process exit while a worker thread is still running.
        for thread, _ in list(self._jobs):
            thread.quit()
            thread.wait(5000)
        super().closeEvent(event)

    # ---- scan --------------------------------------------------------------
    def rescan(self):
        if self._scanning:
            return
        self._scanning = True
        self.btn_rescan.setEnabled(False)
        self.btn_rescan.setText("Scanning…")
        self.log_line("Scanning USB/PCI bus and wireless interfaces…")
        self._start_worker(ScanWorker(self.db), self._on_scan_done)

    def _on_scan_done(self, info, adapters):
        self._scanning = False
        self.sysinfo = info
        self.adapters = adapters
        self._render_status(info)
        self._render_cards(adapters)
        self.btn_rescan.setEnabled(True)
        self.btn_rescan.setText("⟳  Rescan")
        n = len(adapters)
        self.log_line(f"Found {n} adapter(s)." + (
            "  (demo data — not running on Linux)" if adapters and adapters[0].is_demo else ""))

    def _render_status(self, info):
        while self.status_strip_l.count():
            item = self.status_strip_l.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def add(text, ok=True, warn=False, tip=""):
            colour = T.WARN if warn else (T.GOOD if ok else T.DANGER)
            self.status_strip_l.addWidget(_chip(text, colour, tip))

        add(info.distro_name, ok=True, tip="Detected distribution")
        add(f"kernel {info.kernel_release}", ok=True)
        if info.is_linux:
            add("headers ✓" if info.headers_installed else "headers ✗",
                ok=info.headers_installed, warn=not info.headers_installed,
                tip="Kernel headers are required for DKMS builds")
            add("dkms ✓" if info.dkms_installed else "dkms ✗",
                ok=info.dkms_installed, warn=not info.dkms_installed)
            sb = info.secure_boot
            add(f"secure boot: {sb}", ok=(sb == "off"), warn=(sb == "on"),
                tip="Secure Boot blocks unsigned DKMS modules")
            add("root ✓" if info.is_root else "not root",
                ok=info.is_root, warn=not info.is_root,
                tip="Installs need root; launch with sudo")
        else:
            add("demo mode (non-Linux)", warn=True,
                tip="Detection & install are simulated on this OS")
        add("online" if info.has_internet else "offline",
            ok=info.has_internet, warn=not info.has_internet)
        self.status_strip_l.addStretch(1)

    def _render_cards(self, adapters):
        # clear
        for c in self.cards:
            c.deleteLater()
        self.cards.clear()
        while self.cards_l.count():
            self.cards_l.takeAt(0)
        if not adapters:
            empty = QLabel("No WiFi adapters detected.\nPlug one in and press Rescan.")
            empty.setObjectName("Dim")
            empty.setAlignment(Qt.AlignCenter)
            self.cards_l.addWidget(empty)
            self.cards_l.addStretch(1)
            return
        for a in adapters:
            card = AdapterCard(a)
            card.clicked.connect(self.select_adapter)
            self.cards_l.addWidget(card)
            self.cards.append(card)
        self.cards_l.addStretch(1)
        self.select_adapter(adapters[0])

    # ---- selection ---------------------------------------------------------
    def select_adapter(self, adapter: Adapter):
        self.selected = adapter
        for c in self.cards:
            c.set_selected(c.adapter is adapter)
        self._render_detail(adapter)

    def _render_detail(self, a: Adapter):
        self.detail_title.setText(a.title)
        known = a.known
        self.identify_row.setVisible(not known)
        self.btn_install.setEnabled(True)
        self.btn_plan.setEnabled(True)
        self.btn_verify.setEnabled(True)
        self.btn_remove.setEnabled(True)
        if known:
            c = a.chipset
            drivers = " → ".join(d.method for d in c.best_drivers())
            native = (f"in-kernel <b>{c.kernel_native.module}</b> "
                      f"(kernel ≥ {c.kernel_native.min_kernel})") if c.kernel_native else "none"
            self.detail_body.setText(
                f"<b>{c.vendor}</b> · {c.wifi} · {c.band}<br>"
                f"Monitor mode: <b style='color:{T.GOOD if c.monitor_mode else T.DANGER}'>"
                f"{'yes' if c.monitor_mode else 'no'}</b> · "
                f"Injection: <b style='color:{T.GOOD if c.injection else T.DANGER}'>"
                f"{'yes' if c.injection else 'no'}</b> "
                f"({c.injection_quality})<br>"
                f"In-kernel driver: {native}<br>"
                f"Driver strategy: <span style='color:{T.CYAN}'>{drivers}</span><br><br>"
                f"<span style='color:{T.DIM}'>{c.notes}</span>")
        else:
            self.detail_body.setText(
                f"<span style='color:{T.WARN}'>This adapter ({a.usb_id}) isn't in the "
                f"database yet.</span><br>Choose the closest chipset below and AirDriver "
                f"will try its driver. Please consider reporting the USB ID so it can be added.")

    # ---- install -----------------------------------------------------------
    def _resolve_target(self) -> Adapter | None:
        a = self.selected
        if a is None:
            return None
        if not a.known:
            cid = self.identify_combo.currentData()
            a.chipset = self.db.get(cid)
        return a

    def _make_plan(self):
        a = self._resolve_target()
        if a is None or a.chipset is None:
            return None
        return build_plan(a, self.sysinfo,
                          force_dkms=self.cb_dkms.isChecked(),
                          prefer_offline=self.cb_offline.isChecked())

    def preview_plan(self):
        plan = self._make_plan()
        if plan is None:
            return
        self.log.clear()
        self.log_line(plan.describe())

    def install_selected(self):
        if self._installing:
            return
        plan = self._make_plan()
        if plan is None:
            return
        if self.sysinfo and not self.sysinfo.is_root and not self.cb_dry.isChecked() \
                and self.sysinfo.is_linux:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Root required")
            box.setText("Installing drivers needs root.")
            box.setInformativeText(
                "Either relaunch AirDriver with sudo, or continue — sudo will "
                "prompt for your password in the terminal you launched from.")
            box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            if box.exec() == QMessageBox.Cancel:
                return

        dry = self.cb_dry.isChecked()
        # After a real install, automatically verify the driver actually loaded.
        self._verify_after = (plan.chipset, self.selected.usb_id) if (
            not dry and self.sysinfo and self.sysinfo.is_linux and plan.chipset) else None
        self._installing = True
        self.log.clear()
        self._set_busy(True)
        worker = InstallWorker(plan, self.sysinfo, dry)
        worker.line.connect(self.log_line)
        self._start_worker(worker, self._on_install_done)

    def _on_install_done(self, ok: bool):
        self._installing = False
        self.log_line("\n" + ("✓ Install steps finished."
                              if ok else "✗ Finished with errors — see log."))
        target = self._verify_after
        self._verify_after = None
        if target and target[0]:
            chip, usb = target
            self.log_line(f"\nVerifying {chip.name} — checking the driver actually loaded…")
            self._start_worker(VerifyWorker(chip, self.sysinfo, usb), self._on_verify_done)
        else:
            self._set_busy(False)
            QTimer.singleShot(0, self.rescan)

    # ---- verify / remove ---------------------------------------------------
    def _selected_chip(self):
        a = self._resolve_target()
        if a is None or a.chipset is None:
            return None, None
        return a.chipset, a.usb_id

    def verify_selected(self):
        if self._installing:
            return
        chip, usb = self._selected_chip()
        if chip is None:
            return
        self.log.clear()
        self.log_line(f"Verifying {chip.name}…")
        self._set_busy(True)
        self._start_worker(VerifyWorker(chip, self.sysinfo, usb), self._on_verify_done)

    def _on_verify_done(self, health):
        self._set_busy(False)
        self.log_line("\n" + verify.describe(health))
        head = {
            "working":     "✓ Working — the driver is loaded and your adapter is ready.",
            "no_iface":    "Almost there — module loaded but no interface yet. Re-plug the adapter and Rescan.",
            "secure_boot": "Blocked by Secure Boot — the built module can't load until you disable it or enroll a MOK key.",
            "not_loaded":  "Built but not loaded — try a reboot, or re-plug and hit Verify again.",
            "not_built":   "The driver did not build for this kernel — see the log for why.",
            "demo":        "Demo mode — run on Kali/Parrot to verify for real.",
        }.get(health.verdict, "Verification finished.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information if health.ok else QMessageBox.Warning)
        box.setWindowTitle("Driver verification")
        box.setText(head)
        if not health.ok and health.messages:
            box.setInformativeText("\n".join(m for m in health.messages if m)[:700])
        box.exec()
        QTimer.singleShot(0, self.rescan)

    def remove_selected(self):
        if self._installing:
            return
        chip, _ = self._selected_chip()
        if chip is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Remove driver")
        box.setText(f"Remove the installed driver for {chip.name}?")
        box.setInformativeText(
            "Runs dkms/apt removal and unloads the module so you can retry a clean "
            "install. In-kernel drivers are left untouched.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return
        plan = build_remove_plan(chip, self.sysinfo)
        self._verify_after = None
        self._installing = True
        self.log.clear()
        self._set_busy(True)
        worker = InstallWorker(plan, self.sysinfo, False)
        worker.line.connect(self.log_line)
        self._start_worker(worker, self._on_install_done)

    # ---- diagnostics -------------------------------------------------------
    def run_diagnose(self):
        if self._installing:
            return
        self.btn_diag.setEnabled(False)
        self.btn_diag.setText("Collecting…")
        self.log.clear()
        self.log_line("Collecting diagnostic snapshot (rfkill · dmesg · dkms · interfaces)…")
        self._start_worker(DiagnoseWorker(self.db), self._on_diagnose_done)

    def _on_diagnose_done(self, text: str):
        self.btn_diag.setEnabled(True)
        self.btn_diag.setText("🩺 Diagnose")
        self.log.setPlainText(text)
        QApplication.clipboard().setText(text)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Diagnostic ready")
        box.setText("Diagnostic snapshot copied to your clipboard.")
        box.setInformativeText("It's also shown in the log on the right. Paste it into a "
                               "GitHub issue / forum / chat when asking for help.")
        box.exec()

    # ---- diagnose ----------------------------------------------------------
    def run_diagnose(self):
        if self._installing or self._scanning:
            return
        self.log.clear()
        self.log_line("Collecting diagnostic snapshot (rfkill, dmesg, dkms…)…")
        self.btn_diag.setEnabled(False)
        self.btn_diag.setText("Collecting…")
        self._start_worker(DiagnoseWorker(self.db), self._on_diagnose_done)

    def _on_diagnose_done(self, text: str):
        self.btn_diag.setEnabled(True)
        self.btn_diag.setText("🩺 Diagnose")
        self.log.setPlainText(text)
        QApplication.clipboard().setText(text)
        QMessageBox.information(
            self, "Diagnostic ready",
            "A full diagnostic snapshot is shown in the log and copied to your "
            "clipboard.\n\nPaste it wherever you're asking for help.")

    def _set_busy(self, busy: bool):
        for b in (self.btn_install, self.btn_plan, self.btn_rescan,
                  self.btn_verify, self.btn_remove):
            b.setEnabled(not busy)
        self.btn_install.setText("Installing…" if busy else "⬇  Install driver")

    # ---- report ------------------------------------------------------------
    def export_report(self):
        if self.sysinfo is None:
            return
        report = rep.build(self.sysinfo, self.adapters, log=self.log.toPlainText())
        paths = rep.save(report, fmt="both")
        self.log_line("Saved report:")
        for p in paths:
            self.log_line(f"  {p}")
        QMessageBox.information(self, "Report saved",
                                "Diagnostic report written to:\n\n" +
                                "\n".join(str(p) for p in paths))

    # ---- copy log ----------------------------------------------------------
    def copy_log(self):
        text = self.log.toPlainText()
        if not text.strip():
            self.log_line("(nothing to copy yet)")
            return
        QApplication.clipboard().setText(text)
        self.log_line("📋 Log copied to clipboard.")

    # ---- help / about ------------------------------------------------------
    def show_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("AirDriver — Help")
        dlg.resize(640, 560)
        lay = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setHtml(f"""
        <h2 style="color:{T.ACCENT};margin-bottom:2px">AirDriver
            <span style="color:{T.DIM};font-size:13px">v{__version__} · {__codename__}</span></h2>
        <p style="color:{T.DIM}">WiFi adapter driver auto-installer for Kali&nbsp;Linux &amp; Parrot&nbsp;OS.</p>

        <h3 style="color:{T.CYAN}">Quick start</h3>
        <ol>
          <li>Plug in your USB WiFi adapter.</li>
          <li>Press <b>⟳ Rescan</b> and select the adapter card on the left.</li>
          <li>Review the chipset details &amp; capabilities, then click <b>⬇ Install driver</b>.</li>
          <li>Tick <b>Dry run</b> first if you want to preview every step without changing anything.</li>
        </ol>

        <h3 style="color:{T.CYAN}">Installing needs root</h3>
        <p>Driver installation modifies the system, so it needs root. The smoothest way is to
        launch the whole app with root:</p>
        <pre style="background:#0a0e14;padding:8px;border-radius:6px">sudo airdriver</pre>
        <p>If you started it as a normal user, that's fine too — each install step will ask for
        your <code>sudo</code> password in the terminal you launched from.</p>

        <h3 style="color:{T.CYAN}">Won't open / Qt errors?</h3>
        <p>The command-line tools need <b>no</b> GUI libraries and always work:</p>
        <pre style="background:#0a0e14;padding:8px;border-radius:6px">airdriver scan      airdriver doctor      airdriver install</pre>
        <p>If the GUI shows an <code>xcb</code> error, install the Qt runtime libs:</p>
        <pre style="background:#0a0e14;padding:8px;border-radius:6px">sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1</pre>

        <h3 style="color:{T.CYAN}">Adapter not recognised?</h3>
        <p>Select it, choose the closest chipset under <b>Identify as</b>, and AirDriver will try
        that driver. Please consider reporting its USB ID so it can be added to the database.</p>

        <h3 style="color:{T.CYAN}">Links</h3>
        <p>
          Project &amp; issues: <a style="color:{T.CYAN}" href="{REPO_URL}">{REPO_URL}</a><br>
          Chipset database: <a style="color:{T.CYAN}" href="{REPO_URL}/blob/main/airdriver/data/chipsets.json">chipsets.json</a>
        </p>

        <p style="color:{T.WARN}">⚠ Use monitor mode / injection only on networks you own or are
        authorised to test.</p>
        """)
        lay.addWidget(view)
        row = QHBoxLayout()
        btn_repo = QPushButton("Open project page")
        btn_repo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        btn_close = QPushButton("Close")
        btn_close.setObjectName("Primary")
        btn_close.clicked.connect(dlg.accept)
        row.addWidget(btn_repo)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)
        dlg.exec()
