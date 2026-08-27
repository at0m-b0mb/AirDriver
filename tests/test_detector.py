"""Hardware-detection tests, driven by a fake sysfs tree.

Detection is the one part of AirDriver that decides *what hardware you have*,
and getting it wrong is expensive in both directions: miss a real adapter and
the tool is useless, invent one and the user installs a driver for hardware
they do not own. Both used to be possible:

  * ``detect()`` fell back to demo adapters whenever ``lsusb`` was absent — on a
    minimal Kali box that meant three fabricated adapters on real hardware.
  * A leftover interface was paired with the first PCI adapter found, so with
    an internal card and a USB dongle plugged in, the dongle's ``wlan1`` could
    be reported against the internal card.

So the tree below is built on disk (real dirs, real symlinks) and enumerated
for real; nothing about sysfs parsing is mocked.
"""
import os
import tempfile
import unittest

from airdriver.core import detector
from airdriver.core.chipset_db import ChipsetDB

DB = ChipsetDB.load()

# A Realtek RTL8812AU and an Atheros AR9271 — both in the shipped database.
RTL8812AU = ("0bda", "8812")
AR9271 = ("0cf3", "9271")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class FakeSysfs:
    """Builds the handful of sysfs files AirDriver actually reads."""

    def __init__(self, root):
        self.root = root
        self.usb = os.path.join(root, "bus", "usb", "devices")
        self.pci = os.path.join(root, "bus", "pci", "devices")
        self.net = os.path.join(root, "class", "net")
        for d in (self.usb, self.pci, self.net):
            os.makedirs(d, exist_ok=True)

    def usb_device(self, name, vid, pid, product="", manufacturer="",
                   iface_class="ff", iface_subclass="ff", busnum="1", devnum="4"):
        dev = os.path.join(self.usb, name)
        _write(os.path.join(dev, "idVendor"), vid + "\n")
        _write(os.path.join(dev, "idProduct"), pid + "\n")
        _write(os.path.join(dev, "busnum"), busnum + "\n")
        _write(os.path.join(dev, "devnum"), devnum + "\n")
        if product:
            _write(os.path.join(dev, "product"), product + "\n")
        if manufacturer:
            _write(os.path.join(dev, "manufacturer"), manufacturer + "\n")
        # The interface directory is a sibling named "<device>:<config>.<iface>".
        iface = os.path.join(self.usb, name + ":1.0")
        _write(os.path.join(iface, "bInterfaceClass"), iface_class + "\n")
        _write(os.path.join(iface, "bInterfaceSubClass"), iface_subclass + "\n")
        return dev, iface

    def pci_device(self, slot, vid, pid, dev_class="0x028000"):
        dev = os.path.join(self.pci, slot)
        _write(os.path.join(dev, "vendor"), "0x" + vid + "\n")
        _write(os.path.join(dev, "device"), "0x" + pid + "\n")
        _write(os.path.join(dev, "class"), dev_class + "\n")
        return dev

    def netdev(self, name, device_dir, driver="", usb_product=None):
        """A wireless netdev whose ``device`` symlink points at ``device_dir``."""
        nd = os.path.join(self.net, name)
        os.makedirs(os.path.join(nd, "phy80211"), exist_ok=True)
        _write(os.path.join(nd, "address"), "00:11:22:33:44:55\n")
        _write(os.path.join(nd, "operstate"), "up\n")
        os.symlink(device_dir, os.path.join(nd, "device"))
        if driver:
            drv = os.path.join(self.root, "bus", "drv", driver)
            os.makedirs(drv, exist_ok=True)
            os.symlink(drv, os.path.join(device_dir, "driver"))
        if usb_product:
            vid, pid = usb_product
            _write(os.path.join(device_dir, "uevent"),
                   f"PRODUCT={vid.lstrip('0') or '0'}/{pid.lstrip('0') or '0'}/200\n")
        return nd


