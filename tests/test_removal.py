"""Regression tests for driver *removal* — the half of the lifecycle that used
to fail silently.

Three separate bugs made "remove the driver" a no-op or actively harmful:

  1. The DKMS search pattern was built from the module name (``88XXau``) and
     matched case-sensitively, but ``dkms status`` reports the *package* name
     (``rtl88xxau``). Nothing ever matched, so removal cheerfully reported
     success while removing nothing.
  2. The modprobe blacklist written during install was left behind, so after a
     "successful" removal the out-of-tree driver was gone *and* the in-kernel
     one was still forbidden — an adapter with no driver at all.
  3. ``Executor._maybe_sudo`` stripped every ``sudo `` in the script when
     running as root, including inside quoted help text, mangling the advice
     printed to the user.

Each test below pins one of those.
"""
import re
import shlex
import shutil
import subprocess
import unittest

from airdriver.core import manage
from airdriver.core.chipset_db import ChipsetDB
from airdriver.core.installer import Executor, build_remove_plan
from airdriver.core.modules import BLACKLIST_FILE
from airdriver.core.system import SystemInfo

# Realistic `dkms status` output, in both shapes DKMS emits, plus unrelated
# modules that must survive the sweep untouched.
DKMS_STATUS = """\
rtl88xxau/5.6.4.2, 6.6.15-amd64, x86_64: installed
8812au/5.6.4.2, 6.6.15-amd64, x86_64: installed
rtl8821cu/5.12.0, 6.6.15-amd64, x86_64: installed
virtualbox/7.0.14, 6.6.15-amd64, x86_64: installed
nvidia-current/535.183.01, 6.6.15-amd64, x86_64: installed
"""


def _kali(**over):
    base = dict(os="Linux", is_linux=True, distro_id="kali", distro_name="Kali",
                is_debian_based=True, arch="x86_64", kernel_release="6.6.0-amd64",
                headers_installed=True, dkms_installed=True, build_tools=True,
                secure_boot="off", is_root=True, has_internet=True)
    base.update(over)
    return SystemInfo(**base)


def _pattern_of(plan) -> str:
    """The regex the removal step feeds to grep.

    ``shlex.quote`` only adds quotes when the value needs them, so a pattern of
    a single word (``rtw89_pci``) arrives bare — parse it the way a shell would
    rather than assuming quotes.
    """
    for step in plan.steps:
        if step.shell and "PATTERN=" in step.shell:
            assignment = re.search(r"^PATTERN=(.*)$", step.shell, re.M).group(1)
            return shlex.split(assignment)[0]
    raise AssertionError("no DKMS removal step in plan")


def _grep(pattern: str, text: str) -> list[str]:
    """Run the real grep the plan would run, so the test exercises the actual
    shell behaviour rather than a Python approximation of it."""
    p = subprocess.run(["grep", "-iE", pattern], input=text,
                       capture_output=True, text=True)
    return [line.split(",")[0].split(":")[0]
            for line in p.stdout.splitlines() if line.strip()]


@unittest.skipUnless(shutil.which("grep"), "needs grep")
class DkmsPatternMatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_matches_the_package_name_dkms_actually_reports(self):
        """`88XXau` (module) must still find `rtl88xxau` (dkms package)."""
        plan = build_remove_plan(self.db.get("rtl8812au"), _kali())
        hits = _grep(_pattern_of(plan), DKMS_STATUS)
        self.assertIn("rtl88xxau/5.6.4.2", hits,
                      "case-sensitive match regression: removal would do nothing")

    def test_matches_the_unprefixed_form_too(self):
        plan = build_remove_plan(self.db.get("rtl8812au"), _kali())
        hits = _grep(_pattern_of(plan), DKMS_STATUS)
        self.assertIn("8812au/5.6.4.2", hits)

    def test_leaves_unrelated_modules_alone(self):
        plan = build_remove_plan(self.db.get("rtl8812au"), _kali())
        hits = " ".join(_grep(_pattern_of(plan), DKMS_STATUS))
        self.assertNotIn("virtualbox", hits)
        self.assertNotIn("nvidia", hits)

    def test_every_dkms_chipset_builds_a_matching_pattern(self):
        """No chipset may generate a pattern that matches nothing sane."""
        for chip in self.db.all():
            plan = build_remove_plan(chip, _kali())
            if not any(s.shell and "PATTERN=" in s.shell for s in plan.steps):
                continue
            pattern = _pattern_of(plan)
            self.assertTrue(pattern.strip(), f"{chip.id}: empty removal pattern")
            # It must at minimum match the chipset's own id, case-insensitively.
            self.assertTrue(_grep(pattern, f"{chip.id}/1.0, 6.6.0, x86_64: installed"),
                            f"{chip.id}: pattern {pattern!r} misses its own id")


