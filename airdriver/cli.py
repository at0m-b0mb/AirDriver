"""AirDriver command-line interface — full functionality without the GUI,
so it works over SSH on a headless box.

    airdriver                 # launch the GUI (or --no-gui to print scan)
    airdriver scan            # list detected adapters
    airdriver doctor          # system readiness check
    airdriver info <usb_id>   # database details for a chipset / id
    airdriver install [usb]   # plan + install a driver (--dry-run to preview)
    airdriver monitor <iface> # toggle monitor mode / injection test
    airdriver report          # write a diagnostic report
    airdriver db              # dump the chipset database
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, __codename__
from .core import detector, monitor as mon, report as rep, system, verify
from .core.chipset_db import ChipsetDB
from .core.installer import Executor, build_plan, build_remove_plan, select_driver

# --- tiny ANSI helpers (no dependency) ------------------------------------- #
_USE_COLOR = sys.stdout.isatty()


def _c(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _USE_COLOR else s


def bold(s): return _c(s, "1")
def green(s): return _c(s, "32")
def red(s): return _c(s, "31")
def yellow(s): return _c(s, "33")
def cyan(s): return _c(s, "36")
def dim(s): return _c(s, "2")


BANNER = rf"""{cyan(r'''
   ___  _     ___      _
  / _ |(_)___/ _ \____(_)  _____ ____
 / __ |/ / __/ // / __/ / |/ / -_) __/
/_/ |_/_/_/ /____/_/ /_/|___/\__/_/   ''')}  {bold('AirDriver')} {dim('v'+__version__)} · {dim(__codename__)}
  {dim('WiFi adapter driver auto-installer for Kali Linux & Parrot OS')}
