# Changelog

All notable changes to AirDriver are documented here.

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
- **Dead/duplicate GUI code:** `run_diagnose`/`_on_diagnose_done` were each defined twice.
- **Socket leak** in the internet-connectivity check (used `create_connection` + `with`).

## [0.2.0] — 2026-06-19 · "Clean Install"

- Correct DKMS installs via the maintainer's own `install-driver.sh`, post-install
  verification (`verify`/`remove`/`fix`), rfkill/bring-up so a built driver actually works,
  the one-shot `diagnose` snapshot, and the Secure-Boot/headers doctor checks.

## [0.1.0] — 2026-06-13

- Initial release: adapter auto-detection, the chipset→driver database, the install
  engine (in-kernel / apt / DKMS-git / offline), the PySide6 GUI, and the CLI.
