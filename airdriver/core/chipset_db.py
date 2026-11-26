"""Loads and queries the chipset database (data/chipsets.json).

The database is the brain of AirDriver: it maps a USB ``vid:pid`` to a chipset
and to an ordered list of ways to get a working driver for it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path
from typing import Optional


class DatabaseError(RuntimeError):
    """The chipset database is missing, unreadable, or not a database."""


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

    @classmethod
    def from_dict(cls, d: dict) -> "KernelNative":
        # Only the fields we know about: a database that grows a new key must
        # not stop the whole tool from loading with a TypeError.
        return cls(module=str(d.get("module", "")),
                   min_kernel=str(d.get("min_kernel", "0")),
                   recommended_kernel=str(d.get("recommended_kernel", "")),
                   firmware=d.get("firmware"))


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
    #: True when an in-kernel driver exists but the out-of-tree one is what has
    #: the injection track record. Without it, the mere existence of
    #: ``kernel_native`` makes AirDriver skip the build — the right call for a
    #: laptop card and the wrong one for an injection adapter.
    prefer_out_of_tree: bool = False

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
            prefer_out_of_tree=bool(d.get("prefer_out_of_tree", False)),
            adapters=tuple(d.get("adapters", ())),
            usb_ids=tuple(s.lower() for s in d.get("usb_ids", ())),
            drivers=tuple(DriverOption.from_dict(x) for x in d.get("drivers", ())),
            blacklist=tuple(d.get("blacklist", ())),
            kernel_native=KernelNative.from_dict(kn) if kn else None,
        )


# --------------------------------------------------------------------------- #
# Load-time quarantine                                                        #
# --------------------------------------------------------------------------- #
# `problems()` is the *review* gate: it runs in CI, so a pull request carrying a
# shell metacharacter never merges. It is not a *runtime* gate, because nothing
# called it before the values were used — and the database on disk is a plain
# JSON file that anything with write access to the install can edit, that a user
# may hand-edit to add their own adapter, and that `--db` can point elsewhere.
#
# So the same rules are applied again at load, and anything that fails them is
# dropped rather than handed to a root shell. Dropping (not refusing the whole
# file) is deliberate: one malformed entry must not take Wi-Fi away from a
# machine that has no other way to get online. Every drop is recorded in
# ``load_warnings`` so `airdriver doctor`, `db --check` and the GUI can say so
# out loud instead of silently doing less than the file asked for.
def sanitize(chipsets: list[Chipset]) -> tuple[list[Chipset], list[str]]:
    """Return (chipsets with every unsafe value removed, warnings)."""
    warnings: list[str] = []
    out: list[Chipset] = []
    for c in chipsets:
        changed = False

        blacklist = tuple(m for m in c.blacklist if SAFE_MODULE.match(m or ""))
        if len(blacklist) != len(c.blacklist):
            warnings.append(f"{c.id}: dropped unsafe blacklist entry")
            changed = True

        kn = c.kernel_native
        if kn is not None and not SAFE_MODULE.match(kn.module or ""):
            warnings.append(f"{c.id}: dropped unsafe kernel_native module {kn.module!r}")
            kn = None
            changed = True

        drivers = []
        for d in c.drivers:
            bad = None
            if d.module and not SAFE_MODULE.match(d.module):
                bad = f"module {d.module!r}"
            elif d.package and not SAFE_PACKAGE.match(d.package):
                bad = f"apt package {d.package!r}"
            elif d.firmware_pkg and not SAFE_PACKAGE.match(d.firmware_pkg):
                bad = f"firmware package {d.firmware_pkg!r}"
            elif d.repo and not SAFE_REPO.match(d.repo):
                bad = f"repo {d.repo!r}"
            elif d.path and not _safe_rel_path(d.path):
                bad = f"offline path {d.path!r}"
            if bad is None:
                drivers.append(d)
            else:
                warnings.append(f"{c.id}: dropped driver option with unsafe {bad}")
                changed = True

        out.append(replace(c, blacklist=blacklist, kernel_native=kn,
                           drivers=tuple(drivers)) if changed else c)
    return out, warnings


class ChipsetDB:
    def __init__(self, chipsets: list[Chipset], meta: dict,
                 load_warnings: Optional[list[str]] = None,
                 raw_chipsets: Optional[list[Chipset]] = None):
        self._chipsets = chipsets
        self._by_usb: dict[str, Chipset] = {}
        for c in chipsets:
            for uid in c.usb_ids:
                self._by_usb[uid] = c
        self.meta = meta
        #: Values the loader refused to pass on (see ``sanitize``). Empty for
        #: the shipped database — a non-empty list means the file was edited.
        self.load_warnings: list[str] = list(load_warnings or ())
        #: The entries exactly as the file spelled them, before the loader
        #: dropped anything. `problems()` checks these, so `db --check` still
        #: reports a value that the runtime quietly refused to use.
        self._for_check: list[Chipset] = list(raw_chipsets or chipsets)

    # ---- queries -----------------------------------------------------------
    def all(self) -> list[Chipset]:
        return list(self._chipsets)

    def match_usb(self, usb_id: str) -> Optional[Chipset]:
        return self._by_usb.get(usb_id.lower().strip())

    def contested(self, usb_id: str) -> Optional[dict]:
        """Why this ``vid:pid`` is deliberately *not* in any chipset.

        Some ids are claimed by two or more kernel drivers, because two
        different chips shipped behind the same id. Guessing is the worst
        option available: the install blacklists the other driver's module, so
        a wrong guess leaves the adapter with no driver at all. These ids are
        therefore absent from every family, and this is the explanation that
        gets shown instead of a bare "unknown".
        """
        entry = (self.meta.get("contested_ids") or {}).get(usb_id.lower().strip())
        return entry if isinstance(entry, dict) else None

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
        for c in self._for_check:
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
        for c in self._for_check:
            seen_cid[c.id] = seen_cid.get(c.id, 0) + 1
        for cid, n in seen_cid.items():
            if n > 1:
                out.append(f"duplicate chipset id '{cid}' ({n} entries)")

        # Every usb_id must be unique across the whole file, else lookups are
        # ambiguous and the last-loaded chipset silently wins.
        owner: dict[str, str] = {}
        for c in self._for_check:
            for uid in c.usb_ids:
                if not _id_re.match(uid):
                    out.append(f"{c.id}: malformed usb_id '{uid}' (want lowercase vid:pid)")
                if uid in owner and owner[uid] != c.id:
                    out.append(f"usb_id '{uid}' claimed by both '{owner[uid]}' and '{c.id}'")
                owner[uid] = c.id

        # Driver options must be sane and priorities unique within a chipset.
        for c in self._for_check:
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
    def load(cls, path: Optional[Path] = None, *, strict: bool = False) -> "ChipsetDB":
        """Load the database, dropping any value that is not safe to execute.

        ``strict=True`` raises instead of dropping — used by the test-suite and
        by ``db --check`` so a problem is loud at review time.
        """
        src = Path(path) if path is not None else data_path("chipsets.json")
        try:
            raw = json.loads(src.read_text())
        except FileNotFoundError:
            raise DatabaseError(f"chipset database not found at {src}") from None
        except (OSError, UnicodeDecodeError) as exc:
            raise DatabaseError(f"could not read {src}: {exc}") from None
        except json.JSONDecodeError as exc:
            raise DatabaseError(f"{src} is not valid JSON: {exc}") from None
        if not isinstance(raw, dict) or not isinstance(raw.get("chipsets", []), list):
            raise DatabaseError(f"{src} is not an AirDriver chipset database")
        try:
            chipsets = [Chipset.from_dict(c) for c in raw.get("chipsets", [])]
        except (KeyError, TypeError, ValueError) as exc:
            raise DatabaseError(f"{src} has a malformed chipset entry: {exc}") from None
        meta = {k: v for k, v in raw.items() if k != "chipsets"}
        clean, warnings = sanitize(chipsets)
        if warnings and strict:
            raise DatabaseError("unsafe values in the chipset database: "
                                + "; ".join(warnings))
        return cls(clean, meta, warnings, raw_chipsets=chipsets)
