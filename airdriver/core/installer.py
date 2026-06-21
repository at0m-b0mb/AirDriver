"""The install engine: turn an adapter + system state into a concrete, ordered
plan of steps, then execute it with streamed output.

Design goals:
  * **Smart method selection** — skip a DKMS build entirely when a working
    in-kernel driver already exists for this kernel.
  * **Hybrid online/offline** — prefer apt when online, fall back to a DKMS git
    build, and fall back again to a bundled offline copy with no internet.
  * **Honest dry-run** — every plan can be previewed without touching the system.
  * **Streamed output** — long compiles report progress line-by-line.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Callable, Optional

from .chipset_db import Chipset, DriverOption
from .detector import Adapter
from .modules import BLACKLIST_FILE, blacklist_snippet, module_available
from .system import SystemInfo

LogFn = Callable[[str], None]


# --------------------------------------------------------------------------- #
# Plan model                                                                  #
# --------------------------------------------------------------------------- #
@dataclass
class Step:
    title: str
    kind: str = "cmd"               # "cmd" | "write" | "note"
    shell: Optional[str] = None     # for kind == "cmd" (run via bash -c)
    path: Optional[str] = None      # for kind == "write"
    content: Optional[str] = None   # for kind == "write"
    privileged: bool = False
    optional: bool = False          # failure logged but does not abort


@dataclass
class InstallPlan:
    adapter: Adapter
    chipset: Chipset
    method: str                     # chosen DriverOption.method (or "kernel_native")
    summary: str
    steps: list[Step] = field(default_factory=list)
    needs_reboot: bool = True
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [f"Plan: {self.summary}", ""]
        for i, s in enumerate(self.steps, 1):
            tag = {"cmd": "$", "write": "≫", "note": "#"}.get(s.kind, "-")
            lines.append(f" {i:>2}. {s.title}")
            if s.kind == "cmd" and s.shell:
                lines.append(f"      {tag} {s.shell}")
            elif s.kind == "write":
                lines.append(f"      {tag} write {s.path}")
        if self.warnings:
            lines += ["", "Warnings:"] + [f"  ! {w}" for w in self.warnings]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Offline driver bundle                                                       #
# --------------------------------------------------------------------------- #
def offline_source_dir(option: DriverOption) -> Optional[Path]:
    """Resolve a bundled offline driver dir if it exists and has content."""
    if not option.path:
        return None
    try:
        root = resources.files("airdriver.data")
        # option.path is like "drivers/8812au-20210820" (relative to data/).
        candidate = Path(str(root)) / option.path
    except (ModuleNotFoundError, AttributeError):
        return None
    if candidate.is_dir() and any(candidate.iterdir()):
        return candidate
    return None


# --------------------------------------------------------------------------- #
# Feasibility + method selection                                              #
# --------------------------------------------------------------------------- #
def _feasible(option: DriverOption, sysinfo: SystemInfo) -> tuple[bool, str]:
    m = option.method
    if m == "kernel_native":
        return True, ""
    if m == "apt":
        if not sysinfo.has_internet:
            return False, "no internet"
        if not sysinfo.is_debian_based:
            return False, "not a Debian/Kali/Parrot system"
        return True, ""
    if m == "dkms_git":
        if not sysinfo.has_internet:
            return False, "no internet"
        return True, ""
    if m == "offline":
        return (True, "") if offline_source_dir(option) else (False, "no offline bundle present")
    return False, "unknown method"


def select_driver(chipset: Chipset, sysinfo: SystemInfo,
                  force_dkms: bool = False, prefer_offline: bool = False):
    """Return (DriverOption-or-None, reason_string).

    If a usable in-kernel driver already exists for this kernel, we prefer it and
    return ``None`` (meaning "no install needed — just load/verify"), unless the
    caller forces a DKMS build.
    """
    kn = chipset.kernel_native
    native_ready = (
        kn is not None
        and sysinfo.kernel_at_least(kn.min_kernel)
        and not force_dkms
        # On Linux we double-check the module truly exists for this kernel.
        and (not sysinfo.is_linux or module_available(kn.module))
    )
    if native_ready:
        return None, (f"In-kernel driver '{kn.module}' is available on kernel "
                      f"{sysinfo.kernel_release} (>= {kn.min_kernel}) — no build needed.")

    options = chipset.best_drivers()
    if prefer_offline:
        options = sorted(options, key=lambda o: (o.method != "offline", o.priority))

    tried = []
    for opt in options:
        ok, why = _feasible(opt, sysinfo)
        if ok:
            return opt, f"Selected '{opt.method}' driver path."
        tried.append(f"{opt.method} ({why})")
    return None, "No feasible driver method. Tried: " + ", ".join(tried)


# --------------------------------------------------------------------------- #
# Plan building                                                               #
# --------------------------------------------------------------------------- #
# The build script. `__FETCH__` is substituted with a snippet that puts the
# driver source in $SRC. We deliberately prefer the *driver's own* installer:
# morrownr / aircrack-ng ship an `install-driver.sh` that does the complete,
# correct job (stage to /usr/src, dkms add/build/install, write the modprobe.d
# conf, blacklist the conflicting in-kernel module, depmod, and load it). The
# old code ran a bare `dkms add . && dkms autoinstall` and skipped all of that,
# which is exactly why a build could "succeed" yet the adapter never worked.
_DKMS_BUILD = r"""
set -e
__FETCH__
cd "$SRC"
echo "[airdriver] driver source ready: $SRC"

