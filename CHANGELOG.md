# Changelog

All notable changes to AirDriver are documented here.

## [0.4.0] — 2026-07-26 · "Field Kit"

Turns AirDriver from an *installer* into a driver **manager**, and roughly triples the
hardware it recognises.

### Added — driver management
- **`airdriver status`** — the dashboard that was missing: every DKMS driver on the box,
  which kernels it's built for, whether it's built for the one you're *running*, whether
  it's loaded, and which chipset it serves. `--json` for scripts.
- **`airdriver rebuild`** — the fix for the single most common way Wi-Fi breaks on Kali:
  you `apt full-upgrade`, reboot into a new kernel, and the out-of-tree module was never
  built for it. Installs matching headers if needed, runs `dkms autoinstall`, re-checks.
- **`airdriver sign`** — Secure Boot support. Generates a MOK signing key once, signs every
  DKMS module built for the running kernel (correctly decompressing and **recompressing**
  `.ko.xz`/`.ko.zst`/`.ko.gz`), then prints the one step that needs a password you choose:
  `mokutil --import` + reboot. Enrollment is deliberately never automated.
- **`airdriver modeswitch`** — many cheap dongles enumerate as a fake CD-ROM full of Windows
  drivers and never appear as Wi-Fi. AirDriver now detects that state during a scan and can
  eject it with `usb_modeswitch`.
- **`airdriver recommend`** — ranks the chipsets that genuinely do monitor mode *and*
  injection, preferring ones needing no driver build. `--band 2.4|5`.
- GUI: a **🔧 Drivers** panel showing the same status with one-click Rebuild and Sign, and a
  scan-time warning when an adapter is stuck in storage mode.

### Changed
- Chipset database grown to **32 families / 759 unique USB+PCI IDs** (from 29 / 218). Every
  new id is extracted from the Linux kernel's own driver device tables — `rtl8xxxu` (split
  per chip via its `*_fops` markers), `rt2800usb`, `ath9k_htc` (AR9271 vs AR7010 via
  `driver_info`), `carl9170`, `mt76x0u`/`mt76x2u`/`mt7601u`/`mt7921u`/`mt7925u`,
  `rtw88`/`rtw89` and `rtl8187` — so nothing is guessed.
- New families: **RTL8723AU**, **RTL8192FU** (needs kernel 6.2+), and **RT2800-series
  (other)** — a catch-all covering 300+ rebadged in-kernel `rt2800usb` adapters that
  previously showed up as "unknown".
- `chipsets.json` is now written with wrapped id lists, so a 300-entry array stays readable.

### Fixed
- **Eight more mis-assigned USB IDs**, caught by cross-checking the kernel tables:
  `2357:0106` (RTL8814AU, was 8812au), `2357:0108`/`2357:0109` (RTL8192EU, were 8812au),
  `7392:b611` (RTL8821AU, was 8192eu), and `0b05:17d1`/`148f:760a`/`2357:0123`/`7392:b711`
  (MT7610U, were mt7612u/mt7601u). Each would have installed the wrong driver.
- `Executor` crashed with `AttributeError` on any plan without a chipset — which the new
  management plans are. It now labels those by method instead.

## [0.3.0] — 2026-07-25 · "Full Spectrum"

Broader, more accurate device coverage; installs that find a way to succeed; and a
first real test-suite + CI so it stays that way.

### Added
- **Automatic apt→source fallback.** When the chosen apt driver package is missing or
  hasn't caught up with your running kernel, the install step now transparently compiles
  the maintainer's driver from git in the same run — installing the build prerequisites
  on the fly — instead of failing. One "Install" still ends in a working driver.
- **New chipset family:** Realtek **RTL8710BU / RTL8188GU** (module `8188gu`, the
  `lwfinger/rtl8188gu` driver) — the newer budget 2.4 GHz nano dongles (e.g. Tenda W311MI).
- **In-GUI monitor-mode & injection panel** — enable/disable monitor mode and run the
  `aireplay-ng` injection self-test from the window (previously CLI-only).
- **Searchable chipset browser** in the GUI (**📚 Chipsets**), filtering all families and
  IDs by name, vendor, band, or `vid:pid`; plus a live DB-size pill in the status strip.
- **Scriptable output:** `airdriver scan --json` and `airdriver db --json`.
- **`airdriver db --check`** validates the database (unique IDs, valid driver methods,
  unique priorities) and exits non-zero on any problem.
- **`airdriver monitor status`** — show each wireless interface's current mode.
- **Test-suite** (`tests/`, pure-stdlib `unittest`) and **GitHub Actions CI** running the
  tests across Python 3.9–3.13 plus a headless PySide6 GUI import smoke-test.
- `scripts/gen_screenshots.py` to regenerate the docs screenshots headlessly.

### Changed
- Chipset database grown to **29 families / 218 unique USB/PCI IDs** (was 28 / ~160),
  expanded from the authoritative morrownr `supported-device-IDs` lists.
- The apt install path now also loads the driver module afterward (apt DKMS packages
  don't advertise a module name), so a successful apt install is a *loaded* driver.

### Fixed
- **Duplicate / mis-assigned USB IDs.** `0bda:a811` and `7392:a822` (and several Edimax /
  TP-Link `AU`/`CU`/`BU` IDs) were mapped to two chipsets at once, so lookups silently
  resolved to whichever loaded last and could mis-identify hardware. All IDs are now
  unique and matched to the correct chipset per the maintainer lists — enforced by tests.
- **AirDriver would not run at all on Python 3.9–3.11** (the versions Kali/Parrot ship),
  caught by the new CI matrix:
  - `cli.py` inlined a backslash-containing raw string inside an f-string expression —
    a `SyntaxError` before 3.12, so the CLI failed to even import.
  - `resources.files("airdriver.data")` raised `TypeError` on 3.9 because `data/` is a
    namespace directory; the chipset database now resolves from the filesystem first.
- **Dead/duplicate GUI code:** `run_diagnose`/`_on_diagnose_done` were each defined twice.
- **Socket leak** in the internet-connectivity check (used `create_connection` + `with`).

## [0.2.0] — 2026-06-19 · "Clean Install"

- Correct DKMS installs via the maintainer's own `install-driver.sh`, post-install
  verification (`verify`/`remove`/`fix`), rfkill/bring-up so a built driver actually works,
  the one-shot `diagnose` snapshot, and the Secure-Boot/headers doctor checks.

## [0.1.0] — 2026-06-13

- Initial release: adapter auto-detection, the chipset→driver database, the install
  engine (in-kernel / apt / DKMS-git / offline), the PySide6 GUI, and the CLI.
