"""Smoke tests for the CLI surface — every subcommand should at least parse and
run without raising, and the machine-readable outputs should be valid."""
import io
import json
import unittest
from contextlib import redirect_stdout

from airdriver import cli
from airdriver.core.chipset_db import ChipsetDB


def _run(argv):
    """Run the CLI, capturing stdout. Returns (exit_code, stdout)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


class CliSmoke(unittest.TestCase):
    def test_version(self):
        with self.assertRaises(SystemExit) as cm:
            _run(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_db_check_passes(self):
        code, out = _run(["db", "--check"])
        self.assertEqual(code, 0, out)
        self.assertIn("healthy", out)

    def test_db_json_is_valid(self):
        code, out = _run(["db", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["families"], len(ChipsetDB.load()))
        self.assertIn("chipsets", data)

    def test_scan_json_is_valid(self):
        code, out = _run(["scan", "--json"])
        self.assertEqual(code, 0)
        self.assertIsInstance(json.loads(out), list)

    def test_info_known(self):
        code, out = _run(["info", "0bda:8812"])
        self.assertEqual(code, 0)
        self.assertIn("RTL8812AU", out)

    def test_info_unknown(self):
        code, _ = _run(["info", "dead:beef"])
        self.assertEqual(code, 1)

    def test_install_dry_run(self):
        # Should print a plan and change nothing (works in demo mode too).
        code, out = _run(["install", "rtl8812au", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("Plan", out)


if __name__ == "__main__":
    unittest.main()
