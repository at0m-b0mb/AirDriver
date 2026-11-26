"""Monitor mode + packet-injection helpers (airmon-ng / iw, aireplay-ng).

These are convenience wrappers used by the 'Test adapter' feature. They are
read-mostly: enabling monitor mode is an explicit user action in the GUI/CLI.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class CommandResult:
    ok: bool
    output: str


#: A Linux network-interface name: at most IFNAMSIZ-1 characters, and never
#: starting with '-'. The interface is typed into the GUI's combo box and passed
#: on the command line, so it is checked before it is handed to a tool running
#: under sudo — otherwise "-x" is an interface name as far as this code is
#: concerned, and airmon-ng reads it as an option.
_SAFE_IFACE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@:-]{0,14}$")


def valid_interface(name: str) -> bool:
    return bool(_SAFE_IFACE.match((name or "").strip()))


def _reject(name: str) -> CommandResult:
    return CommandResult(False, f"{name!r} is not a valid interface name "
                                "(expected something like wlan0 or wlan0mon).")


def _run(cmd: list[str], timeout: int = 25) -> CommandResult:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return CommandResult(p.returncode == 0, (p.stdout + p.stderr).strip())
    except FileNotFoundError:
        return CommandResult(False, f"{cmd[0]} not found")
    except PermissionError:
        return CommandResult(False, f"{cmd[0]} could not be executed (permission denied)")
    except subprocess.TimeoutExpired:
        return CommandResult(False, f"{cmd[0]} timed out")


def tools_present() -> dict[str, bool]:
    return {t: shutil.which(t) is not None
            for t in ("airmon-ng", "aireplay-ng", "iw", "iwconfig")}


def status() -> CommandResult:
    """Human-readable summary of every wireless interface's current mode/state —
    the quick 'am I in monitor mode?' check without needing airmon-ng."""
    from . import detector
    ifaces = detector.list_wireless_interfaces()
    if not ifaces:
        return CommandResult(False, "No wireless interfaces found. "
                             "Plug in an adapter and run: airdriver scan")
    lines = []
    for i in ifaces:
        mode = i.mode or "?"
        flag = "  ← MONITOR" if mode.lower() in ("monitor", "mesh") else ""
        lines.append(f"  {i.name:12} mode={mode:9} state={i.operstate or '?':5} "
                     f"driver={i.driver or '?'}{flag}")
    return CommandResult(True, "Wireless interfaces:\n" + "\n".join(lines))


def kill_interferers(sudo: bool = True) -> CommandResult:
    pre = ["sudo"] if sudo else []
    return _run(pre + ["airmon-ng", "check", "kill"])


def enable_monitor(interface: str, sudo: bool = True) -> CommandResult:
    if not valid_interface(interface):
        return _reject(interface)
    pre = ["sudo"] if sudo else []
    if shutil.which("airmon-ng"):
        return _run(pre + ["airmon-ng", "start", interface])
    # Fallback to iw if aircrack-ng isn't installed.
    _run(pre + ["ip", "link", "set", interface, "down"])
    r = _run(pre + ["iw", "dev", interface, "set", "monitor", "control"])
    _run(pre + ["ip", "link", "set", interface, "up"])
    return r


def disable_monitor(interface: str, sudo: bool = True) -> CommandResult:
    if not valid_interface(interface):
        return _reject(interface)
    pre = ["sudo"] if sudo else []
    if shutil.which("airmon-ng"):
        return _run(pre + ["airmon-ng", "stop", interface])
    _run(pre + ["ip", "link", "set", interface, "down"])
    r = _run(pre + ["iw", "dev", interface, "set", "type", "managed"])
    _run(pre + ["ip", "link", "set", interface, "up"])
    return r


def test_injection(interface: str, sudo: bool = True) -> CommandResult:
    """Runs `aireplay-ng --test` — the canonical injection self-test."""
    if not valid_interface(interface):
        return _reject(interface)
    pre = ["sudo"] if sudo else []
    return _run(pre + ["aireplay-ng", "--test", interface], timeout=30)
