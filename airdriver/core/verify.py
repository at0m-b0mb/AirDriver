"""Post-install verification & diagnostics.

Answers the one question that actually matters after an install:
**"is the driver really installed, loaded, and bound to the adapter?"**

The old flow happily printed "Done" even when the freshly built module never
loaded (Secure Boot, a conflicting in-kernel module, a missing firmware blob…).
This module checks each of those links in the chain and gives an honest verdict
with concrete next steps, including the relevant `dmesg` lines.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from . import detector
from .chipset_db import Chipset
from .modules import is_loaded, loaded_modules, module_available
from .system import SystemInfo


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _run(cmd: list[str], timeout: int = 12) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return 127, ""


def _maybe_sudo(cmd: list[str]) -> list[str]:
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    if is_root or not shutil.which("sudo"):
        return cmd
    return ["sudo", "-n", *cmd]   # -n: never block on a password prompt


def _norm(m: str) -> str:
    return m.replace("-", "_").lower()


def expected_modules(chip: Chipset) -> list[str]:
    """Every kernel module name this chipset could end up using."""
    mods: list[str] = []
    if chip.kernel_native and chip.kernel_native.module:
        mods.append(chip.kernel_native.module)
    for d in chip.drivers:
        if d.module:
            mods.append(d.module)
    # de-dupe, preserve order
    seen, out = set(), []
    for m in mods:
        if _norm(m) not in seen:
            seen.add(_norm(m))
            out.append(m)
    return out


def dkms_status_for(chip: Chipset) -> list[str]:
    """Lines from `dkms status` that relate to this chipset's modules."""
    rc, out = _run(["dkms", "status"])
    if rc != 0:
        return []
    names = {_norm(m) for m in expected_modules(chip)}
    # Also match the bare driver dir names (e.g. 8814au, 88x2bu).
    names |= {_norm(d.module) for d in chip.drivers if d.module}
    hits = []
    for line in out.splitlines():
        low = _norm(line)
        if any(n and n in low for n in names):
            hits.append(line.strip())
    return hits


def dmesg_driver_lines(chip: Chipset, max_lines: int = 12) -> list[str]:
    """Recent kernel-log lines relevant to this chipset / Wi-Fi driver errors."""
    rc, out = _run(_maybe_sudo(["dmesg", "--ctime"]))
    if rc != 0 or not out:
        rc, out = _run(_maybe_sudo(["dmesg"]))
    if rc != 0 or not out:
        return []
    keys = [m.lower() for m in expected_modules(chip)]
    keys += [u.replace(":", "") for u in chip.usb_ids[:6]]
    keys += [u for u in chip.usb_ids[:6]]
    error_words = ("firmware", "failed", "error", "signature", "rejected",
                   "unsigned", "taint", "denied", "cannot", "timeout")
    hits = []
    for line in out.splitlines():
        low = line.lower()
        if any(k and k in low for k in keys) or (
                "wlan" in low and any(w in low for w in error_words)):
            hits.append(line.strip())
    return hits[-max_lines:]


# --------------------------------------------------------------------------- #
# health report                                                               #
# --------------------------------------------------------------------------- #
@dataclass
class Health:
    chipset: str
    expected_modules: list[str] = field(default_factory=list)
    module_built: bool = False          # modinfo can find at least one
    loaded_module: Optional[str] = None  # an expected module currently in lsmod
    dkms_lines: list[str] = field(default_factory=list)
    interface: Optional[str] = None      # wlan iface bound to this adapter
    interface_driver: Optional[str] = None
    secure_boot: str = "unknown"
    dmesg: list[str] = field(default_factory=list)
    verdict: str = "unknown"             # working|not_loaded|secure_boot|not_built|no_iface|demo
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == "working"