make_install() {
  echo "[airdriver] no installer script — building with make"
  make clean >/dev/null 2>&1 || true
  make
  sudo make install
}

if [ -f install-driver.sh ]; then
  echo "[airdriver] running the driver's own installer (non-interactive: NoPrompt)"
  # morrownr & aircrack-ng installers accept NoPrompt to skip questions/reboot.
  sudo bash ./install-driver.sh NoPrompt
elif [ -f dkms-install.sh ]; then
  echo "[airdriver] running dkms-install.sh"
  sudo bash ./dkms-install.sh
elif [ -f dkms.conf ]; then
  echo "[airdriver] installing via DKMS"
  NAME="$(sed -n 's/.*PACKAGE_NAME[ =]*//p' dkms.conf | head -1 | tr -dc 'A-Za-z0-9._-')"
  VER="$(sed -n 's/.*PACKAGE_VERSION[ =]*//p' dkms.conf | head -1 | tr -dc 'A-Za-z0-9._-')"
  if [ -n "$NAME" ] && [ -n "$VER" ]; then
    DEST="/usr/src/${NAME}-${VER}"
    echo "[airdriver] staging source at $DEST"
    sudo rm -rf "$DEST"; sudo mkdir -p "$DEST"
    sudo cp -a "$SRC"/. "$DEST"/
    sudo dkms remove -m "$NAME" -v "$VER" --all 2>/dev/null || true
    sudo dkms add -m "$NAME" -v "$VER" 2>/dev/null || true
    sudo dkms build -m "$NAME" -v "$VER"
    sudo dkms install -m "$NAME" -v "$VER" --force
  else
    make_install
  fi
else
  make_install
fi

