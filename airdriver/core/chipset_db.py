"""Loads and queries the chipset database (data/chipsets.json).

The database is the brain of AirDriver: it maps a USB ``vid:pid`` to a chipset
and to an ordered list of ways to get a working driver for it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
# What a database value is allowed to contain                                 #
# --------------------------------------------------------------------------- #
# These fields are interpolated into commands that run as root, so they are
# whitelisted by shape rather than scanned for "bad" characters — a blocklist
# always misses something. Kept deliberately tight: real kernel modules, Debian
# package names and driver repos all fit comfortably inside them.
SAFE_MODULE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Debian policy: lowercase start, then alphanumerics and + - . (we also tolerate
# uppercase, which some third-party packages use).
SAFE_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._-]{0,96}$")
# https only. git's `ext::` transport runs an arbitrary command, and `git://`
# and local paths are not something a driver source should ever need.
SAFE_REPO = re.compile(r"^https://[A-Za-z0-9._~\-]+(?::\d+)?(?:/[A-Za-z0-9._~\-]+)*/?$")


def _safe_rel_path(p: str) -> bool:
    """A bundled-driver path: relative, under ``data/``, no traversal."""
    if not p or p.startswith("/") or "\\" in p:
        return False
    parts = p.split("/")
    if any(seg in ("", ".", "..") for seg in parts):
        return False
    return all(re.fullmatch(r"[A-Za-z0-9._-]{1,64}", seg) for seg in parts)


def data_path(*parts: str) -> Path:
    """Resolve a path inside ``airdriver/data/``.

    Deliberately filesystem-first: ``resources.files("airdriver.data")`` raises
    on Python 3.9 because ``data/`` is a plain directory (a namespace package,
    whose ``origin`` is None), and 3.9 is still shipped by distros we target.
    The importlib branch is the fallback for installs where the package isn't a
    real directory on disk (zipped/frozen).
    """
    local = Path(__file__).resolve().parent.parent / "data"
    for p in parts:
        local = local / p
    if local.exists():
        return local
    base = Path(str(resources.files("airdriver"))) / "data"
    for p in parts:
        base = base / p
    return base


@dataclass(frozen=True)
class DriverOption:
    """One way to obtain a working driver, in ``priority`` order (1 = best)."""

    method: str  # "kernel_native" | "apt" | "dkms_git" | "offline"
    priority: int = 99
    package: Optional[str] = None       # apt package name
    repo: Optional[str] = None          # git URL for dkms_git
    path: Optional[str] = None          # relative path under data/ for offline
    module: Optional[str] = None        # kernel module name once built/loaded
    distro: tuple[str, ...] = ()        # distros this apt package exists on
    firmware_pkg: Optional[str] = None  # firmware package for in-kernel drivers

    @classmethod
    def from_dict(cls, d: dict) -> "DriverOption":
        return cls(
            method=d["method"],
            priority=int(d.get("priority", 99)),
            package=d.get("package"),
            repo=d.get("repo"),
            path=d.get("path"),
            module=d.get("module"),
            distro=tuple(d.get("distro", ())),
            firmware_pkg=d.get("firmware_pkg"),
        )


@dataclass(frozen=True)
class KernelNative:
    """Describes the in-kernel driver, so AirDriver can skip a needless build."""

    module: str
    min_kernel: str = "0"
    recommended_kernel: str = ""
    firmware: Optional[str] = None


@dataclass(frozen=True)
class Chipset:
    id: str
    name: str
    vendor: str
    wifi: str
    band: str
    monitor_mode: bool
    injection: bool
    injection_quality: str
    notes: str
    adapters: tuple[str, ...]
    usb_ids: tuple[str, ...]
    drivers: tuple[DriverOption, ...]
    blacklist: tuple[str, ...]
    kernel_native: Optional[KernelNative] = None

    @property
    def capability_summary(self) -> str:
        bits = []
        bits.append("Monitor ✓" if self.monitor_mode else "Monitor ✗")
        bits.append("Injection ✓" if self.injection else "Injection ✗")
        return "  ".join(bits)

    def best_drivers(self) -> list[DriverOption]:
        return sorted(self.drivers, key=lambda d: d.priority)

    @classmethod
    def from_dict(cls, d: dict) -> "Chipset":
        kn = d.get("kernel_native")
        return cls(
            id=d["id"],
            name=d["name"],
            vendor=d.get("vendor", "Unknown"),
            wifi=d.get("wifi", ""),
            band=d.get("band", ""),
            monitor_mode=bool(d.get("monitor_mode", False)),
            injection=bool(d.get("injection", False)),
            injection_quality=d.get("injection_quality", "unknown"),
            notes=d.get("notes", ""),
            adapters=tuple(d.get("adapters", ())),
            usb_ids=tuple(s.lower() for s in d.get("usb_ids", ())),
            drivers=tuple(DriverOption.from_dict(x) for x in d.get("drivers", ())),
            blacklist=tuple(d.get("blacklist", ())),
            kernel_native=KernelNative(**kn) if kn else None,
        )


class ChipsetDB:
    def __init__(self, chipsets: list[Chipset], meta: dict):
        self._chipsets = chipsets
        self._by_usb: dict[str, Chipset] = {}
        for c in chipsets:
            for uid in c.usb_ids:
                self._by_usb[uid] = c
        self.meta = meta

    # ---- queries -----------------------------------------------------------
    def all(self) -> list[Chipset]:
        return list(self._chipsets)

    def match_usb(self, usb_id: str) -> Optional[Chipset]:
        return self._by_usb.get(usb_id.lower().strip())

    def get(self, chipset_id: str) -> Optional[Chipset]:
        return next((c for c in self._chipsets if c.id == chipset_id), None)

    def __len__(self) -> int:
        return len(self._chipsets)

    def usb_id_count(self) -> int:
        return sum(len(c.usb_ids) for c in self._chipsets)

    # ---- integrity ---------------------------------------------------------
    def problems(self) -> list[str]:
        """Self-consistency check for the database. Returns a list of human
        readable problems (empty == healthy). Used by ``airdriver db --check``
        and the test-suite so a mistake like the same ``vid:pid`` landing in two
        chipsets (which silently mis-identifies hardware) can never ship again.
        """
        valid_methods = {"kernel_native", "apt", "dkms_git", "offline"}
        _id_re = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
        out: list[str] = []

        # --- the database is executable content ----------------------------
        # Every one of these values ends up inside a command AirDriver runs as
        # root, so the file is not merely data: a chipset entry is a small
        # program. Contributions arrive by pull request, which makes this the
        # supply-chain gate — `airdriver db --check` runs in CI, so a value
        # carrying shell metacharacters is rejected at review time rather than
        # executed on a user's machine. (Call sites also shlex-quote these, so a
        # hand-edited database still can't break out; this stops it earlier.)
        for c in self._chipsets:
            for m in c.blacklist:
                if not SAFE_MODULE.match(m or ""):
                    out.append(f"{c.id}: unsafe blacklist module {m!r} "
                               "(want letters, digits, '_' or '-')")
            kn = c.kernel_native
            if kn is not None and not SAFE_MODULE.match(kn.module or ""):
                out.append(f"{c.id}: unsafe kernel_native module {kn.module!r}")
            for d in c.drivers:
                if d.module and not SAFE_MODULE.match(d.module):
                    out.append(f"{c.id}: unsafe driver module {d.module!r}")
                if d.package and not SAFE_PACKAGE.match(d.package):
                    out.append(f"{c.id}: unsafe apt package {d.package!r}")
                if d.firmware_pkg and not SAFE_PACKAGE.match(d.firmware_pkg):
                    out.append(f"{c.id}: unsafe firmware package {d.firmware_pkg!r}")
                if d.repo and not SAFE_REPO.match(d.repo):
                    # git's ext:: transport executes a command, so the scheme is
                    # pinned to https rather than merely scanned for metacharacters.
                    out.append(f"{c.id}: unsafe repo {d.repo!r} (want an https:// URL)")
                if d.path and not _safe_rel_path(d.path):
                    out.append(f"{c.id}: unsafe offline path {d.path!r} "
                               "(want a relative path under data/, no '..')")

        # Unique chipset ids.
        seen_cid: dict[str, int] = {}
        for c in self._chipsets:
            seen_cid[c.id] = seen_cid.get(c.id, 0) + 1
        for cid, n in seen_cid.items():
            if n > 1:
                out.append(f"duplicate chipset id '{cid}' ({n} entries)")

        # Every usb_id must be unique across the whole file, else lookups are
        # ambiguous and the last-loaded chipset silently wins.
        owner: dict[str, str] = {}
        for c in self._chipsets:
            for uid in c.usb_ids:
                if not _id_re.match(uid):
                    out.append(f"{c.id}: malformed usb_id '{uid}' (want lowercase vid:pid)")
                if uid in owner and owner[uid] != c.id:
                    out.append(f"usb_id '{uid}' claimed by both '{owner[uid]}' and '{c.id}'")
                owner[uid] = c.id

        # Driver options must be sane and priorities unique within a chipset.
        for c in self._chipsets:
            if not c.drivers:
                out.append(f"{c.id}: no driver options")
            prios: dict[int, int] = {}
            for d in c.drivers:
                if d.method not in valid_methods:
                    out.append(f"{c.id}: unknown driver method '{d.method}'")
                if d.method == "apt" and not d.package:
                    out.append(f"{c.id}: apt driver without a package name")
                if d.method == "dkms_git" and not d.repo:
                    out.append(f"{c.id}: dkms_git driver without a repo")
                if d.method == "offline" and not d.path:
                    out.append(f"{c.id}: offline driver without a path")
                prios[d.priority] = prios.get(d.priority, 0) + 1
            for p, n in prios.items():
                if n > 1:
                    out.append(f"{c.id}: {n} driver options share priority {p}")

        return out

    # ---- loading -----------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ChipsetDB":
        if path is not None:
            raw = json.loads(Path(path).read_text())
        else:
            raw = json.loads(data_path("chipsets.json").read_text())
        chipsets = [Chipset.from_dict(c) for c in raw.get("chipsets", [])]
        meta = {k: v for k, v in raw.items() if k != "chipsets"}
        return cls(chipsets, meta)