class DetectorTestCase(unittest.TestCase):
    """Neutralises the optional lsusb/pciutils enrichment so results depend
    only on the fake tree, not on whatever hardware the test runner has."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.fs = FakeSysfs(self.root)
        self._orig = (detector._lsusb_names, detector._lspci_names)
        detector._lsusb_names = lambda: {}
        detector._lspci_names = lambda: {}
        self.addCleanup(self._restore)

    def _restore(self):
        detector._lsusb_names, detector._lspci_names = self._orig
        self._tmp.cleanup()


class UsbEnumeration(DetectorTestCase):
    def test_known_adapter_found_without_lsusb(self):
        """The regression that matters: sysfs alone finds real hardware."""
        self.fs.usb_device("1-1", *RTL8812AU, product="802.11n NIC")
        found = detector._scan_usb(DB, self.root)
        self.assertEqual([a.usb_id for a in found], ["0bda:8812"])
        self.assertIsNotNone(found[0].chipset)
        self.assertEqual(found[0].transport, "usb")

    def test_root_hub_ignored(self):
        self.fs.usb_device("usb1", "1d6b", "0002", product="xHCI Host Controller")
        self.assertEqual(detector._scan_usb(DB, self.root), [])

    def test_unrelated_device_ignored(self):
        """A mouse is not in the database and says nothing about wireless."""
        self.fs.usb_device("1-2", "046d", "c52b", product="USB Receiver",
                           iface_class="03", iface_subclass="01")
        self.assertEqual(detector._scan_usb(DB, self.root), [])

    def test_bluetooth_radio_ignored(self):
        """Class 0xE0 is 'wireless controller', but subclass 0x01 is Bluetooth —
        offering it a Wi-Fi driver would be nonsense."""
        self.fs.usb_device("1-3", "8087", "0026", product="Bluetooth Adapter",
                           iface_class="e0", iface_subclass="01")
        self.assertEqual(detector._scan_usb(DB, self.root), [])

    def test_unknown_wireless_class_is_surfaced(self):
        """Not in the database, but it declares a non-Bluetooth wireless
        interface — surface it so the 'identify my adapter' flow can run."""
        self.fs.usb_device("1-4", "1234", "abcd", product="Generic NIC",
                           iface_class="e0", iface_subclass="02")
        found = detector._scan_usb(DB, self.root)
        self.assertEqual([a.usb_id for a in found], ["1234:abcd"])
        self.assertIsNone(found[0].chipset)

    def test_unknown_device_named_wireless_is_surfaced(self):
        self.fs.usb_device("1-5", "1234", "ef01", product="802.11ac WLAN Adapter",
                           iface_class="ff", iface_subclass="ff")
        self.assertEqual([a.usb_id for a in detector._scan_usb(DB, self.root)],
                         ["1234:ef01"])

    def test_description_prefers_lsusb_when_available(self):
        detector._lsusb_names = lambda: {"0bda:8812": "Realtek Semiconductor Corp. RTL8812AU"}
        self.fs.usb_device("1-1", *RTL8812AU, product="802.11n NIC")
        found = detector._scan_usb(DB, self.root)
        self.assertEqual(found[0].description, "Realtek Semiconductor Corp. RTL8812AU")

    def test_description_falls_back_to_sysfs_strings(self):
        self.fs.usb_device("1-1", *RTL8812AU, product="802.11n NIC",
                           manufacturer="Realtek")
        found = detector._scan_usb(DB, self.root)
        self.assertEqual(found[0].description, "Realtek 802.11n NIC")


class PciEnumeration(DetectorTestCase):
    def test_wireless_card_found(self):
        self.fs.pci_device("0000:03:00.0", "8086", "2723", dev_class="0x028000")
        found = detector._scan_pci(DB, self.root)
        self.assertEqual([a.usb_id for a in found], ["8086:2723"])
        self.assertEqual(found[0].transport, "pci")
        self.assertEqual(found[0].device, "0000:03:00.0")

    def test_ethernet_nic_ignored(self):
        """Subclass 0x00 is Ethernet. It must never be offered a Wi-Fi driver."""
        self.fs.pci_device("0000:00:1f.6", "8086", "15bb", dev_class="0x020000")
        self.assertEqual(detector._scan_pci(DB, self.root), [])

    def test_two_cards_keep_distinct_slots(self):
        self.fs.pci_device("0000:03:00.0", "8086", "2723")
        self.fs.pci_device("0000:04:00.0", "168c", "0030")
        slots = sorted(a.device for a in detector._scan_pci(DB, self.root))
        self.assertEqual(slots, ["0000:03:00.0", "0000:04:00.0"])


class Correlation(DetectorTestCase):
    def test_each_interface_attaches_to_its_own_device(self):
        """The mis-attribution bug: an internal card plus a USB dongle. Each
        netdev must land on the device that actually owns it."""
        pci = self.fs.pci_device("0000:03:00.0", "8086", "2723")
        usb_dev, usb_iface = self.fs.usb_device("1-1", *RTL8812AU,
                                                product="802.11ac WLAN Adapter")
        self.fs.netdev("wlan0", pci, driver="iwlwifi")
        # A USB netdev hangs off the *interface* directory, not the device.
        self.fs.netdev("wlan1", usb_iface, driver="88XXau")

        adapters = detector.detect(DB, sysfs_root=self.root)
        by_id = {a.usb_id: a for a in adapters}
        self.assertEqual(by_id["8086:2723"].interface.name, "wlan0")
        self.assertEqual(by_id["0bda:8812"].interface.name, "wlan1")

    def test_no_interface_is_invented_for_a_second_card(self):
        """One netdev, two adapters: the unbound one must stay unbound rather
        than inherit the other card's interface."""
        pci = self.fs.pci_device("0000:03:00.0", "8086", "2723")
        self.fs.usb_device("1-1", *AR9271, product="802.11n WLAN Adapter")
        self.fs.netdev("wlan0", pci, driver="iwlwifi")

        adapters = detector.detect(DB, sysfs_root=self.root)
        by_id = {a.usb_id: a for a in adapters}
        self.assertEqual(by_id["8086:2723"].interface.name, "wlan0")
        self.assertIsNone(by_id["0cf3:9271"].interface)
        self.assertNotIn("Working", by_id["0cf3:9271"].status)

    def test_lone_pair_is_matched_even_without_a_resolvable_path(self):
        """Exactly one adapter and one interface is unambiguous, so pair them
        even when the sysfs path did not resolve."""
        self.fs.usb_device("1-1", *RTL8812AU, product="802.11ac WLAN Adapter")
        stray = os.path.join(self.root, "devices", "somewhere-else")
        os.makedirs(stray, exist_ok=True)
        self.fs.netdev("wlan0", stray, driver="88XXau")

        adapters = detector.detect(DB, sysfs_root=self.root)
        self.assertEqual(adapters[0].interface.name, "wlan0")

    def test_driver_is_read_from_sysfs(self):
        pci = self.fs.pci_device("0000:03:00.0", "8086", "2723")
        self.fs.netdev("wlan0", pci, driver="iwlwifi")
        adapters = detector.detect(DB, sysfs_root=self.root)
        self.assertEqual(adapters[0].interface.driver, "iwlwifi")
        self.assertTrue(adapters[0].driver_loaded)