echo "[airdriver] updating module dependency map"
sudo depmod -a
echo "[airdriver] driver build/install finished"
"""


def _build_script(fetch: str) -> str:
    return _DKMS_BUILD.replace("__FETCH__", fetch)


def _dkms_step_git(option: DriverOption) -> Step:
    fetch = (f'SRC="$(mktemp -d)/src"\n'
             f'git clone --depth=1 {shlex.quote(option.repo)} "$SRC"')
    return Step(title=f"Build & install DKMS driver from {option.repo}",
                shell=_build_script(fetch), privileged=True)


def _dkms_step_offline(option: DriverOption, src: Path) -> Step:
    fetch = (f'SRC="$(mktemp -d)/src"\n'
             f'mkdir -p "$SRC"\n'
             f'cp -a {shlex.quote(str(src))}/. "$SRC"/')
    return Step(title=f"Build & install bundled offline driver ({option.path})",
                shell=_build_script(fetch), privileged=True)


def build_plan(adapter: Adapter, sysinfo: SystemInfo, *,
               force_dkms: bool = False, prefer_offline: bool = False) -> InstallPlan:
    chip = adapter.chipset
    if chip is None:
        raise ValueError("Cannot build a plan for an unidentified adapter.")

    option, reason = select_driver(chip, sysinfo, force_dkms, prefer_offline)
    plan = InstallPlan(adapter=adapter, chipset=chip,
                       method=(option.method if option else "kernel_native"),
                       summary=reason)
    steps = plan.steps

    # --- Secure Boot heads-up (affects DKMS modules) -----------------------
    if sysinfo.secure_boot == "on" and (option is None or option.method in ("dkms_git", "offline")):
        plan.warnings.append(
            "Secure Boot is ON. A freshly built DKMS module is unsigned and the "
            "kernel will refuse to load it. Either disable Secure Boot in the "
            "firmware, or enroll a MOK key (mokutil --import). AirDriver will "
            "still build it, but it won't load until that's resolved.")

    # --- Path A: in-kernel driver already available ------------------------
    if option is None and chip.kernel_native:
        kn = chip.kernel_native
        if kn.firmware:
            fw_pkg = next((d.firmware_pkg for d in chip.drivers if d.firmware_pkg), "firmware-atheros")
            if sysinfo.has_internet:
                steps.append(Step(
                    title=f"Ensure firmware blob '{kn.firmware}' is installed",
                    shell=f"sudo apt-get install -y {fw_pkg}", privileged=True, optional=True))
            else:
                plan.warnings.append(
                    f"This chip needs firmware '{kn.firmware}' ({fw_pkg}); no internet "
                    "to fetch it. If WiFi still fails, install that package when online.")
        _append_conflict_and_load(plan, chip, kn.module)
        _append_bringup(plan)
        plan.needs_reboot = False
        return plan

    if option is None:
        # No native driver and nothing feasible.
        plan.warnings.append(reason)
        steps.append(Step(title="No installable driver path found", kind="note"))
        return plan

    # --- Shared prerequisites for builds -----------------------------------
    if option.method in ("apt", "dkms_git"):
        steps.append(Step(title="Refresh package lists",
                          shell="sudo apt-get update", privileged=True, optional=True))

    if option.method in ("dkms_git", "offline"):
        if not sysinfo.headers_installed:
            steps.append(Step(
                title=f"Install kernel headers for {sysinfo.kernel_release}",
                shell="sudo apt-get install -y linux-headers-$(uname -r) || "
                      "sudo apt-get install -y linux-headers-amd64",
                privileged=True))
            plan.warnings.append(
                f"Kernel headers for your running kernel ({sysinfo.kernel_release}) are "
                "missing. If the header install above can't find an exact match, your "
                "running kernel is older than the installed one — run "
                "'sudo apt update && sudo apt full-upgrade', REBOOT, then install again "
                "so DKMS builds against the kernel you're actually running.")
        steps.append(Step(
            title="Install build prerequisites (dkms, build-essential, git, bc, libelf)",
            shell="sudo apt-get install -y dkms build-essential git bc libelf-dev",
            privileged=True))

    # --- The driver itself -------------------------------------------------
    if option.method == "apt":
        steps.append(Step(title=f"Install apt package '{option.package}'",
                          shell=f"sudo apt-get install -y {option.package}", privileged=True))
    elif option.method == "dkms_git":
        steps.append(_dkms_step_git(option))
    elif option.method == "offline":
        src = offline_source_dir(option)
        steps.append(_dkms_step_offline(option, src))

    # --- Conflicts, depmod, load, bring-up ---------------------------------
    _append_conflict_and_load(plan, chip, option.module or (chip.kernel_native.module if chip.kernel_native else ""))
    _append_bringup(plan)
    return plan


def _append_bringup(plan: InstallPlan) -> None:
    """Steps that turn a *loaded* driver into a *working* adapter. These are the
    bits people forget after a build succeeds: the radio is soft-blocked by
    rfkill, the interface is administratively down, or NetworkManager hasn't
    noticed it yet — any of which looks like 'the driver doesn't work'."""
    plan.steps.append(Step(
        title="Unblock wireless radios (rfkill)",
        shell="sudo rfkill unblock all 2>/dev/null || true",
        privileged=True, optional=True))
    plan.steps.append(Step(
        title="Bring up the wireless interface(s)",
        shell=("found=0; for d in /sys/class/net/*/wireless; do "
               "[ -e \"$d\" ] || continue; i=$(basename \"$(dirname \"$d\")\"); "
               "echo \"[airdriver] ip link set $i up\"; "
               "sudo ip link set \"$i\" up 2>/dev/null && found=1; done; "
               "[ \"$found\" = 1 ] || echo \"[airdriver] no wireless interface yet — "
               "re-plug the adapter and run: airdriver scan\"; "
               "ip -brief link show 2>/dev/null | grep -iE 'wl|mon' || true"),
        privileged=True, optional=True))
    plan.steps.append(Step(
        title="Let NetworkManager manage the adapter",
        shell="sudo nmcli radio wifi on 2>/dev/null || true",
        privileged=True, optional=True))