"""


def _cap_badge(chip) -> str:
    mon_b = green("monitor") if chip.monitor_mode else dim("no-monitor")
    inj_b = green("injection") if chip.injection else dim("no-injection")
    return f"{mon_b} · {inj_b} · {dim(chip.injection_quality)}"


# --------------------------------------------------------------------------- #
# commands                                                                    #
# --------------------------------------------------------------------------- #
def cmd_scan(args, db: ChipsetDB) -> int:
    adapters = detector.detect(db)
    if not adapters:
        print(yellow("No WiFi adapters detected."))
        return 0
    print(bold(f"\nDetected {len(adapters)} adapter(s):\n"))
    for a in adapters:
        mark = green("●") if a.known else red("●")
        demo = dim(" [demo]") if a.is_demo else ""
        print(f" {mark} {bold(a.title)}  {dim('('+a.usb_id+')')}{demo}")
        print(f"     {a.status}")
        if a.chipset:
            print(f"     {_cap_badge(a.chipset)}")
            print(f"     {dim(a.chipset.band)}")
        else:
            print(f"     {yellow('Not in database — run: airdriver install ' + a.usb_id)}")
        print()
    return 0


def cmd_doctor(args, db: ChipsetDB) -> int:
    info = system.gather()
    print(bold("\nSystem readiness\n"))
    rows = [
        ("OS / distro", info.distro_name),
        ("Kernel", info.kernel_release),
        ("Architecture", info.arch),
        ("Root", "yes" if info.is_root else "no"),
        ("Internet", "yes" if info.has_internet else "no"),
        ("Kernel headers", "installed" if info.headers_installed else "MISSING"),
        ("DKMS", "installed" if info.dkms_installed else "MISSING"),
        ("Build tools", "installed" if info.build_tools else "MISSING"),
        ("Secure Boot", info.secure_boot),
    ]
    for k, v in rows:
        ok = v not in ("MISSING", "no", "on") or k in ("Internet", "Root")
        colour = green if v not in ("MISSING",) else red
        print(f"  {k:<16} {colour(str(v))}")
    blockers = info.blockers()
    if blockers:
        print(bold(yellow("\nBlockers to resolve before installing:")))
        for b in blockers:
            print(f"  {yellow('!')} {b}")
    else:
        print(green("\n✓ System looks ready to install drivers."))
    return 0


def cmd_info(args, db: ChipsetDB) -> int:
    key = args.target.lower()
    chip = db.match_usb(key) or db.get(key)
    if not chip:
        print(red(f"No chipset matches '{args.target}'."))
        return 1
    print(bold(f"\n{chip.name}") + dim(f"  ({chip.vendor})"))
    print(f"  {chip.wifi} · {chip.band}")
    print(f"  {_cap_badge(chip)}")
    print(f"\n  {chip.notes}\n")
    print(dim("  Known adapters: ") + ", ".join(chip.adapters))
    print(dim("  USB IDs: ") + ", ".join(chip.usb_ids))
    if chip.kernel_native:
        kn = chip.kernel_native
        print(dim(f"  In-kernel: {kn.module} (>= kernel {kn.min_kernel})"))
    print(bold("\n  Driver options (in order):"))
    for d in chip.best_drivers():
        detail = d.package or d.repo or d.path or d.module or ""
        print(f"    {d.priority}. {cyan(d.method)} {dim(detail)}")
    return 0


def cmd_install(args, db: ChipsetDB) -> int:
    info = system.gather()
    adapters = detector.detect(db)
    target = None
    if args.target:
        target = next((a for a in adapters if a.usb_id == args.target.lower()), None)
        if target is None:
            chip = db.match_usb(args.target) or db.get(args.target)
            if chip is None:
                print(red(f"'{args.target}' is not a detected adapter or known chipset."))
                return 1
            # Synthesize an adapter from the chipset id for a manual install.
            from .core.detector import Adapter
            vid, _, pid = (chip.usb_ids[0] if chip.usb_ids else "0000:0000").partition(":")
            target = Adapter(bus="-", device="-", vid=vid, pid=pid,
                             description=chip.name, chipset=chip)
    else:
        known = [a for a in adapters if a.known]
        if not known:
            print(yellow("No identifiable adapter found. See: airdriver scan"))
            return 1
        target = known[0]

    if not target.known:
        print(red("That adapter isn't in the database yet."))
        return _unknown_flow(target, db)

    plan = build_plan(target, info, force_dkms=args.force_dkms, prefer_offline=args.offline)
    print(BANNER)
    print(plan.describe())
    if args.dry_run:
        print(yellow("\n(dry run — nothing executed)"))
        return 0
    if not args.yes:
        ans = input(bold("\nProceed with install? [y/N] ")).strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 1
    Executor(info, dry_run=False).run(plan, log=print)

    # Honest post-install check — did the driver actually load and bind?
    if target.chipset and info.is_linux:
        print(bold("\n── Verification ─────────────────────────────"))
        h = verify.check(target.chipset, info, usb_id=target.usb_id)
        print(verify.describe(h))
        return 0 if h.ok else 2
    return 0


def _unknown_flow(adapter, db: ChipsetDB) -> int:
    print(bold("\nUnknown adapter — let's identify it.\n"))
    print(f"  USB ID : {adapter.usb_id}")
    print(f"  Name   : {adapter.description}\n")
    print("Pick the closest chipset from the database to try its driver:")
    chips = db.all()
    for i, c in enumerate(chips, 1):
        print(f"  {i:>2}. {c.name}  {dim('('+c.id+')')}")
    print(dim("  0. Cancel"))
    try:
        choice = int(input(bold("\nChipset number: ")).strip())
    except (ValueError, EOFError):
        return 1
    if choice <= 0 or choice > len(chips):
        return 1
    adapter.chipset = chips[choice - 1]
    print(green(f"\nTrying as {adapter.chipset.name}. "
                f"Consider reporting {adapter.usb_id} so we can add it to the DB."))
    info = system.gather()
    plan = build_plan(adapter, info)
    print(plan.describe())
    ans = input(bold("\nProceed? [y/N] ")).strip().lower()
    if ans in ("y", "yes"):
        Executor(info).run(plan, log=print)
    return 0


def cmd_monitor(args, db: ChipsetDB) -> int:
    iface = args.interface
    if args.action == "start":
        r = mon.enable_monitor(iface)
    elif args.action == "stop":
        r = mon.disable_monitor(iface)
    elif args.action == "test":
        r = mon.test_injection(iface)
    elif args.action == "killservices":
        r = mon.kill_interferers()
    else:
        return 1
    print(r.output)
    return 0 if r.ok else 2


def cmd_report(args, db: ChipsetDB) -> int:
    info = system.gather()
    adapters = detector.detect(db)
    report = rep.build(info, adapters)
    paths = rep.save(report, fmt=args.format)
    for p in paths:
        print(green(f"Wrote {p}"))
    return 0


def cmd_db(args, db: ChipsetDB) -> int:
    print(bold(f"\nChipset database ({len(db)} entries, updated {db.meta.get('updated')})\n"))
    for c in db.all():
        print(f"  {cyan(c.id):<28} {c.name}")
        print(f"      {_cap_badge(c)}  ·  {dim(c.band)}")
    return 0


def _resolve_chip(target, db: ChipsetDB):
    """Return (chipset, usb_id_or_None) from a usb id, a chipset id, or — when
    no target is given — the first detected adapter that's in the database."""
    if target:
        chip = db.match_usb(target)
        if chip:
            return chip, target.lower()
        chip = db.get(target.lower())
        return chip, None
    for a in detector.detect(db):
        if a.known:
            return a.chipset, a.usb_id
    return None, None


def cmd_verify(args, db: ChipsetDB) -> int:
    info = system.gather()
    chip, usb = _resolve_chip(args.target, db)
    if chip is None:
        print(red("No known adapter or chipset to verify. Try: airdriver scan"))
        return 1
    print(bold(f"\nVerifying {chip.name}…\n"))
    h = verify.check(chip, info, usb_id=usb)
    print(verify.describe(h))
    return 0 if h.ok else 2


