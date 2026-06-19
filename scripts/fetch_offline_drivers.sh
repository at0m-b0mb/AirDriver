#!/usr/bin/env bash
# Populate the offline driver bundle. Run this ONCE while you have internet;
# afterwards AirDriver can build these drivers on an air-gapped machine.
#
#   ./scripts/fetch_offline_drivers.sh
#
# Each repo path here matches a "method": "offline" entry in data/chipsets.json.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HERE/airdriver/data/drivers"
mkdir -p "$DEST"

# chipset            git repo                                        target dir
REPOS=(
  "rtl8812au|https://github.com/morrownr/8812au-20210820|8812au-20210820"
  "rtl8821au|https://github.com/morrownr/8821au-20210708|8821au-20210708"
  "rtl8814au|https://github.com/morrownr/8814au|8814au"
  "rtl8821cu|https://github.com/morrownr/8821cu-20210916|8821cu-20210916"
  "rtl8822bu|https://github.com/morrownr/88x2bu-20210702|88x2bu-20210702"
  "rtl8188eus|https://github.com/aircrack-ng/rtl8188eus|rtl8188eus"
  "rtl8188fu|https://github.com/kelebek333/rtl8188fu|rtl8188fu"
  "rtl8192eu|https://github.com/clnhub/rtl8192eu-linux|rtl8192eu-linux"
  "rtl8192cu|https://github.com/pvaret/rtl8192cu-fixes|rtl8192cu-fixes"
  "rtl8723bu|https://github.com/lwfinger/rtl8723bu|rtl8723bu"
  "rtl8821ce|https://github.com/tomaspinho/rtl8821ce|rtl8821ce"
  "rtl8852bu|https://github.com/morrownr/rtl8852bu-20250826|rtl8852bu-20250826"
  "rtl8852cu|https://github.com/morrownr/rtl8852cu-20251113|rtl8852cu-20251113"
)

echo "Fetching offline driver sources into $DEST"
for entry in "${REPOS[@]}"; do
  IFS='|' read -r chip url dir <<< "$entry"
  target="$DEST/$dir"
  if [ -d "$target/.git" ]; then
    echo "  ↻ $chip — updating $dir"
    git -C "$target" pull --ff-only --depth=1 || echo "    (update failed, keeping existing copy)"
  else
    echo "  ⬇ $chip — cloning $dir"
    git clone --depth=1 "$url" "$target" || echo "    (clone failed: $url)"
  fi
done

echo
echo "Done. Offline bundle is ready under: $DEST"
echo "AirDriver will now offer the 'offline' install path when there is no internet."
