"""Monitor mode + packet-injection helpers (airmon-ng / iw, aireplay-ng).

These are convenience wrappers used by the 'Test adapter' feature. They are
read-mostly: enabling monitor mode is an explicit user action in the GUI/CLI.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class CommandResult:
    ok: bool
    output: str


def _run(cmd: list[str], timeout: int = 25) -> CommandResult:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return CommandResult(p.returncode == 0, (p.stdout + p.stderr).strip())
    except FileNotFoundError:
        return CommandResult(False, f"{cmd[0]} not found")
    except subprocess.TimeoutExpired:
        return CommandResult(False, f"{cmd[0]} timed out")


def tools_present() -> dict[str, bool]:
    return {t: shutil.which(t) is not None
            for t in ("airmon-ng", "aireplay-ng", "iw", "iwconfig")}


def kill_interferers(sudo: bool = True) -> CommandResult:
    pre = ["sudo"] if sudo else []
    return _run(pre + ["airmon-ng", "check", "kill"])


def enable_monitor(interface: str, sudo: bool = True) -> CommandResult:
    pre = ["sudo"] if sudo else []
    if shutil.which("airmon-ng"):
        return _run(pre + ["airmon-ng", "start", interface])
    # Fallback to iw if aircrack-ng isn't installed.
    _run(pre + ["ip", "link", "set", interface, "down"])
    r = _run(pre + ["iw", interface, "set", "monitor", "control"])
    _run(pre + ["ip", "link", "set", interface, "up"])
    return r


def disable_monitor(interface: str, sudo: bool = True) -> CommandResult:
    pre = ["sudo"] if sudo else []
    if shutil.which("airmon-ng"):
        return _run(pre + ["airmon-ng", "stop", interface])
    _run(pre + ["ip", "link", "set", interface, "down"])
    r = _run(pre + ["iw", interface, "set", "type", "managed"])
    _run(pre + ["ip", "link", "set", interface, "up"])
    return r


def test_injection(interface: str, sudo: bool = True) -> CommandResult:
    """Runs `aireplay-ng --test` — the canonical injection self-test."""
    pre = ["sudo"] if sudo else []
    return _run(pre + ["aireplay-ng", "--test", interface], timeout=30)
