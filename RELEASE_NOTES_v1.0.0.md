# AirDriver v1.0.0 — "Clear Signal"

> Draft release notes, ready to publish. Delete this file once the release is out:
> `gh release create v1.0.0 --title 'AirDriver v1.0.0 — "Clear Signal"' --notes-file RELEASE_NOTES_v1.0.0.md`

**The first stable release.** A second security pass over everything that runs as root, six new chipset families cross-checked against the kernel's own device tables, and a GUI that tells you what is happening while it happens.

```console
$ sudo airdriver setup

  ✓ Detect adapter      ALFA AWUS036ACH  (0bda:8812, USB)
  ✓ Driver              install plan ran clean (dkms_git)
  ✓ Verify              88XXau bound to wlan1
  ✓ Monitor mode        wlan1mon is in monitor mode
  ✓ Injection           aireplay-ng confirmed injection on wlan1mon

  Realtek RTL8812AU is pentest-ready — sniffing and injection both confirmed.
```

## Security

**The chipset database was validated at review time, but not at load.** v0.9.1 wired `db --check` into CI, which stops a hostile *pull request*. It does nothing about the file as it exists on disk — it is plain JSON inside the install, users hand-edit it to add their own adapter, and `ChipsetDB.load(path)` will read one from anywhere. Nothing called that validation before the values were interpolated into commands running as root. Every value is now re-checked when the file is read, and anything unsafe is **dropped rather than executed** — dropped, not refused, because one bad entry must not take Wi-Fi away from a machine with no other way to get online. Every drop is reported.

**`airdriver fix` built `sudo modprobe {m}` by f-string** while every other call site quoted the same database-sourced value.

**A malicious USB descriptor could make the GUI fetch a URL.** A `QLabel` left in its default `AutoText` mode renders a string containing tags as *rich text*, and Qt then requests any resource it names — so a device reporting an `<img src="http://…">` tag as its product name was enough. Device-reported text is pinned to plain text and every database value in rich text is escaped, including the `dkms status` output in the driver table. There is a test.

Also: the Secure Boot signing key is created under `umask 077` and is 4096-bit; `contribute`'s `dmesg` filter no longer sweeps other peripherals into a public issue; interface names are validated before reaching a tool under `sudo`.

## Correctness

`setup <usb_id>` crashed on an adapter that is plugged in but unrecognised. The Driver stage reported success whatever the executor returned. An adapter with no bound driver was reported as "Working". Closing the GUI mid-install aborted the process. A stuck step hung forever — steps now run with stdin closed and a 45-minute ceiling. The details pane showed the previous adapter's specs. `monitor` defaulted to a hardcoded `wlan0`. Reports written under `sudo` landed in `/root`, where the person who asked for one cannot open them.

## Database: 52 → 58 families, 1258 → 1286 IDs

Cross-checked against the kernel's own device tables — fetched and diffed, not recalled.

New: **RTL8822CU**, **RTL8723DU**, **MT7663U**, **MT7915/MT7916**, **MT7996/MT7992** (Wi-Fi 7) and **RS9113/RS9116**, plus the complete in-kernel MediaTek PCIe table.

**One real mis-assignment fixed:** `1740:0605` was filed under AR9170, whose kernel table contains no `0x1740` id at all — it is an rt2800usb device, and AirDriver was offering it an Atheros driver.

**Seven contested ids are no longer guessed at.** Each is claimed by two or more drivers because two different chips shipped behind the same id. Guessing is the worst option available: the install blacklists the other driver's module, so a wrong guess leaves the adapter with *no* driver at all. They live in a `contested_ids` map, and AirDriver explains instead of choosing.

**Injection-grade chipsets prefer the out-of-tree driver again.** `rtw88` gained in-kernel RTL8812AU/8814AU support, which made AirDriver skip the DKMS build for the AWUS036ACH and AWUS1900 and quietly hand pentesters the driver the database itself calls worse for injection. `--prefer-kernel` takes the fast path when you only need to get online.

## GUI

A verdict strip answering "is this adapter ready?", a real progress bar driven by the executor's own step headers, a colour-coded log, adapters ranked with the most capable flagged **BEST**, a spec grid instead of a paragraph, and thirteen keyboard shortcuts.

## Tests: 125 → 174

`tests/test_gui_smoke.py` exists because of one specific trap: **an exception raised inside a Qt slot never reaches the caller.** Qt catches it, prints it to stderr and carries on — so a panel that blew up half-way through drawing still "renders" and the test still passes. Each test installs a collecting `sys.excepthook`, spins the real event loop, and asserts nothing was raised.

`scripts/fmt_chipsets.py` is the database formatter, now in the repo and checked by CI: reformatting `chipsets.json` turns a one-line change into a 1 200-line diff, which is how a bad id slips through review.

---

**Install:**

```bash
curl -fsSL https://raw.githubusercontent.com/at0m-b0mb/AirDriver/main/install.sh | sudo bash
sudo airdriver setup
```

Full detail in the [CHANGELOG](https://github.com/at0m-b0mb/AirDriver/blob/main/CHANGELOG.md). Browse every supported chipset at [at0m-b0mb.github.io/AirDriver](https://at0m-b0mb.github.io/AirDriver/).
