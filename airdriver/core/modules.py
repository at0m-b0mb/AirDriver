"""Kernel-module helpers: what's loaded, blacklisting conflicts, (un)loading."""

from __future__ import annotations

import os
import subprocess

BLACKLIST_FILE = "/etc/modprobe.d/airdriver-blacklist.conf"


def loaded_modules() -> set[str]:
    try:
        out = subprocess.run(["lsmod"], capture_output=True, text=True, timeout=8).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    mods = set()
    for line in out.splitlines()[1:]:
        parts = line.split()
        if parts:
            mods.add(parts[0])
    return mods


def is_loaded(module: str) -> bool:
    return module.replace("-", "_") in {m.replace("-", "_") for m in loaded_modules()}


def module_available(module: str) -> bool:
    """True if the module exists for the running kernel (modinfo finds it)."""
    try:
        rc = subprocess.run(["modinfo", module], capture_output=True,
                            text=True, timeout=8).returncode
        return rc == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def blacklist_snippet(modules: list[str]) -> str:
    lines = ["# Written by AirDriver — prevents in-kernel modules from grabbing",
             "# an adapter that should use the installed out-of-tree driver.\n"]
    for m in modules:
        lines.append(f"blacklist {m}")
    return "\n".join(lines) + "\n"
