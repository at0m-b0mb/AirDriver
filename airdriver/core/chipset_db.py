"""Loads and queries the chipset database (data/chipsets.json).

The database is the brain of AirDriver: it maps a USB ``vid:pid`` to a chipset
and to an ordered list of ways to get a working driver for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Optional


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

    # ---- loading -----------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ChipsetDB":
        if path is not None:
            raw = json.loads(Path(path).read_text())
        else:
            with resources.files("airdriver.data").joinpath("chipsets.json").open() as fh:
                raw = json.load(fh)
        chipsets = [Chipset.from_dict(c) for c in raw.get("chipsets", [])]
        meta = {k: v for k, v in raw.items() if k != "chipsets"}
        return cls(chipsets, meta)
