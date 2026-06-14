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

from PySide6.QtCore import Qt, QThread, QObject, Signal, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .. import __version__, __codename__
from ..core import detector, report as rep, system
from ..core.chipset_db import Chipset, ChipsetDB
from ..core.detector import Adapter
from ..core.installer import Executor, build_plan
from . import theme as T


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
        self._thread: QThread | None = None

        self.setWindowTitle(f"AirDriver {__version__}")
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

        self.rescan()

    # ---- header ------------------------------------------------------------
    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setObjectName("Header")
        lay = QHBoxLayout(h)
        lay.setContentsMargins(18, 14, 18, 14)
        logo = QLabel("📡")
        logo.setStyleSheet("font-size:26px;")
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
        self.btn_rescan = QPushButton("⟳  Rescan")
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
        self.btn_report = QPushButton("Export report")
        self.btn_report.clicked.connect(self.export_report)
        actions.addWidget(self.btn_install)
        actions.addWidget(self.btn_plan)
        actions.addStretch(1)
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

    # ---- scan --------------------------------------------------------------
    def rescan(self):
        self.btn_rescan.setEnabled(False)
        self.btn_rescan.setText("Scanning…")
        self.log_line("Scanning USB/PCI bus and wireless interfaces…")
        self._thread = QThread()
        self.worker = ScanWorker(self.db)
        self.worker.moveToThread(self._thread)
        self._thread.started.connect(self.worker.run)
        self.worker.done.connect(self._on_scan_done)
        self.worker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_scan_done(self, info, adapters):
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

        self.log.clear()
        self._set_busy(True)
        self._thread = QThread()
        self.iworker = InstallWorker(plan, self.sysinfo, self.cb_dry.isChecked())
        self.iworker.moveToThread(self._thread)
        self._thread.started.connect(self.iworker.run)
        self.iworker.line.connect(self.log_line)
        self.iworker.done.connect(self._on_install_done)
        self.iworker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_install_done(self, ok: bool):
        self._set_busy(False)
        self.log_line("\n" + ("✓ Done." if ok else "✗ Finished with errors — see log."))
        # Refresh state so the card status/badges update.
        self.rescan()

    def _set_busy(self, busy: bool):
        for b in (self.btn_install, self.btn_plan, self.btn_rescan):
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