class DemoModeBoundary(DetectorTestCase):
    def test_no_sysfs_means_demo(self):
        """A macOS dev box has no sysfs — demo data is honest there."""
        empty = os.path.join(self.root, "not-sysfs")
        os.makedirs(empty, exist_ok=True)
        adapters = detector.detect(DB, sysfs_root=empty)
        self.assertTrue(adapters and all(a.is_demo for a in adapters))

    def test_no_sysfs_and_demo_disabled_means_empty(self):
        empty = os.path.join(self.root, "not-sysfs")
        os.makedirs(empty, exist_ok=True)
        self.assertEqual(detector.detect(DB, allow_demo=False, sysfs_root=empty), [])

    def test_linux_with_no_adapters_never_invents_any(self):
        """The regression this suite exists for. sysfs is present and lists no
        Wi-Fi hardware: the honest answer is 'none', never three fake adapters."""
        self.assertTrue(detector.have_sysfs(self.root))
        adapters = detector.detect(DB, sysfs_root=self.root)
        self.assertEqual(adapters, [])

    def test_linux_with_hardware_is_never_demo(self):
        self.fs.usb_device("1-1", *RTL8812AU, product="802.11ac WLAN Adapter")
        adapters = detector.detect(DB, sysfs_root=self.root)
        self.assertTrue(adapters)
        self.assertFalse(any(a.is_demo for a in adapters))


class HexParsing(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(detector._hex4("0x8086"), "8086")
        self.assertEqual(detector._hex4("0BDA"), "0bda")
        self.assertEqual(detector._hex4("bda"), "0bda")
        self.assertEqual(detector._hex4(""), "")
        self.assertEqual(detector._hex4("nonsense"), "")


if __name__ == "__main__":
    unittest.main()
