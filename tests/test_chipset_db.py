"""Database integrity + lookup tests.

The whole point of these is to make the "same vid:pid in two chipsets silently
mis-identifies hardware" bug (which shipped once) impossible to re-introduce.
Pure stdlib unittest so it runs on a stock box with no pip installs.
"""
import unittest

from airdriver.core.chipset_db import ChipsetDB, data_path


class DataPath(unittest.TestCase):
    """`airdriver/data/` is a plain directory, not a package. Resolving it via
    ``resources.files('airdriver.data')`` raises on Python 3.9 (namespace
    package, origin=None) — which broke the CLI outright there. data_path()
    must resolve from the filesystem without touching importlib."""

    def test_finds_the_database(self):
        p = data_path("chipsets.json")
        self.assertTrue(p.is_file(), f"{p} should exist")

    def test_joins_nested_parts(self):
        p = data_path("drivers", "README.md")
        self.assertEqual(p.name, "README.md")
        self.assertEqual(p.parent.name, "drivers")

    def test_does_not_need_importlib(self):
        import airdriver.core.chipset_db as mod
        real = mod.resources

        class Boom:
            def files(self, _name):
                raise AssertionError("importlib.resources should not be needed")

        mod.resources = Boom()
        try:
            self.assertTrue(data_path("chipsets.json").is_file())
            self.assertGreaterEqual(len(ChipsetDB.load()), 52)
        finally:
            mod.resources = real


class DatabaseIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_loads_and_is_nonempty(self):
        self.assertGreaterEqual(len(self.db), 52)
        self.assertGreaterEqual(self.db.usb_id_count(), 1258)

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


class EvidenceBackedCapabilities(unittest.TestCase):
    """Capability flags are the promise this project makes, so the ones derived
    from the kernel's own source are pinned here. If someone 'helpfully' flips
    one to look better on paper, the suite says no."""

    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_qca6390_wcn6855_cannot_sniff(self):
        """ath11k sets hw_params.supports_monitor = false for these and then
        clears NL80211_IFTYPE_MONITOR at registration, so claiming monitor mode
        here would send people chasing an airmon-ng failure that cannot be fixed."""
        c = self.db.get("ath11k_qca6390")
        self.assertIsNotNone(c)
        self.assertFalse(c.monitor_mode)
        self.assertFalse(c.injection)

    def test_wcn7850_can_sniff(self):
        """The same table sets supports_monitor = true for WCN7850 — the flag has
        to distinguish it from its QCA6390 sibling, or the entry is just noise."""
        c = self.db.get("ath12k_wcn7850")
        self.assertIsNotNone(c)
        self.assertTrue(c.monitor_mode)

    def test_fullmac_broadcom_never_claims_monitor(self):
        """brcmfmac is FullMAC: it never goes through mac80211 and only offers
        monitor when firmware reports the feature, which consumer firmware doesn't."""
        for cid in ("brcmfmac", "broadcom_sta"):
            with self.subTest(chipset=cid):
                c = self.db.get(cid)
                self.assertIsNotNone(c)
                self.assertFalse(c.monitor_mode)
                self.assertFalse(c.injection)

    def test_injection_implies_monitor(self):
        """You cannot inject on a card that will not go into monitor mode."""
        for c in self.db.all():
            if c.injection:
                with self.subTest(chipset=c.id):
                    self.assertTrue(c.monitor_mode)

    def test_quality_matches_the_declared_scale(self):
        scale = set(self.db.meta["injection_quality_scale"])
        for c in self.db.all():
            with self.subTest(chipset=c.id):
                self.assertIn(c.injection_quality, scale)

    def test_ambiguous_ids_are_omitted_not_guessed(self):
        """050d:7050 and 0707:ee13 are each claimed by more than one kernel
        driver, so the chip cannot be known from the id. Better an 'unknown
        adapter' prompt than confidently installing the wrong driver."""
        for uid in ("050d:7050", "0707:ee13"):
            with self.subTest(usb_id=uid):
                self.assertIsNone(self.db.match_usb(uid))

    # Drivers that sit on mac80211 (softmac). mac80211 unconditionally adds
    # NL80211_IFTYPE_MONITOR in ieee80211_register_hw(), so unless the driver
    # explicitly clears it again — which only ath11k/ath12k do — these chipsets
    # can be put into monitor mode. Flagging one of them monitor=false tells a
    # user to go buy hardware they already own.
    MAC80211_DRIVERS = {
        "rtl8xxxu", "rtl8187", "rt2800usb", "rt73usb", "rt2500usb", "ath5k",
        "ath9k", "ath9k_htc", "carl9170", "zd1211rw", "p54usb", "ar5523",
        "mt7601u", "mt76x0u", "mt76x2u", "mt7921u", "mt7925u", "mt7921e",
        "rtlwifi", "iwlwifi", "ath10k_pci",
    }

    def test_mac80211_chipsets_are_not_marked_blind(self):
        for c in self.db.all():
            mod = c.kernel_native.module if c.kernel_native else ""
            base = mod.split("_")[0] if mod.startswith("rtw8") else mod
            if mod in self.MAC80211_DRIVERS or base in ("rtw88", "rtw89"):
                with self.subTest(chipset=c.id, module=mod):
                    self.assertTrue(
                        c.monitor_mode,
                        f"{c.id} uses the mac80211 driver '{mod}', which always advertises "
                        "monitor mode, so monitor_mode must not be false")
