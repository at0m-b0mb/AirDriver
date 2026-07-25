"""Install-engine tests: method selection + the apt→source auto-fallback.

These build plans against synthetic SystemInfo objects (no real hardware), and
syntax-check the generated shell with ``bash -n`` when bash is available.
"""
import shutil
import subprocess
import unittest

from airdriver.core.chipset_db import ChipsetDB
from airdriver.core.detector import Adapter
from airdriver.core.installer import build_plan, build_remove_plan, select_driver
from airdriver.core.system import SystemInfo


def _kali(**over):
    base = dict(os="Linux", is_linux=True, distro_id="kali", distro_name="Kali",
                is_debian_based=True, arch="x86_64", kernel_release="6.6.0-amd64",
                headers_installed=True, dkms_installed=True, build_tools=True,
                secure_boot="off", is_root=True, has_internet=True)
    base.update(over)
    return SystemInfo(**base)


class MethodSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_in_kernel_skips_build(self):
        # ath9k_htc is in-kernel forever; when the DB says the module is native
        # for this kernel, select_driver returns None (no build). Use is_linux
        # False so the result doesn't depend on the test host having modinfo.
        chip = self.db.get("ar9271")
        opt, reason = select_driver(chip, _kali(is_linux=False, kernel_release="6.6.0"))
        self.assertIsNone(opt, "expected the in-kernel path (no DriverOption)")
        self.assertIn("no build needed", reason)

    def test_old_kernel_uses_apt(self):
        chip = self.db.get("rtl8812au")   # in-kernel only from 6.14
        opt, _ = select_driver(chip, _kali(kernel_release="6.6.0"))
        self.assertIsNotNone(opt)
        self.assertEqual(opt.method, "apt")

    def test_force_dkms_avoids_native(self):
        chip = self.db.get("rtl8812au")
        opt, _ = select_driver(chip, _kali(kernel_release="6.20.0"), force_dkms=True)
        self.assertIsNotNone(opt)
        self.assertNotEqual(opt.method, "kernel_native")


class AptFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def _apt_plan(self, has_internet=True):
        chip = self.db.get("rtl8812au")
        a = Adapter(bus="1", device="4", vid="0bda", pid="8812",
                    description="x", chipset=chip)
        return build_plan(a, _kali(kernel_release="6.6.0", has_internet=has_internet))

    def test_apt_step_has_source_fallback(self):
        plan = self._apt_plan()
        self.assertEqual(plan.method, "apt")
        step = next(s for s in plan.steps if "auto-compiles" in s.title)
        # Falls back to cloning the maintainer's driver and building it.
        self.assertIn("git clone", step.shell)
        self.assertIn("install-driver.sh", step.shell)
        # And it installs build prerequisites only inside the fallback branch.
        self.assertIn("linux-headers", step.shell)

    def test_apt_step_loads_the_module(self):
        plan = self._apt_plan()
        # apt DKMS packages don't set option.module, but we still add a load step.
        self.assertTrue(any("modprobe 88XXau" in (s.shell or "") for s in plan.steps))

    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_generated_shell_is_valid_bash(self):
        plan = self._apt_plan()
        for s in plan.steps:
            if s.kind == "cmd" and s.shell:
                r = subprocess.run(["bash", "-n"], input=s.shell,
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0,
                                 f"bad shell in step {s.title!r}:\n{r.stderr}")


class RemovePlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_remove_dkms_chip(self):
        plan = build_remove_plan(self.db.get("rtl8814au"), _kali())
        self.assertTrue(any("dkms" in (s.shell or "").lower() for s in plan.steps))

    def test_remove_inkernel_only_is_noop(self):
        # rtl8187 is purely in-kernel — nothing to uninstall.
        plan = build_remove_plan(self.db.get("rtl8187"), _kali())
        self.assertTrue(any(s.kind == "note" for s in plan.steps))


if __name__ == "__main__":
    unittest.main()
