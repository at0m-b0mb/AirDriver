"""Driver *management* — the lifecycle around an install.

Installing a driver is only half the job. What actually keeps a pentest box
working is everything after it:

* **What is installed?** — a real inventory of the DKMS modules on the box,
  which kernels they are built for, and whether that includes the kernel you
  are *running* (``status``).
* **Kernel upgrades** — the #1 way Wi-Fi "randomly breaks" on Kali/Parrot: you
  upgrade, reboot into a new kernel, and the out-of-tree module was never built
  for it. ``rebuild`` puts that right in one command.
* **Secure Boot** — a freshly built module is unsigned, so the kernel refuses
  it. ``sign`` does the tedious key/sign work and hands you the one interactive
  step (MOK enrollment) with exact instructions.
* **Flip-storage dongles** — many cheap adapters enumerate as a fake CD-ROM
  holding Windows drivers and never appear as Wi-Fi until they're ejected.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .chipset_db import Chipset, ChipsetDB
from .installer import InstallPlan, Step
from .modules import loaded_modules, module_available
from .system import SystemInfo

# Where AirDriver keeps the Secure Boot signing key it generates.
MOK_DIR = "/var/lib/airdriver"
MOK_KEY = f"{MOK_DIR}/MOK.priv"
MOK_CRT = f"{MOK_DIR}/MOK.der"


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return 127, ""


# --------------------------------------------------------------------------- #
# DKMS inventory                                                              #
# --------------------------------------------------------------------------- #
@dataclass
class DkmsModule:
    name: str
    version: str
    kernels: list[str] = field(default_factory=list)   # kernels it is built for
    states: list[str] = field(default_factory=list)    # installed / built / added

    @property
    def label(self) -> str:
        return f"{self.name}/{self.version}"

    def built_for(self, kernel_release: str) -> bool:
        return any(k == kernel_release for k in self.kernels)


# `dkms status` output has changed shape across versions:
#   old:  name, version, kernel, arch: installed
#   new:  name/version, kernel, arch: installed
#   also: name/version: added            (no kernel yet)
_DKMS_LINE = re.compile(
    r"^(?P<name>[\w.+-]+)[,/]\s*(?P<ver>[\w.+-]+)"
    r"(?:,\s*(?P<kernel>[^,:]+?)(?:,\s*(?P<arch>[^,:]+?))?)?"
    r"\s*:\s*(?P<state>\w+)")


def dkms_inventory() -> list[DkmsModule]:
    """Every DKMS module registered on this system, merged by name/version."""
    rc, out = _run(["dkms", "status"])
    if rc != 0 or not out.strip():
        return []
    merged: dict[str, DkmsModule] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _DKMS_LINE.match(line)
        if not m:
            continue
        key = f"{m.group('name')}/{m.group('ver')}"
        mod = merged.setdefault(key, DkmsModule(m.group("name"), m.group("ver")))
        kernel = (m.group("kernel") or "").strip()
        if kernel and kernel not in mod.kernels:
            mod.kernels.append(kernel)
        state = m.group("state")
        if state and state not in mod.states:
            mod.states.append(state)
    return sorted(merged.values(), key=lambda d: d.name)


def other_kernels(running: str) -> list[str]:
    """Installed kernels other than the running one (a mismatch here is why a
    DKMS build can 'succeed' yet the adapter stays dead after a reboot)."""
    out = []
    base = "/lib/modules"
    if os.path.isdir(base):
        for k in sorted(os.listdir(base)):
            if k != running and os.path.isdir(os.path.join(base, k, "build")):
                out.append(k)
    return out


# --------------------------------------------------------------------------- #
# Status report                                                               #
# --------------------------------------------------------------------------- #
@dataclass
class ManagedDriver:
    """A DKMS module correlated with the chipset(s) it serves."""
    dkms: DkmsModule
    chipsets: list[str] = field(default_factory=list)
    ok_for_running_kernel: bool = False
    loaded: bool = False


@dataclass
class Status:
    kernel: str
    other_kernels: list[str] = field(default_factory=list)
    drivers: list[ManagedDriver] = field(default_factory=list)
    stale: list[ManagedDriver] = field(default_factory=list)   # not built for running kernel
    secure_boot: str = "unknown"
    signing_key: bool = False
    dkms_available: bool = True
    messages: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.stale


def _chipsets_for_module(db: ChipsetDB, module_name: str) -> list[str]:
    """Which chipset families a DKMS module name plausibly serves."""
    n = module_name.replace("-", "_").lower()
    hits = []
    for c in db.all():
        names = {(d.module or "").replace("-", "_").lower() for d in c.drivers}
        names |= {c.id.lower()}
        if c.kernel_native and c.kernel_native.module:
            names.add(c.kernel_native.module.replace("-", "_").lower())
        for cand in names:
            if not cand:
                continue
            if cand == n or (len(n) >= 5 and (n in cand or cand in n)):
                hits.append(c.name)
                break
    return hits


def status(db: ChipsetDB, info: SystemInfo) -> Status:
    st = Status(kernel=info.kernel_release, secure_boot=info.secure_boot)
    if not info.is_linux:
        st.dkms_available = False
        st.messages.append("Driver management is Linux-only; run this on Kali/Parrot.")
        return st
    st.dkms_available = shutil.which("dkms") is not None
    st.signing_key = os.path.exists(MOK_CRT)
    st.other_kernels = other_kernels(info.kernel_release)

    loaded = {m.replace("-", "_").lower() for m in loaded_modules()}
    for d in dkms_inventory():
        md = ManagedDriver(dkms=d, chipsets=_chipsets_for_module(db, d.name))
        md.ok_for_running_kernel = d.built_for(info.kernel_release)
        md.loaded = d.name.replace("-", "_").lower() in loaded
        st.drivers.append(md)
        if not md.ok_for_running_kernel:
            st.stale.append(md)

    if not st.dkms_available:
        st.messages.append("DKMS isn't installed — out-of-tree drivers can't be managed. "
                           "Install it with:  sudo apt install -y dkms")
    elif not st.drivers:
        st.messages.append("No DKMS drivers registered. That's normal if all your adapters "
                           "use in-kernel drivers — check with:  airdriver scan")
    if st.stale:
        names = ", ".join(m.dkms.label for m in st.stale)
        st.messages.append(
            f"{len(st.stale)} driver(s) are NOT built for the kernel you're running "
            f"({info.kernel_release}): {names}.")
        st.messages.append("This is the usual cause of 'Wi-Fi stopped working after an "
                           "update'. Fix it with:  sudo airdriver rebuild")
    if st.secure_boot == "on" and not st.signing_key:
        st.messages.append("Secure Boot is ON and no AirDriver signing key exists yet — "
                           "freshly built modules will be refused. Run:  sudo airdriver sign")
    return st


def describe_status(st: Status) -> str:
    lines = [f"  Running kernel   {st.kernel}"]
    if st.other_kernels:
        lines.append(f"  Other kernels    {', '.join(st.other_kernels)}")
    lines.append(f"  Secure Boot      {st.secure_boot}"
                 + ("   (AirDriver signing key present)" if st.signing_key else ""))
    lines.append("")
    if not st.drivers:
        lines.append("  No DKMS-managed drivers registered.")
    else:
        lines.append(f"  {'DRIVER':<26}{'VERSION':<14}{'RUNNING KERNEL':<16}{'LOADED':<8}CHIPSET")
        for m in st.drivers:
            ok = "yes" if m.ok_for_running_kernel else "NO — stale"
            chips = ", ".join(m.chipsets[:2]) or "-"
            lines.append(f"  {m.dkms.name:<26}{m.dkms.version:<14}{ok:<16}"
                         f"{('yes' if m.loaded else 'no'):<8}{chips}")
    if st.messages:
        lines.append("")
        lines += [f"  {msg}" for msg in st.messages]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Rebuild after a kernel upgrade                                              #
# --------------------------------------------------------------------------- #
def build_rebuild_plan(info: SystemInfo, only: Optional[str] = None) -> InstallPlan:
    """Rebuild DKMS modules for the *running* kernel.

    After `apt full-upgrade` installs a new kernel, out-of-tree modules must be
    rebuilt against it. `dkms autoinstall` is the supported way to do exactly
    that; we make sure the matching headers are present first, because without
    them the build fails with a confusing error.
    """
    plan = InstallPlan(adapter=None, chipset=None, method="rebuild",
                       summary=f"Rebuild DKMS drivers for kernel {info.kernel_release}",
                       needs_reboot=False)
    if not info.headers_installed:
        plan.steps.append(Step(
            title=f"Install kernel headers for {info.kernel_release}",
            shell='sudo apt-get install -y "linux-headers-$(uname -r)" || '
                  'sudo apt-get install -y linux-headers-amd64',
            privileged=True))
        plan.warnings.append(
            f"Headers for the running kernel ({info.kernel_release}) are missing. If apt "
            "can't find an exact match, you're running an older kernel than the one "
            "installed — reboot into the newest kernel first, then rebuild.")

    if only:
        plan.steps.append(Step(
            title=f"Rebuild and install '{only}' for {info.kernel_release}",
            shell=(f'sudo dkms build -m {only} -k "$(uname -r)" --force && '
                   f'sudo dkms install -m {only} -k "$(uname -r)" --force'),
            privileged=True))
    else:
        plan.steps.append(Step(
            title="Rebuild every registered DKMS module for the running kernel",
            shell='sudo dkms autoinstall -k "$(uname -r)"',
            privileged=True))

    plan.steps.append(Step(title="Rebuild module dependency map",
                           shell="sudo depmod -a", privileged=True, optional=True))
    plan.steps.append(Step(
        title="Show the resulting DKMS state",
        shell="dkms status", privileged=False, optional=True))
    return plan


# --------------------------------------------------------------------------- #
# Purge — remove every driver AirDriver could have installed                  #
# --------------------------------------------------------------------------- #
def purge_targets(db: ChipsetDB) -> tuple[list[str], list[str]]:
    """(dkms_labels, apt_packages) that AirDriver plausibly installed.

    DKMS entries are correlated against the chipset database rather than removed
    blindly, so an unrelated module (a GPU or VirtualBox driver, say) is never
    caught in the sweep.
    """
    apt_pkgs = sorted({d.package for c in db.all() for d in c.drivers
                       if d.method == "apt" and d.package})
    labels = [m.label for m in dkms_inventory() if _chipsets_for_module(db, m.name)]
    return labels, apt_pkgs


def build_purge_plan(db: ChipsetDB, info: SystemInfo) -> InstallPlan:
    """One-shot cleanup: every Wi-Fi driver AirDriver installed, gone, and the
    in-kernel drivers un-blacklisted so the adapters fall back to them."""
    from .modules import BLACKLIST_FILE

    labels, apt_pkgs = purge_targets(db)
    plan = InstallPlan(adapter=None, chipset=None, method="purge",
                       summary="Remove every AirDriver-installed Wi-Fi driver",
                       needs_reboot=False)

    if not labels and not apt_pkgs and not os.path.exists(BLACKLIST_FILE):
        plan.steps.append(Step(
            title="Nothing to remove — no AirDriver-installed drivers found.",
            kind="note"))
        return plan

    for label in labels:
        plan.steps.append(Step(
            title=f"Remove DKMS module '{label}'", privileged=True, optional=True,
            shell=f'sudo dkms remove {shlex.quote(label)} --all 2>/dev/null || '
                  f'sudo dkms remove {shlex.quote(label)} 2>/dev/null || true'))

    if apt_pkgs:
        pkgs = " ".join(shlex.quote(p) for p in apt_pkgs)
        plan.steps.append(Step(
            title=f"Remove any of the {len(apt_pkgs)} known driver apt packages",
            privileged=True, optional=True,
            shell=(f'for p in {pkgs}; do\n'
                   '  if dpkg -l "$p" 2>/dev/null | grep -q "^ii"; then\n'
                   '    echo "[airdriver] apt remove $p"\n'
                   '    sudo apt-get remove -y "$p" || true\n'
                   '  fi\n'
                   'done\n'
                   'echo "[airdriver] apt cleanup done"')))

    plan.steps.append(Step(
        title="Remove AirDriver's modprobe blacklist", privileged=True, optional=True,
        shell=(f'if [ -f {BLACKLIST_FILE} ]; then\n'
               f'  sudo rm -f {BLACKLIST_FILE}\n'
               f'  echo "[airdriver] removed {BLACKLIST_FILE} — in-kernel drivers '
               'are free to bind again"\n'
               'else\n'
               '  echo "[airdriver] no blacklist file present"\n'
               'fi')))
    plan.steps.append(Step(title="Rebuild module dependency map",
                           shell="sudo depmod -a", privileged=True, optional=True))
    plan.warnings.append(
        "This removes out-of-tree Wi-Fi drivers only. In-kernel drivers are never "
        "touched — after a reboot (or a re-plug) your adapters fall back to them.")
    return plan


# --------------------------------------------------------------------------- #
# Secure Boot signing                                                         #
# --------------------------------------------------------------------------- #
def modules_to_sign(db: ChipsetDB, kernel: str) -> list[str]:
    """Paths of out-of-tree .ko files for this kernel that DKMS produced."""
    out: list[str] = []
    base = f"/lib/modules/{kernel}/updates/dkms"
    if os.path.isdir(base):
        for root, _dirs, files in os.walk(base):
            for f in files:
                if f.endswith((".ko", ".ko.xz", ".ko.zst", ".ko.gz")):
                    out.append(os.path.join(root, f))
    return sorted(out)


def build_sign_plan(info: SystemInfo) -> InstallPlan:
    """Generate a MOK signing key (once) and sign every DKMS module built for
    the running kernel. Enrolling the key needs a password *you* choose and a
    reboot, so that one step is handed back to the user rather than automated.
    """
    plan = InstallPlan(adapter=None, chipset=None, method="sign",
                       summary=f"Sign DKMS modules for Secure Boot (kernel {info.kernel_release})",
                       needs_reboot=True)
    plan.steps.append(Step(
        title="Install signing prerequisites (openssl, mokutil)",
        shell="sudo apt-get install -y openssl mokutil", privileged=True, optional=True))
    plan.steps.append(Step(
        title=f"Create an AirDriver module-signing key in {MOK_DIR} (once)",
        privileged=True,
        shell=(
            f'sudo mkdir -p {MOK_DIR} && sudo chmod 700 {MOK_DIR}\n'
            f'if [ -f {MOK_CRT} ] && [ -f {MOK_KEY} ]; then\n'
            f'  echo "[airdriver] reusing the existing signing key at {MOK_CRT}"\n'
            f'else\n'
            f'  echo "[airdriver] generating a new 2048-bit signing key"\n'
            f'  sudo openssl req -new -x509 -newkey rsa:2048 -nodes -days 36500 \\\n'
            f'      -subj "/CN=AirDriver module signing key/" \\\n'
            f'      -keyout {MOK_KEY} -outform DER -out {MOK_CRT}\n'
            f'  sudo chmod 600 {MOK_KEY}\n'
            f'fi')))
    plan.steps.append(Step(
        title="Sign every DKMS module built for the running kernel",
        privileged=True,
        shell=(
            'K="$(uname -r)"\n'
            'SIGN="/usr/src/linux-headers-$K/scripts/sign-file"\n'
            '[ -x "$SIGN" ] || SIGN="/lib/modules/$K/build/scripts/sign-file"\n'
            'if [ ! -x "$SIGN" ]; then\n'
            '  echo "[airdriver] sign-file not found — install linux-headers-$K"; exit 1\n'
            'fi\n'
            'found=0\n'
            '# A compressed module can\'t be signed in place: decompress, sign the\n'
            '# plain .ko, then recompress it the way the kernel expects.\n'
            'while IFS= read -r ko; do\n'
            '  [ -n "$ko" ] || continue\n'
            '  plain="$ko"; recompress=none\n'
            '  case "$ko" in\n'
            '    *.ko.xz)  sudo xz -d -f "$ko"        && plain="${ko%.xz}"  && recompress=xz ;;\n'
            '    *.ko.zst) sudo zstd -q -d --rm "$ko" && plain="${ko%.zst}" && recompress=zstd ;;\n'
            '    *.ko.gz)  sudo gzip -d -f "$ko"      && plain="${ko%.gz}"  && recompress=gzip ;;\n'
            '  esac\n'
            '  echo "[airdriver] signing $plain"\n'
            f'  if sudo "$SIGN" sha256 {MOK_KEY} {MOK_CRT} "$plain"; then\n'
            '    found=1\n'
            '  else\n'
            '    echo "[airdriver] WARNING: could not sign $plain"\n'
            '  fi\n'
            '  # Put it back exactly as we found it — a module left decompressed\n'
            '  # confuses later dkms/depmod runs.\n'
            '  case "$recompress" in\n'
            '    xz)   sudo xz -f "$plain"        || echo "[airdriver] WARNING: recompress failed: $plain" ;;\n'
            '    zstd) sudo zstd -q -f --rm "$plain" || echo "[airdriver] WARNING: recompress failed: $plain" ;;\n'
            '    gzip) sudo gzip -f "$plain"      || echo "[airdriver] WARNING: recompress failed: $plain" ;;\n'
            '  esac\n'
            'done <<EOF\n'
            '$(find "/lib/modules/$K/updates/dkms" -name "*.ko*" 2>/dev/null)\n'
            'EOF\n'
            '[ "$found" = 1 ] || echo "[airdriver] no DKMS modules found for $K — '
            'install a driver first (airdriver install), then sign."\n'
            'sudo depmod -a')))
    plan.steps.append(Step(
        title="Next step (needs a password you choose + a reboot)", kind="note"))
    plan.warnings.append(
        "Enrollment is deliberately NOT automated: run  sudo mokutil --import "
        f"{MOK_CRT}  yourself, pick a one-time password, then REBOOT. At boot the "
        "blue MOK Manager screen appears — choose 'Enroll MOK' → 'Continue' → enter "
        "that password. After that the kernel accepts your signed modules.")
    return plan


# --------------------------------------------------------------------------- #
# Flip-storage ("CD-ROM mode") adapters                                       #
# --------------------------------------------------------------------------- #
# Adapters that first enumerate as a fake CD-ROM/flash drive holding Windows
# drivers. Until they're switched, no Wi-Fi device exists at all. Sourced from
# usb_modeswitch's data and the kernel's own STORAGE_DEVICE entries.
STORAGE_MODE_IDS = {
    "0bda:1a2b": "Realtek RTL8188GU / RTL8710BU / RTL8821CU (driver CD-ROM mode)",
    "0cf3:20ff": "Atheros AR9271 (storage mode — ath9k_htc ejects it automatically)",
    "0bda:1e1e": "Realtek RTL8192CU family (driver CD-ROM mode)",
    "0e8d:2870": "MediaTek/Ralink (driver CD-ROM mode)",
}


def storage_mode_devices(adapters) -> list[tuple[str, str]]:
    """Detected devices that are sitting in flip-storage mode."""
    return [(a.usb_id, STORAGE_MODE_IDS[a.usb_id])
            for a in adapters if a.usb_id in STORAGE_MODE_IDS]


def build_modeswitch_plan(usb_id: str) -> InstallPlan:
    """Eject the fake CD-ROM so the device re-enumerates as a Wi-Fi adapter."""
    vid, _, pid = usb_id.partition(":")
    plan = InstallPlan(adapter=None, chipset=None, method="modeswitch",
                       summary=f"Switch {usb_id} out of driver-CD (storage) mode",
                       needs_reboot=False)
    plan.steps.append(Step(
        title="Install usb-modeswitch",
        shell="sudo apt-get install -y usb-modeswitch usb-modeswitch-data",
        privileged=True, optional=True))
    plan.steps.append(Step(
        title=f"Eject the storage interface of {usb_id}",
        privileged=True,
        shell=(f'sudo usb_modeswitch -KW -v {vid} -p {pid} 2>&1 || '
               f'sudo eject /dev/sr0 2>/dev/null || '
               f'echo "[airdriver] could not switch automatically — unplug and re-plug '
               f'the adapter, or run: sudo usb_modeswitch -KW -v {vid} -p {pid}"')))
    plan.steps.append(Step(
        title="Re-scan the USB bus",
        shell="sleep 2; lsusb | grep -iE 'wireless|wlan|802.11|realtek|ralink|atheros|mediatek' || true",
        optional=True))
    plan.warnings.append(
        "After switching, the adapter appears with a DIFFERENT USB id — run "
        "'airdriver scan' again and install the driver for the id that shows up.")
    return plan


# --------------------------------------------------------------------------- #
# Adapter recommendations                                                     #
# --------------------------------------------------------------------------- #
_QUALITY_RANK = {"excellent": 4, "good": 3, "fair": 2, "poor": 1, "unknown": 0}


def recommend(db: ChipsetDB, band: Optional[str] = None,
              need_injection: bool = True, limit: int = 8) -> list[Chipset]:
    """Rank chipsets for pentest use, best first, using the honest capability
    flags in the database (not marketing claims)."""
    def score(c: Chipset) -> tuple:
        q = _QUALITY_RANK.get(c.injection_quality, 0)
        native = 1 if (c.kernel_native and c.drivers
                       and c.drivers[0].method == "kernel_native") else 0
        modern = 1 if ("6" in c.wifi or "7" in c.wifi or "ac" in c.band.lower()) else 0
        return (q, int(c.monitor_mode), native, modern)

    pool = [c for c in db.all() if c.monitor_mode]
    if need_injection:
        pool = [c for c in pool if c.injection]
    if band == "5":
        pool = [c for c in pool if "5 ghz" in c.band.lower() or "dual" in c.band.lower()
                or "tri" in c.band.lower()]
    elif band == "2.4":
        pool = [c for c in pool if "2.4" in c.band]
    return sorted(pool, key=score, reverse=True)[:limit]
