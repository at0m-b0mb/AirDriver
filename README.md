<div align="center">

<img src="docs/banner.png" alt="AirDriver — WiFi adapter driver auto-installer for Kali Linux & Parrot OS" width="840">

<br/><br/>

![Platform](https://img.shields.io/badge/platform-Kali%20%7C%20Parrot%20%7C%20Debian-1f9e72?style=flat-square)
![Python](https://img.shields.io/badge/python-3.9%2B-2ee6a6?style=flat-square&logo=python&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-PySide6-38bdf8?style=flat-square&logo=qt&logoColor=white)
![Chipsets](https://img.shields.io/badge/chipsets-18%20families-f5a623?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)

**Plug in your adapter → AirDriver identifies the chipset → installs the right driver.**

Built for pentesters who just want monitor mode and packet injection to *work*.
`Realtek` · `Atheros` · `MediaTek/Ralink` — 18 chipset families · hybrid online/offline · a clean GUI **and** a full CLI.

</div>

---

## Why

Getting an Alfa/Panda/TP-Link adapter working on Kali or Parrot is a rite of passage:
figure out the chipset, find the *right* DKMS repo (half of them are abandoned),
install kernel headers, fight Secure Boot, blacklist the in-tree module… AirDriver
automates all of it and explains what it's doing.

It also solves the **catch-22**: no WiFi driver means no internet, which means you
can't *download* the driver. AirDriver can bundle driver sources offline and build
them on an air-gapped machine.

## Features

- 🔍 **Auto-detection** — enumerates USB (`lsusb`) and PCI (`lspci`) adapters, reads
  live wireless interfaces from sysfs, and maps `VID:PID` → chipset.
- 🧠 **Smart driver selection** — prefers the **in-kernel** driver when your kernel is
  new enough (no pointless DKMS build), otherwise apt → DKMS-from-git → offline bundle.
- 🌐 **Hybrid online/offline** — uses apt/git when connected, falls back to a
  pre-fetched offline copy when not.
- 🩺 **System doctor** — checks kernel headers, DKMS, build tools, **Secure Boot**, and
  root before it ever tries to build, so failures are caught early.
- 🚫 **Conflict handling** — blacklists in-tree modules (e.g. `r8188eu`) that hijack
  adapters meant for the out-of-tree driver.
- 📶 **Monitor mode + injection** — one-click enable/disable and an `aireplay-ng` self-test.
- 🖥️ **Polished GUI** (PySide6) **and** a complete **CLI** for headless/SSH boxes.
- 📄 **Diagnostic reports** — export JSON + Markdown, perfect for forum help threads.
- ❓ **Unknown-adapter flow** — if your `VID:PID` isn't known yet, pick the closest
  chipset to try and get a reminder to report it.

## Screenshots

<div align="center">

**Main view** — detected adapters, chipset details, capability badges, and live system status (headers · DKMS · Secure Boot):

<img src="docs/screenshots/gui-overview.png" alt="AirDriver main window" width="900">

<br/><br/>

**Unknown adapter?** Identify it from the dropdown and preview the full install plan before anything runs:

<img src="docs/screenshots/gui-install-plan.png" alt="AirDriver identify + install plan" width="900">

</div>

> Running on macOS for the screenshots above, AirDriver shows **demo adapters** so
> the GUI is fully previewable without hardware. On Kali/Parrot it detects your real adapters.

## Supported chipsets (v1)

| Chipset | Typical adapters | Bands | Monitor / Injection | Driver path |
|---|---|---|---|---|
| RTL8812AU | Alfa AWUS036ACH | 2.4+5 GHz AC1200 | ✓ / good | apt → DKMS → offline (in-kernel 6.13+) |
| RTL8811AU/8821AU | Alfa AWUS036ACS | 2.4+5 GHz AC600 | ✓ / fair | apt → DKMS → offline |
| RTL8814AU | Alfa AWUS1900 | 2.4+5 GHz AC1900 | ✓ / good | apt → DKMS → offline (in-kernel 6.15+) |
| RTL8811CU/8821CU | TP-Link T2U Nano/Plus | 2.4+5 GHz AC600 | ✓ / fair | DKMS → offline |
| RTL8188EUS | TL-WN722N **v2/v3** | 2.4 GHz N | ✓ / fair | DKMS (blacklists `r8188eu`) |
| RTL8192EU | TL-WN822N v4/v5 | 2.4 GHz N | ✓ / fair | apt → DKMS |
| RTL8187 | Alfa AWUS036H | 2.4 GHz G | ✓ / excellent | in-kernel |
| AR9271 | Alfa AWUS036NHA, TL-WN722N **v1** | 2.4 GHz N | ✓ / excellent | in-kernel + firmware |
| AR7010 | Alfa AWUS051NH v2 | 2.4+5 GHz N | ✓ / good | in-kernel + firmware |
| RT3070 / RT5370 | Alfa AWUS036NH, Panda | 2.4 GHz N | ✓ / good | in-kernel |
| MT7610U | Alfa AWUS036ACHM | 2.4+5 GHz AC600 | ✓ / good | in-kernel (4.19+) |
| MT7612U | Alfa AWUS036ACM | 2.4+5 GHz AC1200 | ✓ / **excellent** | in-kernel (4.19+) |
| MT7921AU | Alfa AWUS036AXML | WiFi 6E | ✓ / good | in-kernel (5.18+) |
| MT7925U | Netgear A9000 | WiFi 7 | ✓ / good | in-kernel (6.7+) |
| RTL8852BU/8832BU | Alfa AWUS036AXM | WiFi 6 | ✓ / fair | DKMS (morrownr) |
| RTL8852CU/8832CU | generic AXE | WiFi 6E | ✓ / fair | DKMS (morrownr) |

> The database lives in [`airdriver/data/chipsets.json`](airdriver/data/chipsets.json)
> and is trivial to extend — add a `VID:PID` or a whole chipset and AirDriver picks it up.

## Install

On Kali / Parrot:

```bash
git clone <your-repo-url> AirDriver && cd AirDriver
chmod +x install.sh
sudo ./install.sh
```

The installer sets up a venv, installs system prerequisites (`dkms`,
`build-essential`, kernel headers, `usbutils`, `aircrack-ng`, …) and the GUI deps,
then drops an `airdriver` launcher on your PATH.

> Core + CLI are **pure stdlib** — they run on a stock box with zero pip installs.
> Only the GUI needs `PySide6`.

### Bundle drivers for offline use (optional, do it while online)

```bash
./scripts/fetch_offline_drivers.sh
```

## Usage

### GUI

```bash
sudo airdriver           # launch the graphical app
```

Pick your adapter from the cards on the left, review the chipset details and the
proposed install plan, then hit **Install driver**. Watch progress stream in the
log. Use **Dry run** to preview without changing anything.

### CLI

```bash
airdriver scan                  # list detected adapters
airdriver doctor                # system readiness (headers, dkms, secure boot…)
airdriver info 0bda:8812        # database details for a usb id / chipset id
airdriver install               # install driver for the first known adapter
airdriver install rtl8812au --dry-run   # preview the plan for a chipset
airdriver install 0bda:c811 --offline   # force the bundled offline driver
airdriver monitor start wlan0   # enable monitor mode
airdriver monitor test wlan0    # aireplay-ng injection self-test
airdriver report                # write a JSON + Markdown diagnostic report
airdriver db                    # dump the chipset database
```

## How driver selection works

```
detect adapter ─► match VID:PID ─► chipset
                                     │
            ┌────────────────────────┼─────────────────────────────┐
   in-kernel driver exists      online?                        offline bundle
   & kernel new enough           │   │                          present?
        │                       yes  no                            │
   load + verify            apt pkg   └─► DKMS from git ◄───────────┘
   (no build)               (fast)        (compile + dkms install)
```

Before any build, AirDriver verifies kernel headers, DKMS, and build tools are
present, warns about Secure Boot, and blacklists conflicting in-tree modules.

## ⚠️ Responsible use

AirDriver installs drivers and toggles monitor mode for **authorized** wireless
security testing, research, and education. Monitor mode / packet injection on
networks you don't own or have written permission to test may be illegal. You are
responsible for staying within the law and your rules of engagement.

## Project layout

```
AirDriver/
├── airdriver/
│   ├── core/            # detection, database, system probes, install engine
│   │   ├── chipset_db.py    detector.py   system.py
│   │   ├── installer.py     monitor.py    modules.py   report.py
│   ├── data/chipsets.json   # the chipset → driver database
│   ├── data/drivers/        # offline driver bundle (populated by script)
│   ├── gui/             # PySide6 app (theme, main window)
│   └── cli.py           # full-featured command line
├── scripts/fetch_offline_drivers.sh
└── install.sh
```

## Roadmap ideas

- Community VID:PID submission endpoint for unknown adapters
- MOK signing helper for Secure Boot systems
- Per-adapter TX-power / regulatory region tweaks
- Bootable USB persistence profile
- AppImage / .deb packaging

## License

MIT © at0m-b0mb
