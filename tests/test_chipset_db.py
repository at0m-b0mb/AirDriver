"""Database integrity + lookup tests.

The whole point of these is to make the "same vid:pid in two chipsets silently
mis-identifies hardware" bug (which shipped once) impossible to re-introduce.
Pure stdlib unittest so it runs on a stock box with no pip installs.
"""
import unittest

from airdriver.core.chipset_db import ChipsetDB


class DatabaseIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_loads_and_is_nonempty(self):
        self.assertGreaterEqual(len(self.db), 29)
        self.assertGreaterEqual(self.db.usb_id_count(), 200)

    def test_no_problems(self):
        problems = self.db.problems()
        self.assertEqual(problems, [], "database self-check found problems:\n  "
                         + "\n  ".join(problems))

    def test_every_usb_id_is_unique(self):
        seen = {}
        for c in self.db.all():
            for uid in c.usb_ids:
                self.assertNotIn(uid, seen,
                                 f"{uid} in both {seen.get(uid)} and {c.id}")
                seen[uid] = c.id

    def test_usb_ids_are_lowercase_vid_pid(self):
        import re
        pat = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
        for c in self.db.all():
            for uid in c.usb_ids:
                self.assertRegex(uid, pat, f"{c.id}: bad id {uid}")

    def test_chipset_ids_unique(self):
        ids = [c.id for c in self.db.all()]
        self.assertEqual(len(ids), len(set(ids)))


class KnownLookups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_classic_ids(self):
        self.assertEqual(self.db.match_usb("0bda:8812").id, "rtl8812au")
        self.assertEqual(self.db.match_usb("0cf3:9271").id, "ar9271")
        self.assertEqual(self.db.match_usb("0e8d:7612").id, "mt7612u")

    def test_resolved_conflicts(self):
        # These two ids used to be double-mapped; authoritative morrownr lists
        # put a811 on the 8821au and a822 on the 8812au. Lock that in.
        self.assertEqual(self.db.match_usb("0bda:a811").id, "rtl8821au")
        self.assertEqual(self.db.match_usb("7392:a822").id, "rtl8812au")

    def test_new_rtl8710bu_family(self):
        chip = self.db.get("rtl8710bu")
        self.assertIsNotNone(chip)
        self.assertEqual(self.db.match_usb("0bda:b711").id, "rtl8710bu")
        self.assertFalse(chip.injection)   # honest: connect-only

    def test_case_insensitive_match(self):
        self.assertEqual(self.db.match_usb("0BDA:8812").id, "rtl8812au")

    def test_unknown_returns_none(self):
        self.assertIsNone(self.db.match_usb("dead:beef"))


if __name__ == "__main__":
    unittest.main()
