"""AirDriver — WiFi adapter driver auto-installer for Kali Linux & Parrot OS.

AirDriver detects your USB/PCI WiFi adapter, identifies its chipset, and
installs the correct driver automatically — picking the in-kernel module when
one already exists, an apt package when online, a DKMS build from git, or a
bundled offline copy when there is no internet (the classic "no driver -> no
WiFi -> can't download the driver" catch-22).
"""

from .version import __version__, __codename__

__all__ = ["__version__", "__codename__"]
