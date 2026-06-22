"""One-shot diagnostic snapshot — the single block of text to share when a
driver "installed" but the adapter still doesn't work.

It gathers everything that decides whether a Wi-Fi adapter actually works on
Linux: kernel/headers, Secure Boot, rfkill, the USB/PCI device list, the live
wireless interfaces and their bound drivers, loaded modules, DKMS state, and the
tail of the kernel log — plus AirDriver's own verdict per detected adapter.
"""

from __future__ import annotations

import datetime
import os
import subprocess

from . import detector, system, verify
from .chipset_db import ChipsetDB


def _run(cmd: list[str], timeout: int = 12) -> str:
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    if not is_root and cmd and cmd[0] == "dmesg":   # dmesg is often root-only; rfkill isn't
        import shutil
        if shutil.which("sudo"):
            cmd = ["sudo", "-n", *cmd]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return ""


def _section(title: str) -> str:
    return f"\n── {title} " + "─" * max(2, 56 - len(title))


def _tail(text: str, n: int) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    return "\n".join(lines[-n:]) if lines else "(none)"


def snapshot(db: ChipsetDB | None = None) -> str:
    from .. import __version__, __codename__
    db = db or ChipsetDB.load()
    info = system.gather()
    out: list[str] = []

    out.append("=" * 64)
    out.append(f"  AirDriver diagnostic — v{__version__} ({__codename__})")
    out.append(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out.append("=" * 64)
    if info.is_linux and not info.is_root:
        out.append("  TIP: run as root for full rfkill/dmesg output:  sudo airdriver diagnose")

    # --- system ------------------------------------------------------------
    out.append(_section("System"))
    headers_build = os.path.isdir(f"/lib/modules/{info.kernel_release}/build")
    out += [
        f"  OS / distro    {info.distro_name}",
        f"  Kernel         {info.kernel_release} ({info.arch})",
        f"  Running as     {'root' if info.is_root else 'user (installs need sudo)'}",
        f"  Internet       {'yes' if info.has_internet else 'no'}",
        f"  Kernel headers {'present' if info.headers_installed else 'MISSING'} "
        f"(build tree for running kernel: {'yes' if headers_build else 'NO — DKMS will fail'})",
        f"  DKMS           {'installed' if info.dkms_installed else 'MISSING'}",
        f"  Build tools    {'installed' if info.build_tools else 'MISSING'}",
        f"  Secure Boot    {info.secure_boot}"
        + ("   <-- unsigned DKMS modules will be REFUSED" if info.secure_boot == "on" else ""),
    ]

    # --- rfkill ------------------------------------------------------------
    out.append(_section("RF-kill (radio blocks)"))
    blocked = verify.rfkill_blocked()
    rk = _run(["rfkill", "list"])
    out.append("  " + ("\n  ".join(rk.splitlines()) if rk else "(rfkill unavailable)"))
    if blocked:
        out.append(f"  >>> BLOCKED: {', '.join(blocked)} — run: sudo rfkill unblock all")

    # --- adapters ----------------------------------------------------------
    out.append(_section("Detected adapters"))
    adapters = detector.detect(db)
    if not adapters:
        out.append("  (none detected — is it plugged in? try a different USB port)")
    for a in adapters:
        tag = a.chipset.name if a.chipset else "UNKNOWN (not in database)"
        out.append(f"  • {a.usb_id}  {a.transport.upper()}  →  {tag}"
                   + ("  [demo]" if a.is_demo else ""))
        if a.interface:
            out.append(f"      iface: {a.interface.name}  driver: {a.interface.driver or '?'}"
                       f"  mode: {a.interface.mode or '?'}  state: {a.interface.operstate or '?'}")

    # --- wireless interfaces ----------------------------------------------
    out.append(_section("Wireless interfaces (sysfs)"))
    ifaces = detector.list_wireless_interfaces()
    if not ifaces:
        out.append("  (no wireless interfaces present)")
    for i in ifaces:
        out.append(f"  {i.name:10} driver={i.driver or '?':14} mode={i.mode or '?':9} "
                   f"state={i.operstate or '?':5} usb={i.usb_id or '-'}")

    # --- modules / dkms ----------------------------------------------------
    out.append(_section("Loaded Wi-Fi modules"))
    lsmod = _run(["lsmod"])
    wifi = [l for l in lsmod.splitlines()
            if any(k in l.lower() for k in (
                "cfg80211", "mac80211", "rtw", "rtl", "88xx", "8812", "8814", "8821",
                "8188", "8192", "8723", "8852", "88x2", "mt76", "mt79", "ath9k",
                "carl9170", "rt2800", "rt2x00", "iwlwifi", "brcm"))]
    out.append("  " + ("\n  ".join(wifi) if wifi else "(no Wi-Fi modules loaded)"))

    out.append(_section("DKMS status"))
    dkms = _run(["dkms", "status"])
    out.append("  " + ("\n  ".join(dkms.splitlines()) if dkms else "(dkms not installed / nothing registered)"))

    # --- kernel log --------------------------------------------------------
    out.append(_section("Kernel log — Wi-Fi / driver (tail)"))
    dmesg = _run(["dmesg", "--ctime"]) or _run(["dmesg"])
    wlog = [l for l in dmesg.splitlines() if any(k in l.lower() for k in (
        "wlan", "cfg80211", "rtw", "rtl8", "88xx", "8812", "8814", "8821", "8188",
        "8192", "8723", "8852", "mt76", "ath9k", "carl9170", "rt2800", "iwlwifi",
        "firmware", "usb 1-", "usb 2-", "secure boot", "module verification",
        "unsigned"))]
    out.append("  " + (("\n  ".join(wlog[-25:])) if wlog else "(no relevant kernel log lines — run as root for dmesg)"))

    # --- per-adapter verdict ----------------------------------------------
    out.append(_section("AirDriver verdict per known adapter"))
    known = [a for a in adapters if a.chipset]
    if not known:
        out.append("  (no recognised adapter to verify)")
    for a in known:
        h = verify.check(a.chipset, info, usb_id=a.usb_id)
        out.append(f"  • {a.chipset.name}: {h.verdict.upper()}")
        for m in h.messages:
            if m and not m.startswith("    "):
                out.append(f"      - {m}")

    out.append("\n" + "=" * 64)
    out.append("  Share everything above when asking for help.")
    out.append("=" * 64)
    return "\n".join(out)
