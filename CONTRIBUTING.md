# Contributing to AirDriver

The most valuable contribution is **adapter data**. AirDriver is only as good as its
chipset database, and no one person owns every Wi-Fi dongle ever rebadged.

## Report an adapter (30 seconds)

If AirDriver doesn't recognise your adapter — or matches it to the wrong chipset:

```bash
airdriver contribute            # builds the whole report for you
airdriver contribute --open     # …and opens the pre-filled issue
```

It gathers the `vid:pid`, the `lsusb` descriptors, your kernel, and the relevant
`dmesg` lines. **Nothing is sent automatically** — you review the text and decide
whether to submit it. In the GUI, select the adapter and press **Report this adapter**.

## Add a chipset or USB ID yourself

The whole database is one file: [`airdriver/data/chipsets.json`](airdriver/data/chipsets.json).
No code changes needed — AirDriver picks up new entries on the next scan.

```jsonc
{
  "id": "rtl8812au",
  "name": "Realtek RTL8812AU",
  "monitor_mode": true,
  "injection": true,
  "injection_quality": "good",
  "usb_ids": ["0bda:8812", "2357:0103"],
  "kernel_native": {"module": "rtw88_8812au", "min_kernel": "6.14"},
  "drivers": [
    {"method": "apt", "package": "realtek-rtl88xxau-dkms", "priority": 1},
    {"method": "dkms_git", "repo": "https://github.com/morrownr/8812au-20210820", "priority": 2}
  ]
}
```

Then:

```bash
python -m airdriver db --check            # must pass
python -m unittest discover -s tests      # must pass
```

### The three rules for IDs

1. **Never invent an ID.** A wrong `vid:pid` makes AirDriver install the wrong driver on
   someone else's machine. Take it from one of:
   - the kernel's own device table (e.g. `drivers/net/wireless/.../rtl8xxxu/core.c`),
   - the out-of-tree driver's `supported-device-IDs` (morrownr, aircrack-ng, lwfinger),
   - hardware you physically own (include your `lsusb` output in the PR).
2. **Every ID is unique across the whole file.** Two chipsets claiming one ID means
   lookups silently resolve to whichever loaded last. `db --check` enforces this.
3. **Be honest about capability.** `monitor_mode` and `injection` are what people rely on
   when buying a card. "Connects fine but can't inject" is a useful, respectable answer —
   overstating it wastes someone's money.

## Working on the code

Core and CLI are **pure standard library** (they must run on a stock Kali box with zero
pip installs). Only the GUI needs PySide6.

```bash
python -m unittest discover -s tests -v   # no dependencies needed
python -m airdriver db --check
QT_QPA_PLATFORM=offscreen python scripts/gen_screenshots.py   # after UI changes
```

CI runs the suite on Python **3.9–3.13** plus a headless GUI smoke test. 3.9 matters:
it's still shipped, and it has caught real breakage (f-string and `importlib.resources`
behaviour that works fine on 3.12+).

### GUI rules

- **No emoji, ever.** A minimal Kali install has no emoji font, so `🔧`/`📚`/`⬇` render as
  blank boxes and the app looks broken. Use [`airdriver/gui/icons.py`](airdriver/gui/icons.py),
  which draws its icons with QPainter. Add a new one there if you need it.
- Long operations go on a worker thread via `_start_worker` — never block the UI thread,
  and never reuse one `QThread` (that aborts the process).

### Shell that runs as root

The install/rebuild/sign plans generate shell that runs as root on someone's machine.
Keep every step idempotent, prefer the driver maintainer's own installer over hand-rolled
`dkms` calls, and add a test — `tests/test_manage.py` runs the real signing loop against
fake modules in a sandbox.

## Reporting a bug

`sudo airdriver diagnose` prints (and copies) everything needed: kernel, headers, Secure
Boot, rfkill, USB/PCI list, interfaces, modules, DKMS state and the `dmesg` tail. Paste it
into the issue.

## Scope

AirDriver installs and manages drivers for **authorized** wireless security testing.
Contributions that add attack tooling, or that target networks rather than hardware, are
out of scope.

## License

By contributing you agree your work is released under the [MIT License](LICENSE).