def check(chip: Chipset, info: SystemInfo, usb_id: Optional[str] = None) -> Health:
    h = Health(chipset=chip.name, expected_modules=expected_modules(chip),
               secure_boot=info.secure_boot)

    if not info.is_linux:
        h.verdict = "demo"
        h.messages.append("Verification is only meaningful on Linux. On Kali/Parrot "
                          "this confirms the module is loaded and the interface is up.")
        return h

    # 1. Is at least one expected module built/available for this kernel?
    h.module_built = any(module_available(m) for m in h.expected_modules)

    # 2. Is one of them loaded right now?
    loaded = loaded_modules()
    loaded_norm = {_norm(m) for m in loaded}
    for m in h.expected_modules:
        if _norm(m) in loaded_norm:
            h.loaded_module = m
            break

    # 3. DKMS registration state.
    h.dkms_lines = dkms_status_for(chip)

    # 4. Is there a wireless interface bound to this device / driver?
    ifaces = detector.list_wireless_interfaces()
    want_ids = {usb_id} if usb_id else set(chip.usb_ids)
    drv_names = {_norm(m) for m in h.expected_modules}
    for iface in ifaces:
        if (iface.usb_id and iface.usb_id in want_ids) or \
           (iface.driver and _norm(iface.driver) in drv_names):
            h.interface = iface.name
            h.interface_driver = iface.driver
            break
    # Fallback: if exactly one new wlan exists and we just installed, take it.
    if h.interface is None and len(ifaces) == 1 and h.loaded_module:
        h.interface = ifaces[0].name
        h.interface_driver = ifaces[0].driver

    # 5. Kernel log breadcrumbs.
    h.dmesg = dmesg_driver_lines(chip)

    # --- verdict + guidance ------------------------------------------------
    if h.interface:
        h.verdict = "working"
        h.messages.append(
            f"Interface {h.interface} is present (driver: {h.interface_driver or '?'}). "
            "Bring it up and test monitor mode:")
        h.messages.append(f"    sudo ip link set {h.interface} up")
        h.messages.append(f"    sudo airmon-ng start {h.interface}")
    elif h.loaded_module and not h.interface:
        h.verdict = "no_iface"
        h.messages.append(
            f"Module '{h.loaded_module}' is loaded but no interface appeared yet.")
        h.messages.append("Unplug and re-plug the adapter, then run:  airdriver scan")
        h.messages.append("If it still doesn't show, try a different USB port "
                          "(use USB 2.0 / a powered hub for high-power cards like the AWUS1900).")
    elif h.module_built and not h.loaded_module:
        if h.secure_boot == "on":
            h.verdict = "secure_boot"
            h.messages.append(
                "The driver is built but NOT loaded — Secure Boot is ON, so the "
                "kernel refuses the unsigned module. Fix it with either:")
            h.messages.append("    sudo mokutil --disable-validation   # then reboot, follow the blue MOK screen")
            h.messages.append("  …or disable Secure Boot in your UEFI/BIOS firmware.")
        else:
            h.verdict = "not_loaded"
            h.messages.append("The driver is built but not loaded. Try:")
            h.messages.append(f"    sudo depmod -a && sudo modprobe {h.expected_modules[0]}")
            h.messages.append("If modprobe errors, the dmesg lines below explain why.")
            h.messages.append("A reboot often resolves it after a fresh DKMS install.")
    else:
        h.verdict = "not_built"
        h.messages.append(
            "No driver module was found for this kernel — the build did not complete.")
        if not info.headers_installed:
            h.messages.append(f"Kernel headers for {info.kernel_release} are MISSING — "
                              "install them and retry:  sudo apt install -y linux-headers-$(uname -r)")
        h.messages.append("Clean up and retry:  airdriver remove "
                          f"{chip.id}  &&  airdriver install {chip.id}")

    if h.dmesg:
        h.messages.append("")
        h.messages.append("Recent kernel log (dmesg):")
        h.messages += [f"    {l}" for l in h.dmesg]

    return h


def describe(h: Health) -> str:
    icon = {"working": "✓", "demo": "·"}.get(h.verdict, "✗")
    head = {
        "working":     "WORKING — driver loaded and interface present.",
        "no_iface":    "ALMOST — module loaded, but no interface yet.",
        "secure_boot": "BLOCKED — built but Secure Boot won't load it.",
        "not_loaded":  "NOT LOADED — built but the module isn't active.",
        "not_built":   "FAILED — no driver module was built for this kernel.",
        "demo":        "Demo mode — run on Kali/Parrot to verify for real.",
        "unknown":     "Unknown state.",
    }.get(h.verdict, h.verdict)
    lines = [f"{icon} {head}", ""]
    lines.append(f"  Chipset        {h.chipset}")
    lines.append(f"  Module built   {'yes' if h.module_built else 'no'}")
    lines.append(f"  Module loaded  {h.loaded_module or 'no'}")
    if h.dkms_lines:
        lines.append(f"  DKMS           {h.dkms_lines[0]}")
    lines.append(f"  Interface      {h.interface or 'none yet'}"
                 + (f"  (driver: {h.interface_driver})" if h.interface_driver else ""))
    lines.append(f"  Secure Boot    {h.secure_boot}")
    if h.messages:
        lines.append("")
        lines += [f"  {m}" if m else "" for m in h.messages]
    return "\n".join(lines)
