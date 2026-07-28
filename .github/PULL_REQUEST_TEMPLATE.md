<!-- Thanks for contributing to AirDriver. -->

## What this changes

<!-- One or two sentences. -->

## Checklist

- [ ] `python -m airdriver db --check` passes (no duplicate or malformed IDs)
- [ ] `python -m unittest discover -s tests` passes
- [ ] If I touched the GUI: no emoji in any label — use `airdriver/gui/icons.py`
      (a minimal Kali install has no emoji font and they render as blank boxes)

### Adding a chipset or USB ID?

- [ ] The ID came from a **real source** — the kernel's device table, the driver
      maintainer's `supported-device-IDs`, or hardware I physically own
- [ ] `monitor_mode` / `injection` / `injection_quality` are honest for this chip
      (connect-only is fine — say so rather than overstating it)
- [ ] Where the ID came from is noted below

**Source of the ID(s):**

<!-- e.g. "drivers/net/wireless/realtek/rtl8xxxu/core.c" or
     "morrownr/8812au-20210820 supported-device-IDs" or
     "I own this adapter; lsusb output below" -->
