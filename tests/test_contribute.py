"""Tests for the community adapter-report builder.

Two things matter here: the report must contain what a maintainer needs, and the
URL must be a real, correctly-encoded GitHub issue link (it's the whole point of
the feature — a broken link means the report never arrives).
"""
import unittest
import urllib.parse

from airdriver.core import contribute
from airdriver.core.chipset_db import ChipsetDB
from airdriver.core.detector import Adapter
from airdriver.core.system import SystemInfo


def _info():
    return SystemInfo(os="Linux", is_linux=True, distro_name="Kali GNU/Linux Rolling",
                      arch="x86_64", kernel_release="6.12.25-amd64", secure_boot="off")


def _unknown():
    return Adapter(bus="001", device="005", vid="1a2b", pid="3c4d",
                   description="Generic 802.11ac WLAN Adapter", chipset=None)


class ReportBody(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_contains_the_essentials(self):
        r = contribute.build(_unknown(), _info(), self.db)
        for needle in ("1a2b:3c4d", "6.12.25-amd64", "Kali", "Generic 802.11ac"):
            self.assertIn(needle, r.body, f"report is missing {needle!r}")

    def test_says_when_unrecognised(self):
        r = contribute.build(_unknown(), _info(), self.db)
        self.assertIn("**no**", r.body)

    def test_known_adapter_names_its_chipset(self):
        chip = self.db.match_usb("0bda:8812")
        a = Adapter(bus="1", device="4", vid="0bda", pid="8812",
                    description="RTL8812AU", chipset=chip)
        r = contribute.build(a, _info(), self.db)
        self.assertIn("RTL8812AU", r.body)

    def test_title_is_useful_and_bounded(self):
        r = contribute.build(_unknown(), _info(), self.db)
        self.assertTrue(r.title.startswith("[adapter] 1a2b:3c4d"))
        self.assertLessEqual(len(r.title), 120)


class IssueUrl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()
        cls.rep = contribute.build(_unknown(), _info(), cls.db)

    def test_points_at_this_repo(self):
        u = urllib.parse.urlparse(self.rep.url)
        self.assertEqual(u.scheme, "https")
        self.assertEqual(u.netloc, "github.com")
        self.assertIn("at0m-b0mb/AirDriver/issues/new", u.path)

    def test_prefills_the_adapter_template(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.rep.url).query)
        self.assertEqual(q["template"], ["adapter.yml"])
        self.assertEqual(q["usb_id"], ["1a2b:3c4d"])
        self.assertIn("1a2b:3c4d", q["details"][0])

    def test_url_stays_within_github_limits(self):
        self.assertLess(len(self.rep.url), 8000)

    def test_body_is_url_encoded(self):
        # Raw newlines/spaces in a query string would truncate the link.
        self.assertNotIn("\n", self.rep.url)
        self.assertNotIn(" ", self.rep.url)

    def test_short_url_fallback(self):
        self.assertIn("issues/new", self.rep.short_url)
        self.assertNotIn(" ", self.rep.short_url)


if __name__ == "__main__":
    unittest.main()
