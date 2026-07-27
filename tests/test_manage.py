"""Driver-management tests: DKMS inventory parsing, staleness detection, and
the generated rebuild/sign/modeswitch scripts.

The shell these produce runs as root on a user's machine, so every generated
step is syntax-checked, and the signing loop (the one that touches existing
kernel modules) is executed end-to-end against fake modules in a sandbox to
prove it signs them *and* leaves compressed modules compressed.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from airdriver.core import manage
from airdriver.core.chipset_db import ChipsetDB
from airdriver.core.system import SystemInfo


def _linux(**over):
    base = dict(os="Linux", is_linux=True, distro_id="kali", distro_name="Kali",
                is_debian_based=True, arch="x86_64", kernel_release="6.12.25-amd64",
                headers_installed=True, dkms_installed=True, build_tools=True,
                secure_boot="off", is_root=True, has_internet=True)
    base.update(over)
    return SystemInfo(**base)


class DkmsParsing(unittest.TestCase):
    """`dkms status` output has changed shape across dkms versions."""

    def _inventory(self, text):
        orig = manage._run
        manage._run = lambda cmd, timeout=15: (0, text)
        try:
            return manage.dkms_inventory()
        finally:
            manage._run = orig

    def test_modern_slash_format(self):
        mods = self._inventory(
            "8814au/5.8.5.1, 6.12.25-amd64, x86_64: installed\n"
            "rtl88x2bu/5.13.1, 6.12.25-amd64, x86_64: installed\n")
        self.assertEqual([m.name for m in mods], ["8814au", "rtl88x2bu"])
        self.assertTrue(mods[0].built_for("6.12.25-amd64"))

    def test_legacy_comma_format(self):
        mods = self._inventory("8812au, 5.6.4.2, 6.1.0-kali9-amd64, x86_64: installed\n")
        self.assertEqual(mods[0].name, "8812au")
        self.assertEqual(mods[0].version, "5.6.4.2")
        self.assertTrue(mods[0].built_for("6.1.0-kali9-amd64"))

    def test_added_state_without_kernel(self):
        mods = self._inventory("8188eu/1.0: added\n")
        self.assertEqual(mods[0].name, "8188eu")
        self.assertEqual(mods[0].kernels, [])
        self.assertFalse(mods[0].built_for("6.12.25-amd64"))

    def test_multiple_kernels_merge(self):
        mods = self._inventory(
            "8814au/5.8.5.1, 6.11.0-amd64, x86_64: installed\n"
            "8814au/5.8.5.1, 6.12.25-amd64, x86_64: installed\n")
        self.assertEqual(len(mods), 1)
        self.assertEqual(len(mods[0].kernels), 2)

    def test_garbage_is_ignored(self):
        self.assertEqual(self._inventory("dkms: command not found\n\n"), [])


class StatusLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def _status(self, dkms_text, info):
        orig_run, orig_loaded = manage._run, manage.loaded_modules
        manage._run = lambda cmd, timeout=15: (0, dkms_text)
        manage.loaded_modules = lambda: set()
        try:
            return manage.status(self.db, info)
        finally:
            manage._run, manage.loaded_modules = orig_run, orig_loaded

    def test_stale_driver_is_flagged(self):
        # built for the OLD kernel only — the classic post-upgrade breakage
        st = self._status("8814au/5.8.5.1, 6.11.0-amd64, x86_64: installed\n",
                          _linux(kernel_release="6.12.25-amd64"))
        self.assertFalse(st.healthy)
        self.assertEqual(len(st.stale), 1)
        self.assertTrue(any("rebuild" in m for m in st.messages))

    def test_current_driver_is_healthy(self):
        st = self._status("8814au/5.8.5.1, 6.12.25-amd64, x86_64: installed\n",
                          _linux(kernel_release="6.12.25-amd64"))
        self.assertTrue(st.healthy)
        self.assertEqual(st.stale, [])

    def test_secure_boot_without_key_warns(self):
        st = self._status("", _linux(secure_boot="on"))
        self.assertTrue(any("sign" in m for m in st.messages))

    def test_non_linux_is_honest(self):
        st = manage.status(self.db, SystemInfo(os="Darwin", is_linux=False))
        self.assertFalse(st.dkms_available)
        self.assertTrue(any("Linux-only" in m for m in st.messages))

    def test_module_maps_back_to_chipset(self):
        st = self._status("8814au/5.8.5.1, 6.12.25-amd64, x86_64: installed\n", _linux())
        self.assertTrue(any("8814AU" in c.upper()
                            for d in st.drivers for c in d.chipsets))


class GeneratedScripts(unittest.TestCase):
    """Every management plan must be valid, non-destructive shell."""

    def _plans(self):
        info = _linux(secure_boot="on", headers_installed=False)
        return {
            "rebuild": manage.build_rebuild_plan(info),
            "rebuild-one": manage.build_rebuild_plan(info, only="8814au"),
            "sign": manage.build_sign_plan(info),
            "modeswitch": manage.build_modeswitch_plan("0bda:1a2b"),
        }

    @unittest.skipUnless(shutil.which("bash"), "bash required")
    def test_all_steps_are_valid_bash(self):
        for name, plan in self._plans().items():
            for s in plan.steps:
                if s.kind == "cmd" and s.shell:
                    r = subprocess.run(["bash", "-n"], input=s.shell,
                                       capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0,
                                     f"{name}/{s.title}: {r.stderr}")

    def test_rebuild_uses_autoinstall_for_running_kernel(self):
        sh = " ".join(s.shell or "" for s in self._plans()["rebuild"].steps)
        self.assertIn("dkms autoinstall", sh)
        self.assertIn("uname -r", sh)

    def test_rebuild_installs_headers_when_missing(self):
        titles = [s.title for s in self._plans()["rebuild"].steps]
        self.assertTrue(any("headers" in t.lower() for t in titles))

    def test_sign_does_not_automate_enrollment(self):
        """mokutil --import needs a password the user chooses; automating it
        would hang. It must be explained, never executed."""
        plan = self._plans()["sign"]
        for s in plan.steps:
            self.assertNotIn("mokutil --import", s.shell or "")
        self.assertTrue(any("mokutil --import" in w for w in plan.warnings))

    def test_modeswitch_mentions_new_id_caveat(self):
        plan = self._plans()["modeswitch"]
        self.assertTrue(any("DIFFERENT USB id" in w for w in plan.warnings))


class SignLoopSandbox(unittest.TestCase):
    """Run the real signing loop against fake modules: it must sign every .ko
    (including nested ones) and restore compressed modules to their original
    compressed form — leaving them decompressed would confuse dkms/depmod."""

    @unittest.skipUnless(shutil.which("bash") and shutil.which("gzip"),
                         "bash + gzip required")
    def test_signs_and_recompresses(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dkms = root / "lib/modules/TESTK/updates/dkms/sub"
            dkms.mkdir(parents=True)
            (dkms.parent / "a.ko").write_text("A\n")
            (dkms / "c.ko").write_text("C\n")
            plain_b = dkms.parent / "b.ko"
            plain_b.write_text("B\n")
            subprocess.run(["gzip", "-f", str(plain_b)], check=True)

            scripts = root / "usr/src/linux-headers-TESTK/scripts"
            scripts.mkdir(parents=True)
            signer = scripts / "sign-file"
            signer.write_text('#!/usr/bin/env bash\necho "~SIGNED~" >> "$4"\n')
            signer.chmod(0o755)

            step = next(s for s in manage.build_sign_plan(_linux(kernel_release="TESTK")).steps
                        if s.title.startswith("Sign every"))
            sh = (step.shell
                  .replace('"$(uname -r)"', "TESTK")
                  .replace("/usr/src/linux-headers-", f"{root}/usr/src/linux-headers-")
                  .replace("/lib/modules/$K/build", f"{root}/lib/modules/$K/build")
                  .replace('"/lib/modules/$K/updates/dkms"',
                           f'"{root}/lib/modules/$K/updates/dkms"')
                  .replace("sudo ", "")
                  .replace("depmod -a", "true"))
            r = subprocess.run(["bash", "-c", sh], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            base = root / "lib/modules/TESTK/updates/dkms"
            self.assertTrue((base / "b.ko.gz").exists(), "gz module was not recompressed")
            self.assertFalse((base / "b.ko").exists(), "left a decompressed leftover")
            self.assertIn("~SIGNED~", (base / "a.ko").read_text())
            self.assertIn("~SIGNED~", (base / "sub/c.ko").read_text())
            unzipped = subprocess.run(["gzip", "-dc", str(base / "b.ko.gz")],
                                      capture_output=True, text=True).stdout
            self.assertIn("~SIGNED~", unzipped)


class Recommend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_best_pick_is_injection_capable(self):
        picks = manage.recommend(self.db)
        self.assertTrue(picks)
        self.assertTrue(all(c.injection and c.monitor_mode for c in picks))
        self.assertEqual(picks[0].injection_quality, "excellent")

    def test_band_filter(self):
        for c in manage.recommend(self.db, band="5"):
            self.assertTrue(any(k in c.band.lower() for k in ("5 ghz", "dual", "tri")))

    def test_no_injection_widens_the_pool(self):
        self.assertGreaterEqual(len(manage.recommend(self.db, need_injection=False, limit=50)),
                                len(manage.recommend(self.db, need_injection=True, limit=50)))


if __name__ == "__main__":
    unittest.main()