def _append_conflict_and_load(plan: InstallPlan, chip: Chipset, module: str) -> None:
    if chip.blacklist:
        plan.steps.append(Step(
            title=f"Blacklist conflicting in-kernel modules: {', '.join(chip.blacklist)}",
            kind="write", path=BLACKLIST_FILE,
            content=blacklist_snippet(list(chip.blacklist)), privileged=True))
        for m in chip.blacklist:
            plan.steps.append(Step(title=f"Unload conflicting module '{m}'",
                                   shell=f"sudo modprobe -r {m} 2>/dev/null || true",
                                   privileged=True, optional=True))
    plan.steps.append(Step(title="Rebuild module dependency map",
                           shell="sudo depmod -a", privileged=True, optional=True))
    if module:
        plan.steps.append(Step(
            title=f"Load driver module '{module}'",
            # Show modprobe's error if it fails (Secure Boot, missing firmware,
            # conflict…) instead of hiding it — verification reports the verdict.
            shell=f"sudo modprobe {module} || echo \"[airdriver] modprobe {module} "
                  f"failed — see the verification report below for why\"",
            privileged=True, optional=True))


# --------------------------------------------------------------------------- #
# Removal (clean slate for a retry)                                           #
# --------------------------------------------------------------------------- #
def build_remove_plan(chip: Chipset, sysinfo: SystemInfo) -> InstallPlan:
    """Steps to cleanly remove a (possibly half-broken) driver for ``chip`` so
    the user can retry from scratch. Removes DKMS modules + apt packages and
    unloads the out-of-tree module. Never touches in-kernel drivers."""
    plan = InstallPlan(adapter=None, chipset=chip, method="remove",
                       summary=f"Remove installed driver(s) for {chip.name}",
                       needs_reboot=False)
    oot_modules = sorted({d.module for d in chip.drivers
                          if d.method in ("dkms_git", "offline") and d.module})
    apt_pkgs = sorted({d.package for d in chip.drivers
                       if d.method == "apt" and d.package})

    if not oot_modules and not apt_pkgs:
        plan.steps.append(Step(
            title="Nothing to remove — this chipset uses the in-kernel driver only.",
            kind="note"))
        return plan

    if oot_modules:
        pattern = "|".join(re.escape(m) for m in oot_modules)
        plan.steps.append(Step(
            title=f"Remove DKMS modules ({', '.join(oot_modules)})",
            privileged=True, optional=True,
            shell=(
                f'PATTERN={shlex.quote(pattern)}\n'
                'dkms status 2>/dev/null | grep -E "$PATTERN" | sed "s/[,:].*//" '
                '| sort -u | while read -r mod; do\n'
                '  [ -n "$mod" ] || continue\n'
                '  echo "[airdriver] dkms remove $mod"\n'
                '  sudo dkms remove "$mod" --all 2>/dev/null || sudo dkms remove "$mod" 2>/dev/null || true\n'
                'done\n'
                'echo "[airdriver] dkms cleanup done"')))
        for m in oot_modules:
            plan.steps.append(Step(
                title=f"Unload module '{m}' if loaded",
                shell=f"sudo modprobe -r {m} 2>/dev/null || true",
                privileged=True, optional=True))

    for pkg in apt_pkgs:
        plan.steps.append(Step(
            title=f"Remove apt package '{pkg}' (if installed)",
            shell=f"dpkg -l {pkg} >/dev/null 2>&1 && sudo apt-get remove -y {pkg} || true",
            privileged=True, optional=True))

    plan.steps.append(Step(title="Rebuild module dependency map",
                           shell="sudo depmod -a", privileged=True, optional=True))
    plan.warnings.append("After removal, re-plug the adapter and run a fresh install.")
    return plan


