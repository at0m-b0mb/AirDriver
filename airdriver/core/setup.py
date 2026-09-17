"""The one command that goes from "I plugged it in" to "injection confirmed".

Every piece of this already existed as a separate verb — ``scan``, ``install``,
``verify``, ``monitor start``, ``monitor test``. Knowing *that sequence* was the
last bit of expertise AirDriver still demanded of you. ``airdriver setup`` runs
it end to end and finishes with a single honest verdict.

Honesty rules, same as the rest of the tool:

* A chipset the database says cannot sniff is **skipped**, not attempted and
  reported as a failure — that is hardware, not a broken install.
* A failed ``aireplay-ng --test`` means *injection was not confirmed here*. It
  can legitimately fail with no AP in range, so it never gets reported as "your
  driver is broken".
* Nothing claims success that was not observed. If a step could not run (no
  root, no ``aircrack-ng``), it says so and the verdict stays short of "ready".

The decision-making below (which adapter to target, what the stages add up to)
is deliberately pure so it can be unit-tested without hardware; the orchestrator
is a thin shell around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from . import detector, monitor as mon, system, verify
from .chipset_db import Chipset, ChipsetDB
from .detector import Adapter
from .installer import Executor, build_plan

LogFn = Callable[[str], None]

# Stage states, worst-last so a verdict can take the max.
OK, SKIP, WARN, FAIL = "ok", "skip", "warn", "fail"


@dataclass
class Stage:
    """One step of the run, and what it actually proved."""
    name: str
    state: str = OK
    detail: str = ""
    hint: str = ""

    @property
    def icon(self) -> str:
        return {OK: "✓", SKIP: "·", WARN: "!", FAIL: "✗"}.get(self.state, "?")


@dataclass
class Outcome:
    adapter: Optional[Adapter] = None
    stages: list = field(default_factory=list)
    headline: str = ""
    next_steps: list = field(default_factory=list)
    connected: bool = False   # driver bound → the adapter can carry traffic
    monitoring: bool = False  # confirmed in monitor mode
    injecting: bool = False   # aireplay-ng --test actually passed

    @property
    def ready(self) -> bool:
        """Pentest-ready: sniffing confirmed, and injection confirmed when the
        chipset claims to support it."""
        chip = self.adapter.chipset if self.adapter else None
        if not self.monitoring:
            return False
        if chip is not None and chip.injection:
            return self.injecting
        return True

    def add(self, name: str, state: str = OK, detail: str = "", hint: str = "") -> Stage:
        s = Stage(name, state, detail, hint)
        self.stages.append(s)
        return s


# --------------------------------------------------------------------------- #
# Pure decision logic (unit-tested without hardware)                           #
# --------------------------------------------------------------------------- #
_QUALITY = {"excellent": 4, "good": 3, "fair": 2, "poor": 1, "unknown": 0}


def adapter_score(a: Adapter) -> tuple:
    """Rank a detected adapter as a *pentest* target, best first when sorted
    descending. USB beats an internal card: internal Wi-Fi almost never injects."""
    chip = a.chipset
    if chip is None:
        return (-1, 0, 0, 0, 0)
    return (
        _QUALITY.get((chip.injection_quality or "unknown").lower(), 0),
        1 if chip.injection else 0,
        1 if chip.monitor_mode else 0,
        1 if a.transport == "usb" else 0,
        1 if a.interface is not None else 0,   # already present on the system
    )


def rank_adapters(adapters) -> list:
    """Known adapters, most pentest-capable first."""
    return sorted([a for a in adapters if a.known], key=adapter_score, reverse=True)


def pick_adapter(adapters, target: Optional[str] = None):
    """Choose what to set up. Returns ``(adapter_or_None, reason)``."""
    if target:
        t = target.lower().strip()
        for a in adapters:
            if a.usb_id == t or (a.chipset and a.chipset.id == t):
                return a, f"targeting {a.title}"
        return None, (f"'{target}' is not among the adapters plugged in right now. "
                      "Run 'airdriver scan' to see what is.")
    ranked = rank_adapters(adapters)
    if ranked:
        return ranked[0], f"picked {ranked[0].title} as the most capable adapter"
    if adapters:
        return None, ("None of the adapters plugged in are in the database yet. "
                      "Run 'airdriver contribute' to report one — it takes 30 seconds.")
    return None, ("No Wi-Fi adapters detected at all. Plug one in (try a USB 2.0 "
                  "port or a powered hub for high-power cards) and run 'airdriver scan'.")


def summarise(outcome: Outcome) -> Outcome:
    """Turn the stage list into a headline and concrete next steps."""
    ad = outcome.adapter
    chip = ad.chipset if ad else None
    name = chip.name if chip else "adapter"
    steps: list = []

    if ad is None:
        outcome.headline = "No adapter to set up."
        failed = [s for s in outcome.stages if s.state == FAIL]
        outcome.next_steps = [failed[0].hint or failed[0].detail] if failed else []
        return outcome

    # Order matters: a chipset that cannot inject is "ready" once it sniffs, but
    # saying "injection confirmed" about it would be a lie. That case goes first.
    if outcome.monitoring and chip is not None and not chip.injection:
        outcome.headline = (f"{name} is sniffing. This chipset cannot inject — that is the "
                            "hardware, not the install.")
        steps.append("For injection, use an AR9271, MT7612U or RTL8812AU adapter "
                     "(see: airdriver recommend).")
    elif outcome.ready:
        outcome.headline = f"{name} is pentest-ready — sniffing and injection both confirmed."
    elif outcome.monitoring:
        outcome.headline = f"{name} is in monitor mode, but injection was not confirmed."
        steps.append("Injection tests need an access point in range — move closer to one "
                     "and re-run:  sudo airdriver monitor test <iface>")
    elif outcome.connected:
        outcome.headline = f"{name} has a working driver, but it is not sniffing yet."
    else:
        outcome.headline = f"{name} does not have a working driver yet."

    for s in outcome.stages:
        if s.state in (FAIL, WARN) and s.hint:
            steps.append(s.hint)
    if outcome.connected and not steps:
        steps.append("Run 'airdriver diagnose' if anything still looks off.")
    # de-dupe, keep order
    seen, uniq = set(), []
    for s in steps:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    outcome.next_steps = uniq
    return outcome


def monitor_interface(default: str = "") -> str:
    """The interface currently in monitor mode, if any — airmon-ng renames
    ``wlan0`` to ``wlan0mon``, so the name we started with is often stale."""
    for i in detector.list_wireless_interfaces():
        if (i.mode or "").lower() in ("monitor", "mesh"):
            return i.name
    return default


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #
def run(db: ChipsetDB, *, target: Optional[str] = None, want_monitor: bool = True,
        want_inject: bool = True, dry_run: bool = False,
        log: LogFn = print) -> Outcome:
    out = Outcome()
    info = system.gather()
    adapters = detector.detect(db)

    # --- 1. which adapter ---------------------------------------------------
    ad, why = pick_adapter(adapters, target)
    out.adapter = ad
    if ad is None:
        out.add("Detect adapter", FAIL, why, hint=why)
        return summarise(out)
    out.add("Detect adapter", OK, f"{ad.title}  ({ad.usb_id}, {ad.transport.upper()})")
    chip: Chipset = ad.chipset

    # --- 2. can this hardware even do the job? ------------------------------
    if not chip.monitor_mode:
        out.add("Capability", WARN,
                f"{chip.name} cannot do monitor mode — it can get you online only.",
                hint="Use 'airdriver recommend' to pick an adapter that can sniff.")
        want_monitor = want_inject = False
    elif not chip.injection and want_inject:
        out.add("Capability", WARN,
                f"{chip.name} sniffs but does not inject ({chip.injection_quality}).",
                hint="For injection use an AR9271 / MT7612U / RTL8812AU adapter.")
        want_inject = False
    else:
        out.add("Capability", OK,
                f"monitor {'yes' if chip.monitor_mode else 'no'} · "
                f"injection {chip.injection_quality}")

    # --- 3. system readiness ------------------------------------------------
    blockers = info.blockers()
    if blockers:
        out.add("System readiness", WARN, "; ".join(blockers),
                hint="Run 'airdriver doctor' for the full list and the fix for each.")
    elif info.is_linux:
        out.add("System readiness", OK, f"kernel {info.kernel_release}, headers + DKMS present")
    else:
        # Don't claim checks that were never run: the readiness probes are all
        # gated on Linux, so off-Linux there is simply nothing to report.
        out.add("System readiness", SKIP,
                f"not Linux ({info.distro_name}) — nothing to check here")

    # --- 4. driver ----------------------------------------------------------
    before = verify.check(chip, info, usb_id=ad.usb_id)
    if before.ok:
        out.add("Driver", SKIP, f"already working on {before.interface} "
                                f"({before.loaded_module or 'in-kernel'}) — nothing to install")
    elif dry_run:
        plan = build_plan(ad, info)
        log(plan.describe())
        out.add("Driver", SKIP, "dry run — the plan above was not executed")
        return summarise(out)
    else:
        plan = build_plan(ad, info)
        log(plan.describe())
        Executor(info, dry_run=False).run(plan, log=log)
        out.add("Driver", OK, f"install plan ran ({plan.method})")

    # --- 5. verify it really bound -----------------------------------------
    health = verify.check(chip, info, usb_id=ad.usb_id)
    out.connected = health.ok
    if health.ok:
        out.add("Verify", OK, f"{health.loaded_module or 'driver'} bound to {health.interface}")
    else:
        hint = next((m for m in health.messages if m and not m.startswith("    ")), "")
        out.add("Verify", FAIL, f"driver not usable yet ({health.verdict})", hint=hint)
        return summarise(out)

    iface = health.interface or ""

    # --- 6. monitor mode ----------------------------------------------------
    if not want_monitor:
        out.add("Monitor mode", SKIP, "not requested" if chip.monitor_mode
                else "unsupported by this chipset")
        return summarise(out)

    tools = mon.tools_present()
    if not (tools.get("airmon-ng") or tools.get("iw")):
        out.add("Monitor mode", WARN, "neither airmon-ng nor iw is installed",
                hint="sudo apt install -y aircrack-ng iw")
        return summarise(out)

    r = mon.enable_monitor(iface)
    log(r.output)
    mif = monitor_interface(iface)
    if mon_is_active(mif):
        out.monitoring = True
        out.add("Monitor mode", OK, f"{mif} is in monitor mode")
    else:
        out.add("Monitor mode", FAIL, f"could not put {iface} into monitor mode",
                hint="Try:  sudo airmon-ng check kill  then re-run 'airdriver setup'. "
                     "NetworkManager often takes the interface back.")
        return summarise(out)

    # --- 7. injection -------------------------------------------------------
    if not want_inject:
        out.add("Injection", SKIP, "this chipset does not inject" if not chip.injection
                else "not requested")
        return summarise(out)
    if not tools.get("aireplay-ng"):
        out.add("Injection", WARN, "aireplay-ng is not installed, so injection is unproven",
                hint="sudo apt install -y aircrack-ng")
        return summarise(out)

    t = mon.test_injection(mif)
    log(t.output)
    if t.ok:
        out.injecting = True
        out.add("Injection", OK, f"aireplay-ng confirmed injection on {mif}")
    else:
        out.add("Injection", WARN, "aireplay-ng could not confirm injection here",
                hint="This test needs an AP in range — move closer and re-run:  "
                     f"sudo airdriver monitor test {mif}")
    return summarise(out)


def mon_is_active(iface: str) -> bool:
    """True when ``iface`` is really in monitor mode, read back from sysfs/iw
    rather than trusting airmon-ng's exit code."""
    if not iface:
        return False
    for i in detector.list_wireless_interfaces():
        if i.name == iface:
            return (i.mode or "").lower() in ("monitor", "mesh")
    return False


def describe(out: Outcome) -> str:
    """Render the run as the single screen the user actually reads."""
    lines = ["", "── Setup summary " + "─" * 44, ""]
    for s in out.stages:
        lines.append(f"  {s.icon} {s.name:<18} {s.detail}")
    lines.append("")
    lines.append(f"  {out.headline}")
    if out.next_steps:
        lines.append("")
        lines.append("  Next:")
        for n in out.next_steps:
            lines.append(f"    • {n}")
    lines.append("")
    return "\n".join(lines)
