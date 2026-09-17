"""Turn an unknown adapter into a ready-to-file report.

The chipset database only gets better if the adapters it *doesn't* know come
back to the project. Asking people to hand-assemble `lsusb`, kernel version and
`dmesg` output is how that never happens — so AirDriver assembles the whole
report itself and hands over a pre-filled GitHub issue link.

Nothing is ever sent automatically: this builds text and a URL, the user reads
it and decides whether to open it. That matters because the report contains
details about their machine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass

from . import detector
from .chipset_db import ChipsetDB
from .system import SystemInfo

REPO = "https://github.com/at0m-b0mb/AirDriver"
ISSUE_NEW = f"{REPO}/issues/new"
# Keep the body well under GitHub's URL limit.
_MAX_BODY = 5500


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return ""


def _lsusb_line(usb_id: str) -> str:
    for line in _run(["lsusb"]).splitlines():
        if usb_id.lower() in line.lower():
            return line.strip()
    return ""


def _lsusb_verbose(usb_id: str) -> str:
    """iManufacturer / iProduct / bcdDevice tell a maintainer which silicon
    revision this is — often the difference between two similar chipsets."""
    vid, _, pid = usb_id.partition(":")
    out = _run(["lsusb", "-v", "-d", f"{vid}:{pid}"], timeout=15)
    if not out:
        return ""
    keep = ("idVendor", "idProduct", "bcdDevice", "iManufacturer",
            "iProduct", "bDeviceClass", "bInterfaceClass")
    lines = [l.strip() for l in out.splitlines() if any(k in l for k in keep)]
    return "\n".join(dict.fromkeys(lines))[:900]


# Descriptor attributes worth reporting. `serial` is deliberately absent: this
# report is destined for a public GitHub issue, and a device serial number
# identifies one physical adapter (and, with it, its owner).
_SYSFS_DEVICE_ATTRS = ("idVendor", "idProduct", "bcdDevice", "manufacturer",
                       "product", "bDeviceClass", "bDeviceSubClass",
                       "bNumInterfaces", "speed", "version")
_SYSFS_IFACE_ATTRS = ("bInterfaceClass", "bInterfaceSubClass", "bInterfaceProtocol")


def _sysfs_descriptors(usb_id: str, sysfs_root: str = detector.SYSFS_ROOT) -> str:
    """USB descriptors read straight from sysfs, for hosts without usbutils.

    This is what keeps `airdriver contribute` useful on a minimal Kali/Parrot
    install. Without it the report for an unknown adapter arrives carrying no
    descriptors at all — which are precisely the fields a maintainer needs in
    order to add the chipset to the database.
    """
    base = os.path.join(sysfs_root, "bus", "usb", "devices")
    if not os.path.isdir(base):
        return ""
    want_vid, _, want_pid = usb_id.lower().partition(":")
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return ""
    for entry in entries:
        if ":" in entry:
            continue
        dev = os.path.join(base, entry)
        vid = detector._hex4(detector._read(os.path.join(dev, "idVendor")))
        pid = detector._hex4(detector._read(os.path.join(dev, "idProduct")))
        if vid != want_vid or pid != want_pid:
            continue
        lines = [f"{entry}:"]
        for attr in _SYSFS_DEVICE_ATTRS:
            val = detector._read(os.path.join(dev, attr))
            if val:
                lines.append(f"  {attr:<16} {val}")
        for iface_name in sorted(e for e in entries if e.startswith(entry + ":")):
            idir = os.path.join(base, iface_name)
            vals = [(a, detector._read(os.path.join(idir, a))) for a in _SYSFS_IFACE_ATTRS]
            vals = [(a, v) for a, v in vals if v]
            if vals:
                lines.append(f"  interface {iface_name}:")
                lines += [f"    {a:<20} {v}" for a, v in vals]
        return "\n".join(lines)[:900]
    return ""


def _dmesg_for(usb_id: str) -> str:
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    cmd = ["dmesg"]
    if not is_root and shutil.which("sudo"):
        cmd = ["sudo", "-n", "dmesg"]
    out = _run(cmd, timeout=12)
    if not out:
        return ""
    vid, _, pid = usb_id.partition(":")
    keys = (f"{vid}:{pid}", f"idVendor={vid}", f"idProduct={pid}", "usb ", "wlan")
    hits = [l.strip() for l in out.splitlines() if any(k in l.lower() for k in keys)]
    return "\n".join(hits[-20:])[:1500]


@dataclass
class Report:
    usb_id: str
    title: str
    body: str

    @property
    def url(self) -> str:
        q = urllib.parse.urlencode({
            "template": "adapter.yml",
            "title": self.title,
            "labels": "new-adapter",
            "usb_id": self.usb_id,
            "details": self.body[:_MAX_BODY],
        })
        return f"{ISSUE_NEW}?{q}"

    @property
    def short_url(self) -> str:
        """Fallback when the full URL is unwieldy — a blank issue, body pasted
        by the user from the printed report."""
        return f"{ISSUE_NEW}?labels=new-adapter&title={urllib.parse.quote(self.title)}"


def build(adapter, info: SystemInfo, db: ChipsetDB) -> Report:
    """Assemble the report for one adapter (known or not)."""
    usb_id = adapter.usb_id
    desc = adapter.description or "(no description)"
    chip = adapter.chipset
    iface = adapter.interface

    lines = [
        "### Adapter",
        "",
        f"- **USB/PCI ID:** `{usb_id}`",
        f"- **Reported name:** {desc}",
        f"- **Transport:** {adapter.transport}",
        f"- **AirDriver recognises it:** {'yes — ' + chip.name if chip else '**no**'}",
    ]
    if iface and iface.name:
        lines.append(f"- **Interface:** `{iface.name}` (driver: `{iface.driver or 'none'}`)")
    else:
        lines.append("- **Interface:** none — no driver is bound")

    lines += [
        "",
        "### System",
        "",
        f"- **Distro:** {info.distro_name}",
        f"- **Kernel:** `{info.kernel_release}` ({info.arch})",
        f"- **Secure Boot:** {info.secure_boot}",
        f"- **AirDriver DB:** {len(db)} families / {db.usb_id_count()} IDs",
    ]

    lsusb = _lsusb_line(usb_id)
    if lsusb:
        lines += ["", "### lsusb", "", "```", lsusb, "```"]
    verbose = _lsusb_verbose(usb_id)
    if verbose:
        lines += ["", "<details><summary>lsusb -v (descriptors)</summary>", "",
                  "```", verbose, "```", "", "</details>"]
    elif not lsusb:
        # No usbutils on this box — read the same descriptors out of sysfs so
        # the report is still actionable.
        sysfs = _sysfs_descriptors(usb_id)
        if sysfs:
            lines += ["", "<details><summary>sysfs descriptors (usbutils not installed)"
                      "</summary>", "", "```", sysfs, "```", "", "</details>"]
    dmesg = _dmesg_for(usb_id)
    if dmesg:
        lines += ["", "<details><summary>dmesg</summary>", "",
                  "```", dmesg, "```", "", "</details>"]

    lines += [
        "",
        "### What I know about this adapter",
        "",
        "<!-- If you know the chipset (from the vendor page, the FCC ID, or a "
        "sticker inside the case), please say so — that's the one thing "
        "AirDriver can't work out on its own. -->",
        "",
    ]

    name = chip.name if chip else desc
    title = f"[adapter] {usb_id} — {name}"[:120]
    return Report(usb_id=usb_id, title=title, body="\n".join(lines))
