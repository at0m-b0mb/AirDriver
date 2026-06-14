# Offline driver bundle

This folder holds **driver source trees** so AirDriver can build out-of-tree
DKMS drivers on a machine with **no internet** — the classic
"no WiFi driver → no internet → can't download the driver" catch-22.

It starts empty. Populate it once, while online:

```bash
./scripts/fetch_offline_drivers.sh
```

That clones each driver repo into a subfolder here (e.g. `8812au-20210820/`).
The folder names match the `"method": "offline"` → `"path"` entries in
[`../chipsets.json`](../chipsets.json).

When AirDriver runs and finds **no internet**, it falls back to building from
these local copies instead of `git clone`-ing. The contents are git-ignored
(they're large and upstream-owned); commit them yourself only if you want a
fully self-contained, checked-in offline bundle.