# --------------------------------------------------------------------------- #
# Execution                                                                   #
# --------------------------------------------------------------------------- #
class Executor:
    def __init__(self, sysinfo: SystemInfo, dry_run: bool = False):
        self.sysinfo = sysinfo
        self.dry_run = dry_run

    def _maybe_sudo(self, shell: str) -> str:
        # If already root, strip the literal 'sudo ' so logs are clean.
        if self.sysinfo.is_root:
            return shell.replace("sudo ", "")
        return shell

    def run(self, plan: InstallPlan, log: LogFn) -> bool:
        log(f"=== AirDriver install: {plan.chipset.name} ===")
        log(plan.summary)
        for w in plan.warnings:
            log(f"  ⚠ {w}")
        if self.dry_run:
            log("\n[DRY RUN] Nothing will be executed. Plan:\n")
            log(plan.describe())
            return True

        ok = True
        for i, step in enumerate(plan.steps, 1):
            log(f"\n[{i}/{len(plan.steps)}] {step.title}")
            try:
                if step.kind == "note":
                    continue
                elif step.kind == "write":
                    self._write_file(step, log)
                else:
                    rc = self._run_shell(self._maybe_sudo(step.shell or ""), log)
                    if rc != 0 and not step.optional:
                        log(f"  ✗ step failed (exit {rc}) — aborting.")
                        return False
                    if rc != 0:
                        log(f"  ⚠ optional step returned {rc}, continuing.")
            except Exception as exc:  # noqa: BLE001 — surface any failure to the log
                if step.optional:
                    log(f"  ⚠ {exc} (optional, continuing)")
                else:
                    log(f"  ✗ {exc}")
                    return False
        log("\n✓ Install steps complete." +
            (" Reboot recommended." if plan.needs_reboot else " No reboot needed."))
        return ok

    def _run_shell(self, shell: str, log: LogFn) -> int:
        proc = subprocess.Popen(["bash", "-c", shell], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            log("  " + line.rstrip())
        proc.wait()
        return proc.returncode

    def _write_file(self, step: Step, log: LogFn) -> None:
        path, content = step.path, step.content or ""
        if step.privileged and not self.sysinfo.is_root:
            log(f"  writing {path} via sudo tee")
            p = subprocess.run(["sudo", "tee", path], input=content,
                               capture_output=True, text=True)
            if p.returncode != 0:
                raise RuntimeError(f"could not write {path}: {p.stderr.strip()}")
        else:
            log(f"  writing {path}")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            Path(path).write_text(content)