def cmd_remove(args, db: ChipsetDB) -> int:
    info = system.gather()
    chip, _ = _resolve_chip(args.target, db)
    if chip is None:
        print(red(f"'{args.target}' is not a known adapter or chipset."))
        return 1
    plan = build_remove_plan(chip, info)
    print(plan.describe())
    if not args.yes:
        if input(bold("\nRemove the above? [y/N] ")).strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 1
    ok = Executor(info).run(plan, log=print)
    print(green("\n✓ Removed. Re-plug the adapter, then: airdriver install "
                f"{chip.id}") if ok else yellow("\nRemoval finished with warnings."))
    return 0 if ok else 2


def cmd_fix(args, db: ChipsetDB) -> int:
    """Reload the driver (depmod + modprobe) and re-verify — the quick 'it built
    but isn't loaded' rescue that avoids a full reinstall."""
    from .core.installer import InstallPlan, Step
    info = system.gather()
    chip, usb = _resolve_chip(args.target, db)
    if chip is None:
        print(red("Nothing to fix — no known adapter/chipset. Try: airdriver scan"))
        return 1
    mods = verify.expected_modules(chip)
    plan = InstallPlan(adapter=None, chipset=chip, method="fix",
                       summary=f"Reload driver for {chip.name}", needs_reboot=False)
    plan.steps.append(Step(title="Rebuild module dependency map",
                           shell="sudo depmod -a", privileged=True, optional=True))
    for m in mods:
        plan.steps.append(Step(
            title=f"Reload module '{m}'",
            shell=f"sudo modprobe -r {m} 2>/dev/null; sudo modprobe {m} 2>&1 || true",
            privileged=True, optional=True))
    Executor(info).run(plan, log=print)
    print(bold("\n── Verification ─────────────────────────────"))
    h = verify.check(chip, info, usb_id=usb)
    print(verify.describe(h))
    return 0 if h.ok else 2


def cmd_gui(args, db: ChipsetDB) -> int:
    try:
        from .gui.app import run as run_gui
    except ImportError as exc:
        print(red(f"GUI dependencies missing: {exc}"))
        print("Install with:  pip install PySide6")
        return 1
    return run_gui()


# --------------------------------------------------------------------------- #
# parser                                                                       #
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="airdriver",
                                description="WiFi adapter driver auto-installer for Kali/Parrot.")
    p.add_argument("--version", action="version", version=f"AirDriver {__version__}")
    p.add_argument("--no-gui", action="store_true", help="With no subcommand, scan instead of launching GUI.")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("scan", help="Detect WiFi adapters")
    sub.add_parser("doctor", help="Check system readiness")
    sub.add_parser("db", help="Show the chipset database")
    sub.add_parser("gui", help="Launch the graphical interface")

    pr = sub.add_parser("report", help="Write a diagnostic report")
    pr.add_argument("--format", choices=["json", "md", "both"], default="both")

    pi = sub.add_parser("info", help="Show database info for a chipset/usb id")
    pi.add_argument("target", help="usb id (0bda:8812) or chipset id (rtl8812au)")

    pin = sub.add_parser("install", help="Install a driver")
    pin.add_argument("target", nargs="?", help="usb id or chipset id (default: first known adapter)")
    pin.add_argument("--dry-run", action="store_true", help="Show the plan, change nothing")
    pin.add_argument("--yes", "-y", action="store_true", help="Don't prompt for confirmation")
    pin.add_argument("--force-dkms", action="store_true", help="Build DKMS even if an in-kernel driver exists")
    pin.add_argument("--offline", action="store_true", help="Prefer the bundled offline driver")

    pm = sub.add_parser("monitor", help="Monitor mode / injection test")
    pm.add_argument("action", choices=["start", "stop", "test", "killservices"])
    pm.add_argument("interface", nargs="?", default="wlan0")

    pvf = sub.add_parser("verify", help="Check a driver is installed, loaded & bound")
    pvf.add_argument("target", nargs="?", help="usb id / chipset id (default: first detected)")

    prm = sub.add_parser("remove", help="Cleanly remove a driver (for a fresh retry)")
    prm.add_argument("target", help="usb id or chipset id")
    prm.add_argument("--yes", "-y", action="store_true", help="Don't prompt")

    pfx = sub.add_parser("fix", help="Reload the driver (depmod + modprobe) and re-check")
    pfx.add_argument("target", nargs="?", help="usb id / chipset id (default: first detected)")
    return p


_DISPATCH = {
    "scan": cmd_scan, "doctor": cmd_doctor, "info": cmd_info, "install": cmd_install,
    "monitor": cmd_monitor, "report": cmd_report, "db": cmd_db, "gui": cmd_gui,
    "verify": cmd_verify, "remove": cmd_remove, "fix": cmd_fix,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = ChipsetDB.load()
    if not args.command:
        if args.no_gui:
            return cmd_scan(args, db)
        return cmd_gui(args, db)
    return _DISPATCH[args.command](args, db)


if __name__ == "__main__":
    sys.exit(main())
