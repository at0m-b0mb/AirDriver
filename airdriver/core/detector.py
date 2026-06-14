"""Detects WiFi adapters and correlates them with the chipset database.

Strategy:
  * Enumerate USB devices via ``lsusb`` (parse VID:PID + description).
  * Enumerate PCI devices via ``lspci`` for internal cards (best-effort).
  * Enumerate live wireless interfaces from ``/sys/class/net`` and read the
    bound kernel driver from sysfs.
  * Match every device against the database by VID:PID; keep unknown devices
    that *look* like WiFi so AirDriver can offer the "help me identify it" flow.

On non-Linux hosts (a macOS dev box) ``detect()`` returns demo adapters so the
GUI is fully previewable without hardware.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .chipset_db import Chipset, ChipsetDB

_LSUSB_RE = re.compile(
    r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\s*(.*)"
)

# Keywords that suggest an unknown USB device is actually a WiFi adapter.
_WIFI_HINTS = ("wireless", "wlan", "802.11", "wifi", "wi-fi", "wlam", "network adapter", "wn722", "awus")


@dataclass
class WirelessInterface:
    name: str            # wlan0, wlan0mon...
    driver: str = ""     # bound kernel module
    mac: str = ""
    mode: str = ""       # managed | monitor | ...
    operstate: str = ""  # up | down
    usb_id: str = ""     # correlated vid:pid if discoverable


@dataclass
class Adapter:
    bus: str
    device: str
    vid: str
    pid: str
    description: str
    transport: str = "usb"             # "usb" | "pci"
    chipset: Optional[Chipset] = None  # None => unknown / not in DB
    interface: Optional[WirelessInterface] = None
    is_demo: bool = False

    @property
    def usb_id(self) -> str:
        return f"{self.vid}:{self.pid}".lower()

    @property
    def known(self) -> bool:
        return self.chipset is not None

    @property
    def driver_loaded(self) -> bool:
        return bool(self.interface and self.interface.driver)

    @property
    def title(self) -> str:
        if self.chipset:
            return self.chipset.name
        return self.description or f"Unknown device {self.usb_id}"

    @property
    def status(self) -> str:
        if self.interface and self.interface.name:
            return f"Working — {self.interface.name} ({self.interface.driver or 'driver?'})"
        if self.chipset and self.chipset.kernel_native:
            return "Recognized — driver may be in-kernel (verify)"
        if self.chipset:
            return "Recognized — driver needs installing"
        return "Unknown — needs identification"


def _run(cmd: list[str], timeout: int = 8) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return ""


# --------------------------------------------------------------------------- #
# sysfs: live wireless interfaces                                             #
# --------------------------------------------------------------------------- #
def _read(path: str) -> str:
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def list_wireless_interfaces() -> list[WirelessInterface]:
    base = "/sys/class/net"
    out: list[WirelessInterface] = []
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        dev = os.path.join(base, name)
        # Wireless NICs expose a phy80211 or wireless directory.
        if not (os.path.isdir(os.path.join(dev, "phy80211")) or
                os.path.isdir(os.path.join(dev, "wireless"))):
            continue
        iface = WirelessInterface(name=name)
        iface.mac = _read(os.path.join(dev, "address"))
        iface.operstate = _read(os.path.join(dev, "operstate"))
        # Bound driver module name from the device/driver symlink.
        drv_link = os.path.join(dev, "device", "driver")
        if os.path.islink(drv_link):
            iface.driver = os.path.basename(os.path.realpath(drv_link))
        # USB product id from the device uevent (PRODUCT=vid/pid/bcd, hex no pad).
        uevent = _read(os.path.join(dev, "device", "uevent"))
        m = re.search(r"PRODUCT=([0-9a-fA-F]+)/([0-9a-fA-F]+)/", uevent)
        if m:
            iface.usb_id = f"{int(m.group(1), 16):04x}:{int(m.group(2), 16):04x}"
        # Mode via iw if available.
        if shutil.which("iw"):
            info = _run(["iw", "dev", name, "info"])
            mm = re.search(r"type\s+(\w+)", info)
            if mm:
                iface.mode = mm.group(1)
        out.append(iface)
    return out


# --------------------------------------------------------------------------- #
# USB / PCI enumeration                                                       #
# --------------------------------------------------------------------------- #
def _parse_lsusb(db: ChipsetDB) -> list[Adapter]:
    text = _run(["lsusb"])
    adapters: list[Adapter] = []
    for line in text.splitlines():
        m = _LSUSB_RE.match(line.strip())
        if not m:
            continue
        bus, dev, vid, pid, desc = m.groups()
        usb_id = f"{vid}:{pid}".lower()
        chip = db.match_usb(usb_id)
        looks_wifi = any(h in desc.lower() for h in _WIFI_HINTS)
        if chip is None and not looks_wifi:
            continue  # skip mice, hubs, root hubs, etc.
        adapters.append(Adapter(bus=bus, device=dev, vid=vid.lower(),
                                pid=pid.lower(), description=desc.strip(),
                                transport="usb", chipset=chip))
    return adapters


def _parse_lspci(db: ChipsetDB) -> list[Adapter]:
    text = _run(["lspci", "-nn"])
    adapters: list[Adapter] = []
    for line in text.splitlines():
        low = line.lower()
        if "network" not in low and "wireless" not in low and "802.11" not in low:
            continue
        m = re.search(r"\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]", line)
        vid, pid = (m.group(1), m.group(2)) if m else ("0000", "0000")
        usb_id = f"{vid}:{pid}".lower()
        adapters.append(Adapter(bus="pci", device="", vid=vid.lower(), pid=pid.lower(),
                                description=line.split(": ", 1)[-1].strip(),
                                transport="pci", chipset=db.match_usb(usb_id)))
    return adapters


def _correlate(adapters: list[Adapter], ifaces: list[WirelessInterface]) -> None:
    by_usb = {i.usb_id: i for i in ifaces if i.usb_id}
    used: set[str] = set()
    for a in adapters:
        if a.usb_id in by_usb:
            a.interface = by_usb[a.usb_id]
            used.add(a.interface.name)
    # Any leftover wireless iface with no USB match (e.g. PCI) attaches to a
    # matching PCI adapter or is surfaced on its own elsewhere.
    leftover = [i for i in ifaces if i.name not in used]
    for a in adapters:
        if a.interface is None and a.transport == "pci" and leftover:
            a.interface = leftover.pop(0)


def _demo_adapters(db: ChipsetDB) -> list[Adapter]:
    """Synthetic adapters so the GUI is fully usable on a non-Linux dev box."""
    samples = [
        ("001", "004", "0bda", "8812", "Realtek RTL8812AU 802.11ac WLAN Adapter"),
        ("001", "006", "0cf3", "9271", "Qualcomm Atheros AR9271 802.11n"),
        ("001", "007", "1234", "abcd", "Generic 802.11ac WLAN Adapter (unknown)"),
    ]
    out = []
    for bus, dev, vid, pid, desc in samples:
        chip = db.match_usb(f"{vid}:{pid}")
        a = Adapter(bus=bus, device=dev, vid=vid, pid=pid, description=desc,
                    chipset=chip, is_demo=True)
        if chip and chip.id == "rtl8812au":
            a.interface = WirelessInterface(name="(not bound)", driver="", mode="")
        out.append(a)
    return out


def detect(db: Optional[ChipsetDB] = None, allow_demo: bool = True) -> list[Adapter]:
    db = db or ChipsetDB.load()
    have_lsusb = shutil.which("lsusb") is not None
    if not have_lsusb:
        return _demo_adapters(db) if allow_demo else []

    adapters = _parse_lsusb(db)
    if shutil.which("lspci"):
        adapters.extend(_parse_lspci(db))
    _correlate(adapters, list_wireless_interfaces())
    return adapters