class BlacklistIsUndone(unittest.TestCase):
    """Removing a driver must also drop the blacklist it installed, or the
    adapter is left with no usable driver at all."""

    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_blacklisted_chipset_removes_the_file(self):
        chip = next(c for c in self.db.all() if c.blacklist)
        plan = build_remove_plan(chip, _kali())
        shells = " ".join(s.shell or "" for s in plan.steps)
        self.assertIn(BLACKLIST_FILE, shells,
                      f"{chip.id}: removal never deletes {BLACKLIST_FILE}")
        self.assertIn("rm -f", shells)

    def test_in_kernel_modules_are_reloaded(self):
        chip = next(c for c in self.db.all() if c.blacklist)
        titles = " ".join(s.title for s in plan_titles(chip))
        for mod in chip.blacklist:
            self.assertIn(mod, titles)


def plan_titles(chip):
    return build_remove_plan(chip, _kali()).steps


class PurgePlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_purge_plan_is_buildable_and_safe(self):
        plan = manage.build_purge_plan(self.db, _kali())
        self.assertEqual(plan.method, "purge")
        shells = " ".join(s.shell or "" for s in plan.steps)
        # It must clean the blacklist, and must never touch in-kernel trees.
        self.assertIn(BLACKLIST_FILE, shells)
        self.assertNotIn("rm -rf /lib/modules", shells)

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_purge_shell_is_valid_bash(self):
        plan = manage.build_purge_plan(self.db, _kali())
        for step in plan.steps:
            if step.shell:
                p = subprocess.run(["bash", "-n"], input=step.shell,
                                   capture_output=True, text=True)
                self.assertEqual(p.returncode, 0,
                                 f"invalid bash in '{step.title}':\n{p.stderr}")

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_remove_shell_is_valid_bash(self):
        for chip in self.db.all():
            for step in build_remove_plan(chip, _kali()).steps:
                if step.shell:
                    p = subprocess.run(["bash", "-n"], input=step.shell,
                                       capture_output=True, text=True)
                    self.assertEqual(p.returncode, 0,
                                     f"{chip.id} / '{step.title}':\n{p.stderr}")


class SudoStripping(unittest.TestCase):
    """Running as root strips `sudo` from *commands* only — never from prose."""

    def setUp(self):
        self.root = Executor(_kali(is_root=True))
        self.user = Executor(_kali(is_root=False))

    def test_command_sudo_is_stripped_when_root(self):
        self.assertEqual(self.root._maybe_sudo("sudo depmod -a"), "depmod -a")
        self.assertEqual(self.root._maybe_sudo("a && sudo b || sudo c"), "a && b || c")
        self.assertEqual(
            self.root._maybe_sudo('if x; then sudo y; fi'), 'if x; then y; fi')

    def test_quoted_advice_keeps_its_sudo(self):
        shell = 'echo "could not switch — run: sudo usb_modeswitch -KW"'
        self.assertIn("sudo usb_modeswitch", self.root._maybe_sudo(shell),
                      "stripped sudo out of user-facing advice")

    def test_non_root_is_untouched(self):
        shell = "sudo depmod -a"
        self.assertEqual(self.user._maybe_sudo(shell), shell)


if __name__ == "__main__":
    unittest.main()
