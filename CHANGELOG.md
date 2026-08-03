# Changelog

All notable changes to AirDriver are documented here.

## [0.6.0] — 2026-08-02 · "Clean Sweep"

Teaches AirDriver about the Wi-Fi card that's already **inside** your laptop, makes
removing a driver actually remove it, and fixes button icons properly this time.

### Fixed — removal was quietly a no-op

- **`airdriver remove` removed nothing.** The DKMS search pattern was built from the
  *module* name and matched case-sensitively — but `dkms status` reports the *package*
  name. The driver for an RTL8812AU was looked up as `88XXau` while DKMS had it
  registered as `rtl88xxau`, nothing matched, and AirDriver reported a clean removal
  having done absolutely nothing. Matching is now case-insensitive and covers the module
  name, the chipset id, the apt package, and the common unprefixed form (`8812au`).
  `tests/test_removal.py` runs the real `grep` against real `dkms status` output.
- **Removal left the adapter with no driver at all.** Installing writes a modprobe
  blacklist so the in-kernel driver keeps its hands off the card. Removal never deleted
  it, so afterwards the out-of-tree driver was gone *and* the in-kernel one was still
  forbidden. Removal now deletes the blacklist and modprobes the in-kernel driver back.
- **`sudo` was stripped out of help text.** When running as root the executor did a blunt
  `str.replace("sudo ", "")` across the whole script, which also rewrote the word inside
  quoted messages — so advice that read "run: `sudo usb_modeswitch …`" lost its `sudo`
  and became wrong. Only `sudo` in command position is stripped now.
- **Installs reported unqualified success even when steps failed.** `Executor.run` built
  an `ok` flag it never updated. It now tracks optional-step failures and lists them.

### Fixed — button icons on Linux

- **Icons were rasterised once at 32px and rescaled by Qt to whatever the button asked
  for.** At the 16px icon size that meant a ~1.5px antialiased stroke got resampled down,
  which is why they looked faint or vanished depending on the desktop's scaling — and on
  fractional scaling (1.25x/1.5x, common under Wayland) it was worse. `icons.py` now
  paints through a **`QIconEngine`**, rendering on demand at exactly the size and
  device-pixel-ratio Qt requests. Verified rendering at 1x, 1.5x and 2x.
- **Two icons were geometrically broken.** The wrench was an unclosed arc that read as a
  random squiggle, and the refresh arrowhead was drawn detached from its arc. Both redrawn.
- **Default icon size 16px → 18px** with heavier strokes, so they hold up next to the label.
- **Every label inside a card drew its own dark rectangle.** The stylesheet's universal
  `QWidget { background: … }` rule painted the window colour behind child widgets too, so
  labels sitting on a lighter panel showed as mismatched boxes. Labels and checkboxes are
  transparent now.
- **The GUI now pins the Fusion style** unless you override it. Kali/Parrot commonly set
  `QT_QPA_PLATFORMTHEME=gtk3` (or ship qt6ct/Kvantum), and those themes restyle buttons
  with their own metrics and icon handling. Fusion is built into Qt, so it's also the one
  style guaranteed to exist on a minimal install. Override with `QT_STYLE_OVERRIDE`.
- The UI font is requested with a real fallback chain (`Inter → Cantarell → Noto Sans →
  DejaVu Sans`) instead of a single family that isn't installed on stock Kali.

### Added — the card inside your laptop

The database was almost entirely USB dongles, while "my Wi-Fi doesn't work on Kali" is
usually an *internal* card. **8 new families, +99 IDs — now 40 families / 858 IDs.**
Every id comes from the driver's own device table; capability flags are honest, including
the unflattering ones.

