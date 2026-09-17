"""Tests for the end-to-end `airdriver setup` flow.

The orchestrator itself touches real hardware, so what is tested here is the
part that decides things: which adapter gets targeted, and what the finished
stage list actually adds up to. Those are pure functions precisely so they can
be pinned down without an adapter plugged in.
"""
import unittest

from airdriver.core import setup as S
from airdriver.core.chipset_db import ChipsetDB
from airdriver.core.detector import Adapter, WirelessInterface


def _chip(db, cid):
    c = db.get(cid)
    assert c is not None, cid
    return c


def _adapter(chip, transport="usb", iface=None, vid="0bda", pid="8813"):
    return Adapter(bus="1", device="2", vid=vid, pid=pid,
                   description=chip.name if chip else "unknown",
                   transport=transport, chipset=chip, interface=iface)


class AdapterChoice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def test_usb_injector_beats_internal_card(self):
        """An internal PCIe card must never be chosen over a USB injector: the
        whole point of the tool is the adapter you can actually attack with."""
        usb = _adapter(_chip(self.db, "ar9271"))                 # excellent injection
        pci = _adapter(_chip(self.db, "rtl8821ce"), transport="pci")  # connect-only
        best, why = S.pick_adapter([pci, usb])
        self.assertIs(best, usb, why)

    def test_better_injection_quality_wins(self):
        good = _adapter(_chip(self.db, "rtl8812au"))   # good
        exc = _adapter(_chip(self.db, "mt7612u"))      # excellent
        best, _ = S.pick_adapter([good, exc])
        self.assertIs(best, exc)

    def test_explicit_target_by_usb_id_and_chipset_id(self):
        a = _adapter(_chip(self.db, "ar9271"), vid="0cf3", pid="9271")
        b = _adapter(_chip(self.db, "mt7612u"), vid="0e8d", pid="7612")
        by_usb, _ = S.pick_adapter([a, b], target="0e8d:7612")
        self.assertIs(by_usb, b)
        by_chip, _ = S.pick_adapter([a, b], target="ar9271")
        self.assertIs(by_chip, a)

    def test_unknown_target_is_refused_not_guessed(self):
        a = _adapter(_chip(self.db, "ar9271"))
        got, why = S.pick_adapter([a], target="does:notexist")
        self.assertIsNone(got)
        self.assertIn("scan", why)

    def test_unknown_adapter_points_at_contribute(self):
        got, why = S.pick_adapter([_adapter(None)])
        self.assertIsNone(got)
        self.assertIn("contribute", why)

    def test_nothing_plugged_in(self):
        got, why = S.pick_adapter([])
        self.assertIsNone(got)
        self.assertIn("No Wi-Fi adapters", why)


class Verdict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ChipsetDB.load()

    def _mk(self, cid, **flags):
        o = S.Outcome(adapter=_adapter(_chip(self.db, cid)))
        for k, v in flags.items():
            setattr(o, k, v)
        return o

    def test_monitoring_alone_is_not_ready_for_an_injector(self):
        """The honesty rule: a chipset that *can* inject is only 'ready' once
        injection was actually observed, not merely because it sniffs."""
        o = self._mk("ar9271", connected=True, monitoring=True, injecting=False)
        self.assertFalse(o.ready)
        S.summarise(o)
        self.assertIn("not confirmed", o.headline)

    def test_injection_confirmed_is_ready(self):
        o = self._mk("ar9271", connected=True, monitoring=True, injecting=True)
        self.assertTrue(o.ready)
        S.summarise(o)
        self.assertIn("pentest-ready", o.headline)

    def test_monitor_only_chipset_is_ready_without_injection(self):
        """A chipset the DB says cannot inject must not be held to an injection
        bar it can never clear — that would blame hardware on the install."""
        chip = next(c for c in self.db.all() if c.monitor_mode and not c.injection)
        o = S.Outcome(adapter=_adapter(chip), connected=True, monitoring=True)
        self.assertTrue(o.ready)
        S.summarise(o)
        self.assertIn("cannot inject", o.headline)

    def test_driver_up_but_not_sniffing(self):
        o = self._mk("ar9271", connected=True, monitoring=False)
        self.assertFalse(o.ready)
        S.summarise(o)
        self.assertIn("not sniffing", o.headline)

    def test_no_driver_at_all(self):
        o = self._mk("ar9271")
        S.summarise(o)
        self.assertIn("does not have a working driver", o.headline)

    def test_no_adapter_surfaces_the_hint(self):
        o = S.Outcome()
        o.add("Detect adapter", S.FAIL, "nothing found", hint="plug one in")
        S.summarise(o)
        self.assertEqual(o.next_steps, ["plug one in"])

    def test_next_steps_are_deduped(self):
        o = self._mk("ar9271", connected=True)
        o.add("A", S.WARN, "x", hint="same hint")
        o.add("B", S.WARN, "y", hint="same hint")
        S.summarise(o)
        self.assertEqual(o.next_steps.count("same hint"), 1)


class MonitorInterface(unittest.TestCase):
    def tearDown(self):
        S.detector.list_wireless_interfaces = self._orig

    def setUp(self):
        self._orig = S.detector.list_wireless_interfaces

    def _fake(self, ifaces):
        S.detector.list_wireless_interfaces = lambda *a, **k: ifaces

    def test_finds_the_renamed_monitor_interface(self):
        """airmon-ng renames wlan0 -> wlan0mon, so the name we started with is
        stale; the monitor interface has to be read back from the system."""
        self._fake([WirelessInterface(name="wlan0mon", mode="monitor"),
                    WirelessInterface(name="eth0", mode="")])
        self.assertEqual(S.monitor_interface("wlan0"), "wlan0mon")

    def test_falls_back_to_the_given_name(self):
        self._fake([WirelessInterface(name="wlan0", mode="managed")])
        self.assertEqual(S.monitor_interface("wlan0"), "wlan0")

    def test_mon_is_active_reads_back_real_mode(self):
        """Trust sysfs, not airmon-ng's exit code."""
        self._fake([WirelessInterface(name="wlan0", mode="managed")])
        self.assertFalse(S.mon_is_active("wlan0"))
        self._fake([WirelessInterface(name="wlan0", mode="monitor")])
        self.assertTrue(S.mon_is_active("wlan0"))

    def test_mon_is_active_false_for_missing_iface(self):
        self._fake([])
        self.assertFalse(S.mon_is_active("wlan0"))
        self.assertFalse(S.mon_is_active(""))


if __name__ == "__main__":
    unittest.main()
