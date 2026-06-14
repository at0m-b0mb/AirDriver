"""Builds and saves diagnostic reports — handy for forums/bug reports and for
the GUI's 'Export report' button."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

from .detector import Adapter
from .system import SystemInfo
from ..version import __version__


def report_dir() -> Path:
    d = Path(os.path.expanduser("~/.airdriver/reports"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _adapter_dict(a: Adapter) -> dict:
    return {
        "usb_id": a.usb_id,
        "description": a.description,
        "transport": a.transport,
        "chipset": a.chipset.name if a.chipset else None,
        "chipset_id": a.chipset.id if a.chipset else None,
        "monitor_mode": a.chipset.monitor_mode if a.chipset else None,
        "injection": a.chipset.injection if a.chipset else None,
        "interface": a.interface.name if a.interface else None,
        "driver_loaded": a.interface.driver if a.interface else None,
        "status": a.status,
    }


def build(sysinfo: SystemInfo, adapters: list[Adapter], log: str = "") -> dict:
    return {
        "airdriver_version": __version__,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "system": asdict(sysinfo) if is_dataclass(sysinfo) else {},
        "blockers": sysinfo.blockers(),
        "adapters": [_adapter_dict(a) for a in adapters],
        "install_log": log,
    }


def to_markdown(rep: dict) -> str:
    s = rep["system"]
    lines = [
        f"# AirDriver report — {rep['generated']}",
        f"*AirDriver {rep['airdriver_version']} on {platform.system()}*",
        "",
        "## System",
        f"- Distro: **{s.get('distro_name')}**  ·  Kernel: `{s.get('kernel_release')}`  ·  Arch: {s.get('arch')}",
        f"- Headers: {'✓' if s.get('headers_installed') else '✗'} "
        f"· DKMS: {'✓' if s.get('dkms_installed') else '✗'} "
        f"· Build tools: {'✓' if s.get('build_tools') else '✗'} "
        f"· Secure Boot: {s.get('secure_boot')}",
        f"- Internet: {'✓' if s.get('has_internet') else '✗'} · Root: {'✓' if s.get('is_root') else '✗'}",
    ]
    if rep["blockers"]:
        lines += ["", "## ⚠ Blockers"] + [f"- {b}" for b in rep["blockers"]]
    lines += ["", "## Adapters"]
    if not rep["adapters"]:
        lines.append("- None detected.")
    for a in rep["adapters"]:
        lines.append(f"- **{a['chipset'] or a['description']}** (`{a['usb_id']}`) — {a['status']}")
        if a["chipset"]:
            lines.append(f"  - Monitor: {a['monitor_mode']} · Injection: {a['injection']}")
    if rep.get("install_log"):
        lines += ["", "## Install log", "```", rep["install_log"], "```"]
    return "\n".join(lines) + "\n"


def save(rep: dict, fmt: str = "both") -> list[Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out: list[Path] = []
    if fmt in ("json", "both"):
        p = report_dir() / f"airdriver-{stamp}.json"
        p.write_text(json.dumps(rep, indent=2, default=str))
        out.append(p)
    if fmt in ("md", "both"):
        p = report_dir() / f"airdriver-{stamp}.md"
        p.write_text(to_markdown(rep))
        out.append(p)
    return out
