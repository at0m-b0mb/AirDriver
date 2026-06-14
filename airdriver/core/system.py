"""Probes the host system: distro, kernel, headers, Secure Boot, DKMS, network.

These are the checks that decide *whether a driver build can even succeed* —
the things people forget and then spend an evening debugging.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Optional


def _run(cmd: list[str], timeout: int = 8) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return 127, ""


def parse_kernel_version(release: str) -> tuple[int, ...]:
    """'6.12.13-amd64' -> (6, 12, 13). Tolerant of junk suffixes."""
    nums = re.findall(r"\d+", release.split("-")[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def version_ge(a: str, b: str) -> bool:
    """True if version string ``a`` >= ``b`` (e.g. '6.13' >= '6.12')."""
    return parse_kernel_version(a) >= parse_kernel_version(b)


@dataclass
class SystemInfo:
    os: str = "unknown"
    is_linux: bool = False
    distro_id: str = "unknown"
    distro_name: str = "unknown"
    is_debian_based: bool = False
    arch: str = ""
    kernel_release: str = ""
    headers_installed: bool = False
    headers_package: str = ""
    dkms_installed: bool = False
    build_tools: bool = False
    secure_boot: str = "unknown"  # "on" | "off" | "unknown"
    is_root: bool = False
    has_internet: bool = False
    pentest_tools: dict = field(default_factory=dict)  # airmon-ng, aireplay-ng, iw...

    @property
    def kernel_tuple(self) -> tuple[int, ...]:
        return parse_kernel_version(self.kernel_release)

    def kernel_at_least(self, ver: str) -> bool:
        return self.kernel_tuple >= parse_kernel_version(ver)

    # The list of problems that will block or complicate a DKMS install.
    def blockers(self) -> list[str]:
        out = []
        if self.is_linux and not self.is_root:
            out.append("Not running as root — installs need sudo.")
        if self.is_debian_based and not self.headers_installed:
            out.append(f"Kernel headers missing for {self.kernel_release} "
                       "— DKMS builds will fail until installed.")
        if self.is_linux and not self.dkms_installed:
            out.append("DKMS not installed — needed for out-of-tree drivers.")
        if self.is_linux and not self.build_tools:
            out.append("build-essential / gcc missing — needed to compile drivers.")
        if self.secure_boot == "on":
            out.append("Secure Boot is ON — unsigned DKMS modules will be refused "
                       "until enrolled with a MOK key.")
        return out


def _detect_distro() -> tuple[str, str, bool]:
    path = "/etc/os-release"
    if not os.path.exists(path):
        return "unknown", "unknown", False
    data = {}
    try:
        for line in open(path):
            if "=" in line:
                k, _, v = line.strip().partition("=")
                data[k] = v.strip().strip('"')
    except OSError:
        return "unknown", "unknown", False
    distro_id = data.get("ID", "unknown").lower()
    name = data.get("PRETTY_NAME", data.get("NAME", distro_id))
    like = (data.get("ID_LIKE", "") + " " + distro_id).lower()
    debian_based = any(x in like for x in ("debian", "kali", "ubuntu", "parrot"))
    return distro_id, name, debian_based


def _detect_secure_boot() -> str:
    # mokutil is the cleanest signal; fall back to the efivars blob.
    if shutil.which("mokutil"):
        rc, out = _run(["mokutil", "--sb-state"])
        low = out.lower()
        if "enabled" in low:
            return "on"
        if "disabled" in low:
            return "off"
    try:
        import glob
        for f in glob.glob("/sys/firmware/efi/efivars/SecureBoot-*"):
            data = open(f, "rb").read()
            if data:
                return "on" if data[-1] == 1 else "off"
    except OSError:
        pass
    return "unknown"


def _headers_present(kernel_release: str) -> tuple[bool, str]:
    pkg = f"linux-headers-{kernel_release}"
    # The reliable check: do the build-tree headers actually exist on disk?
    if os.path.isdir(f"/lib/modules/{kernel_release}/build"):
        return True, pkg
    if os.path.isdir(f"/usr/src/{pkg}"):
        return True, pkg
    return False, pkg


def _check_internet(host: str = "1.1.1.1", port: int = 53, timeout: float = 2.0) -> bool:
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except OSError:
        return False


def gather(check_internet: bool = True) -> SystemInfo:
    info = SystemInfo()
    info.os = platform.system()
    info.is_linux = info.os == "Linux"
    info.arch = platform.machine()
    info.kernel_release = platform.release()
    info.is_root = (hasattr(os, "geteuid") and os.geteuid() == 0)

    if info.is_linux:
        info.distro_id, info.distro_name, info.is_debian_based = _detect_distro()
        info.headers_installed, info.headers_package = _headers_present(info.kernel_release)
        info.dkms_installed = shutil.which("dkms") is not None
        info.build_tools = shutil.which("gcc") is not None and shutil.which("make") is not None
        info.secure_boot = _detect_secure_boot()
        for tool in ("iw", "airmon-ng", "aireplay-ng", "iwconfig", "ip", "modprobe", "git", "apt"):
            info.pentest_tools[tool] = shutil.which(tool) is not None
    else:
        # Non-Linux (e.g. macOS dev box): report honestly, enable demo mode upstream.
        info.distro_name = f"{info.os} {platform.release()}"

    info.has_internet = _check_internet() if check_internet else False
    return info