| Family | Covers | Monitor | Injection |
|---|---|:--:|:--:|
| `ath9k_pci` | Atheros AR5416–AR9565 PCIe | yes | **excellent** |
| `mt79xx_pci` | MediaTek MT7921E / MT7922 / MT7925E | yes | fair |
| `ath10k_pci` | QCA6174 / QCA9377 / QCA988x | yes | no |
| `iwlwifi_legacy` | Intel 7260 / 7265 / 3165 / 8260 / 8265 / 9260 / 9560 | yes | no |
| `intel_be200` | Intel WiFi 7 BE200 / BE201 | yes | no |
| `rtw89_pci` | RTL8852AE / 8852BE / 8852CE / 8922AE | yes | no |
| `rtlwifi_pci` | RTL8188CE / 8192CE / 8723AE / 8723BE / 8821AE | yes | no |
| `broadcom_sta` | Broadcom BCM43xx (`wl` / `b43`) | **no** | **no** |

If you have an `ath9k_pci` card you already own the best adapter in the room. If you have
Broadcom, AirDriver now says plainly that it cannot do monitor mode or injection and that
you need a USB adapter — rather than letting you spend an evening finding that out.

### Added — one command to clean up

- **`airdriver remove --all`** — removes every driver AirDriver installed, drops the
  blacklist, and hands your adapters back to their in-kernel drivers. DKMS entries are
  correlated against the chipset database first, so an unrelated module (VirtualBox,
  NVIDIA) is never caught in the sweep.
- **`uninstall.sh`** — a real uninstaller. Removes the launcher, venv, and blacklist;
  `--drivers` also clears the Wi-Fi drivers; `--all` additionally deletes the Secure Boot
  signing key. Defaults to *keeping* your drivers, because those are what make Wi-Fi work.
- **One-line install.** `install.sh` detects being piped from `curl`, clones itself to
  `/opt/airdriver`, and re-execs — so the README one-liner genuinely works.
- GUI: a **Remove all** button in the Drivers panel, listing exactly what will go before
  it goes. `Remove` gained a red icon and now explains that it un-blacklists too.
- `airdriver remove` gained `--dry-run`, and `--all` makes its `target` optional.
- `make test`, `make shots`, `make purge` targets.

### Changed
- `Executor.run()` now returns `False` when optional steps failed, so `airdriver remove` /
  `rebuild` / `sign` exit non-zero on a partial result instead of always claiming success.
- New icons: `eye`, `broom`, `chip`, `shield`, `plug`. `Preview plan` finally has one.

## [0.5.0] — 2026-07-27 · "Open Signal"

Fixes a UI regression that made buttons look broken on the machines AirDriver targets,
and makes contributing an unknown adapter a 30-second job.

### Fixed
- **Buttons appeared to have no icons on Kali/Parrot.** v0.3.0 and v0.4.0 put emoji
  (`🔧 📚 🩺 ⬇ 📋`) in button labels. A minimal Kali install has no emoji font, so those
  rendered as blank tofu boxes and the toolbar looked broken. All of them are replaced by
  **`airdriver/gui/icons.py`** — 16 icons drawn with QPainter, so they render identically
  on a bare box and a full desktop, at any DPI. Also swapped the risky `⟳`, `⚠` and `⬇`
  in log/help text for text that every default font set can show.
  `tests/test_gui_glyphs.py` now fails the build if an emoji reappears, or if a widget
  asks for an icon that doesn't exist.
- **Action-row labels were clipped** ("Install drive", "Export repor") once icons widened
  the buttons. The log actions moved onto the log header row, so the row can't overflow.

### Added — contributing back
- **`airdriver contribute`** — builds a complete, ready-to-file report for an unrecognised
  adapter (usb id, `lsusb` descriptors, kernel, distro, matching `dmesg` lines) and prints
  a pre-filled GitHub issue link. `--open` opens it. **Nothing is ever sent automatically:**
  the report describes the user's machine, so they read it and decide.
- GUI: a **Report this adapter** button next to *Identify as*, which shows the report,
  copies it to the clipboard, and offers to open the pre-filled issue.
- Structured **issue templates** (adapter / bug), a **PR template** whose checklist covers
  the ID-sourcing rules and the no-emoji rule, and **`CONTRIBUTING.md`** documenting how the
  database works and the three rules for adding IDs.

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
