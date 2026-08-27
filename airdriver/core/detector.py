"""Detects WiFi adapters and correlates them with the chipset database.

Enumeration is **sysfs-native**: ``/sys/bus/usb/devices`` and
``/sys/bus/pci/devices`` are read directly instead of shelling out to ``lsusb``
and ``lspci``. Those binaries live in the ``usbutils`` / ``pciutils`` packages,
which a minimal Kali or Parrot install does not necessarily ship — and when
``lsusb`` was missing AirDriver used to fall back to *demo* adapters, i.e. it
invented three plausible-looking adapters on a machine whose real hardware was
sitting right there in sysfs. sysfs is part of the kernel, so it is always
present on Linux. ``lsusb``/``lspci`` are still consulted when installed, purely
to borrow their vendor-resolved product names.

Strategy:
  * Enumerate USB devices from sysfs (VID/PID, product strings, interface class).
  * Enumerate PCI devices from sysfs, keeping class 0x0280 (wireless network
    controller) so Ethernet NICs are never offered a Wi-Fi driver.
  * Enumerate live wireless interfaces from ``/sys/class/net`` and read the
    bound kernel driver from sysfs.
  * Match every device against the database by ``vid:pid``; keep unknown devices
    that *look* like WiFi so AirDriver can offer the "help me identify it" flow.
  * Correlate interfaces to adapters by **sysfs device path**, so with two
    wireless devices present each interface lands on the adapter that actually
    owns it.

Only on a host with no sysfs at all (a macOS dev box) does ``detect()`` return
demo adapters, so the GUI stays previewable without hardware.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from .chipset_db import Chipset, ChipsetDB

SYSFS_ROOT = "/sys"

_LSUSB_RE = re.compile(
    r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\s*(.*)"
)
# `lspci -Dnn`: "0000:03:00.0 Network controller [0280]: Intel ... [8086:2723] (rev 1a)"
_LSPCI_RE = re.compile(r"^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\s+(.*)$")

# Keywords that suggest an unknown device is actually a WiFi adapter.
_WIFI_HINTS = ("wireless", "wlan", "802.11", "wifi", "wi-fi", "wlam",
               "network adapter", "wn722", "awus")

# USB root hubs advertise the Linux Foundation vendor id; never a Wi-Fi adapter.
_USB_ROOT_HUB_VID = "1d6b"

# USB class 0xE0 is "Wireless Controller", but subclass 0x01 within it is
# Bluetooth (RF controller) — which every second laptop has, and which must not
# be offered a Wi-Fi driver.
_USB_CLASS_WIRELESS = "e0"
_USB_SUBCLASS_BLUETOOTH = "01"

# PCI class 0x02 is a network controller; subclass 0x80 ("other") is what every
# Wi-Fi card reports. Ethernet is subclass 0x00 and is deliberately excluded.
_PCI_CLASS_NETWORK = "02"
_PCI_SUBCLASS_WIRELESS = "80"


@dataclass
class WirelessInterface:
    name: str            # wlan0, wlan0mon...
    driver: str = ""     # bound kernel module
    mac: str = ""
    mode: str = ""       # managed | monitor | ...
    operstate: str = ""  # up | down
    usb_id: str = ""     # correlated vid:pid if discoverable
    device_path: str = ""  # resolved sysfs path of the device behind this iface


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
    sysfs_path: str = ""               # resolved sysfs dir of this device

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


def _read(path: str) -> str:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _hex4(raw: str) -> str:
    """'0x8086' / '8086' -> '8086'. Empty string when unparseable."""
    raw = raw.strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    return raw.zfill(4)[-4:] if re.fullmatch(r"[0-9a-f]{1,4}", raw) else ""


# --------------------------------------------------------------------------- #
# sysfs: live wireless interfaces                                             #
# --------------------------------------------------------------------------- #
def list_wireless_interfaces(sysfs_root: str = SYSFS_ROOT) -> list[WirelessInterface]:
    base = os.path.join(sysfs_root, "class", "net")
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
        # The device backing this netdev. For PCI this is the card itself; for
        # USB it is the *interface* directory whose parent is the device.
        dev_link = os.path.join(dev, "device")
        if os.path.exists(dev_link):
            iface.device_path = os.path.realpath(dev_link)
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
# Optional enrichment from usbutils / pciutils                                #
# --------------------------------------------------------------------------- #
def _lsusb_names() -> dict[str, str]:
    """``vid:pid`` -> vendor-resolved product name, when usbutils is installed.

    sysfs only offers the string descriptor the device reports about itself
    ("802.11n NIC"); lsusb resolves the id against usb.ids and yields something
    a human recognises ("Realtek Semiconductor Corp. RTL8812AU"). Best-effort.
    """
    if not shutil.which("lsusb"):
        return {}
    names: dict[str, str] = {}
    for line in _run(["lsusb"]).splitlines():
        m = _LSUSB_RE.match(line.strip())
        if not m:
            continue
        _bus, _dev, vid, pid, desc = m.groups()
        desc = desc.strip()
        if desc:
            names.setdefault(f"{vid}:{pid}".lower(), desc)
    return names


def _lspci_names() -> dict[str, str]:
    """Domain-qualified PCI slot -> human name, when pciutils is installed."""
    if not shutil.which("lspci"):
        return {}
    names: dict[str, str] = {}
    for line in _run(["lspci", "-Dnn"]).splitlines():
        m = _LSPCI_RE.match(line.strip())
        if not m:
            continue
        slot, rest = m.group(1).lower(), m.group(2)
        desc = rest.split(": ", 1)[-1].strip()
        # Drop the trailing "[8086:2723] (rev 1a)" noise; the ids are shown separately.
        desc = re.sub(r"\s*\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\]", "", desc)
        desc = re.sub(r"\s*\(rev [0-9a-fA-F]+\)\s*$", "", desc).strip()
        if desc:
            names[slot] = desc
    return names


# --------------------------------------------------------------------------- #
# USB enumeration (sysfs)                                                     #
# --------------------------------------------------------------------------- #
def _usb_interface_classes(dev_dir: str) -> list[tuple[str, str]]:
    """(bInterfaceClass, bInterfaceSubClass) for each interface of a USB device.

    A device's interfaces are siblings named ``<device>:<config>.<iface>``.
    """
    parent, base = os.path.dirname(dev_dir), os.path.basename(dev_dir)
    out: list[tuple[str, str]] = []
    try:
        entries = os.listdir(parent)
    except OSError:
        return out
    for name in sorted(entries):
        if not name.startswith(base + ":"):
            continue
        cls = _read(os.path.join(parent, name, "bInterfaceClass")).lower()
        sub = _read(os.path.join(parent, name, "bInterfaceSubClass")).lower()
        if cls:
            out.append((cls, sub))
    return out


def _usb_looks_wireless(dev_dir: str) -> bool:
    """True when a USB device declares a non-Bluetooth wireless interface."""
    for cls, sub in _usb_interface_classes(dev_dir):
        if cls == _USB_CLASS_WIRELESS and sub != _USB_SUBCLASS_BLUETOOTH:
            return True
    return False


def _scan_usb(db: ChipsetDB, sysfs_root: str = SYSFS_ROOT) -> list[Adapter]:
    base = os.path.join(sysfs_root, "bus", "usb", "devices")
    adapters: list[Adapter] = []
    if not os.path.isdir(base):
        return adapters
    names = _lsusb_names()
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return adapters
    for entry in entries:
        if ":" in entry:
            continue  # an interface (1-1:1.0), not a device
        dev_dir = os.path.join(base, entry)
        vid = _hex4(_read(os.path.join(dev_dir, "idVendor")))
        pid = _hex4(_read(os.path.join(dev_dir, "idProduct")))
        if not vid or not pid or vid == _USB_ROOT_HUB_VID:
            continue
        usb_id = f"{vid}:{pid}"
        chip = db.match_usb(usb_id)
        # sysfs strings first, lsusb's nicer name when it has one.
        product = _read(os.path.join(dev_dir, "product"))
        vendor = _read(os.path.join(dev_dir, "manufacturer"))
        sysfs_desc = " ".join(p for p in (vendor, product) if p).strip()
        desc = names.get(usb_id) or sysfs_desc
        looks_wifi = (any(h in desc.lower() for h in _WIFI_HINTS)
                      or any(h in sysfs_desc.lower() for h in _WIFI_HINTS)
                      or _usb_looks_wireless(dev_dir))
        if chip is None and not looks_wifi:
            continue  # skip mice, hubs, webcams, Bluetooth radios...
        adapters.append(Adapter(
            bus=_read(os.path.join(dev_dir, "busnum")) or entry,
            device=_read(os.path.join(dev_dir, "devnum")),
            vid=vid, pid=pid, description=desc, transport="usb",
            chipset=chip, sysfs_path=os.path.realpath(dev_dir)))
    return adapters


# --------------------------------------------------------------------------- #
# PCI enumeration (sysfs)                                                     #
# --------------------------------------------------------------------------- #
def _scan_pci(db: ChipsetDB, sysfs_root: str = SYSFS_ROOT) -> list[Adapter]:
    base = os.path.join(sysfs_root, "bus", "pci", "devices")
    adapters: list[Adapter] = []
    if not os.path.isdir(base):
        return adapters
    names = _lspci_names()
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return adapters
    for slot in entries:
        dev_dir = os.path.join(base, slot)
        vid = _hex4(_read(os.path.join(dev_dir, "vendor")))
        pid = _hex4(_read(os.path.join(dev_dir, "device")))
        if not vid or not pid:
            continue
        usb_id = f"{vid}:{pid}"
        chip = db.match_usb(usb_id)
        # "0x028000" -> base class 02, subclass 80.
        raw_class = _read(os.path.join(dev_dir, "class")).lower().replace("0x", "")
        raw_class = raw_class.zfill(6)
        is_wireless = (raw_class[0:2] == _PCI_CLASS_NETWORK
                       and raw_class[2:4] == _PCI_SUBCLASS_WIRELESS)
        if chip is None and not is_wireless:
            continue  # Ethernet NICs, GPUs, bridges...
        adapters.append(Adapter(
            bus="pci", device=slot.lower(), vid=vid, pid=pid,
            description=names.get(slot.lower()) or f"PCI wireless device {usb_id}",
            transport="pci", chipset=chip, sysfs_path=os.path.realpath(dev_dir)))
    return adapters


# --------------------------------------------------------------------------- #
# Correlation                                                                 #
# --------------------------------------------------------------------------- #
# How far up the sysfs tree to walk from a netdev's device to find the adapter
# that owns it. USB needs one hop (interface dir -> device dir); the extra
# headroom covers nested cases without ever reaching a hub or PCI bridge.
_MAX_PARENT_HOPS = 4


def _correlate(adapters: list[Adapter], ifaces: list[WirelessInterface]) -> None:
    """Attach each wireless interface to the adapter that actually owns it.

    Matching is by sysfs device path, which is exact. The old code paired any
    leftover interface with the first PCI adapter it could find, so on a box
    with an internal card *and* a USB dongle the dongle's interface could be
    reported against the internal card — the adapter you were trying to fix
    would show as "Working" while the one that was working showed as dead.
    """
    by_path = {a.sysfs_path: a for a in adapters if a.sysfs_path}
    claimed: set[str] = set()

    # 1. Exact sysfs ownership: the netdev's device, or one of its parents.
    for iface in ifaces:
        path = iface.device_path
        for _ in range(_MAX_PARENT_HOPS):
            if not path or path == os.path.dirname(path):
                break
            owner = by_path.get(path)
            if owner is not None:
                if owner.interface is None:
                    owner.interface = iface
                    claimed.add(iface.name)
                break
            path = os.path.dirname(path)

    # 2. USB id match, for interfaces sysfs paths could not resolve.
    for iface in ifaces:
        if iface.name in claimed or not iface.usb_id:
            continue
        for a in adapters:
            if a.interface is None and a.usb_id == iface.usb_id:
                a.interface = iface
                claimed.add(iface.name)
                break

    # 3. Last resort, and only when it is unambiguous: exactly one adapter
    #    without an interface and exactly one interface without an adapter.
    #    Anything less certain is left unpaired rather than guessed at.
    orphan_ifaces = [i for i in ifaces if i.name not in claimed]
    orphan_adapters = [a for a in adapters if a.interface is None]
    if len(orphan_ifaces) == 1 and len(orphan_adapters) == 1:
        orphan_adapters[0].interface = orphan_ifaces[0]


# --------------------------------------------------------------------------- #
# Demo mode (non-Linux hosts only)                                            #
# --------------------------------------------------------------------------- #
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


def have_sysfs(sysfs_root: str = SYSFS_ROOT) -> bool:
    """True on a host with a real sysfs — i.e. Linux, where detection is real."""
    return os.path.isdir(os.path.join(sysfs_root, "bus"))


def detect(db: Optional[ChipsetDB] = None, allow_demo: bool = True,
           sysfs_root: str = SYSFS_ROOT) -> list[Adapter]:
    db = db or ChipsetDB.load()
    if not have_sysfs(sysfs_root):
        # No sysfs at all => not Linux. Demo data is honest here, and only here:
        # on Linux an empty result means "no Wi-Fi hardware found", which is a
        # real answer and must never be replaced with invented adapters.
        return _demo_adapters(db) if allow_demo else []

    adapters = _scan_usb(db, sysfs_root)
    adapters.extend(_scan_pci(db, sysfs_root))
    _correlate(adapters, list_wireless_interfaces(sysfs_root))
    return adapters
