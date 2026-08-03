#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  AirDriver uninstaller
#
#  Removes AirDriver itself. By default it leaves the Wi-Fi drivers it installed
#  in place, because those are what make your adapter work — pass --drivers to
#  clear those too and return the machine to its in-kernel drivers.
#
#  Usage:
#    sudo ./uninstall.sh              # remove AirDriver, keep the Wi-Fi drivers
#    sudo ./uninstall.sh --drivers    # …and remove every driver it installed
#    sudo ./uninstall.sh --all        # …and the Secure Boot signing key too
#    sudo ./uninstall.sh --yes        # don't ask
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"
BLACKLIST="/etc/modprobe.d/airdriver-blacklist.conf"
MOK_DIR="/var/lib/airdriver"

if [ -t 1 ]; then
  BOLD='\033[1m'; GREEN='\033[32m'; YELLOW='\033[33m'; CYAN='\033[36m'; RED='\033[31m'; RESET='\033[0m'
else
  BOLD=''; GREEN=''; YELLOW=''; CYAN=''; RED=''; RESET=''
fi
say()  { echo -e "${CYAN}${BOLD}▸${RESET} $*"; }
ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
warn() { echo -e "  ${YELLOW}!${RESET} $*"; }
err()  { echo -e "  ${RED}✗${RESET} $*"; }

REMOVE_DRIVERS=0
REMOVE_KEYS=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --drivers)  REMOVE_DRIVERS=1 ;;
    --all)      REMOVE_DRIVERS=1; REMOVE_KEYS=1 ;;
    --yes|-y)   ASSUME_YES=1 ;;
    -h|--help)  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) err "Unknown option: $arg"; exit 1 ;;
  esac
done

echo
echo -e "${BOLD}${CYAN}  AirDriver uninstaller${RESET}"
echo

confirm() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  read -r -p "$(echo -e "  ${BOLD}$1${RESET} [y/N] ")" ans
  case "$ans" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

# --- 1. optionally remove the Wi-Fi drivers AirDriver installed -------------
# Do this FIRST, while the airdriver command still exists.
if [ "$REMOVE_DRIVERS" -eq 1 ]; then
  say "Removing the Wi-Fi drivers AirDriver installed…"
  AIRDRIVER_BIN=""
  for cand in "$VENV/bin/python" "$(command -v airdriver 2>/dev/null || true)"; do
    [ -n "$cand" ] && [ -x "$cand" ] && { AIRDRIVER_BIN="$cand"; break; }
  done
  if [ -z "$AIRDRIVER_BIN" ]; then
    warn "Couldn't find AirDriver to run the driver cleanup — skipping."
    warn "Remove them manually with:  sudo dkms status   then  sudo dkms remove <name> --all"
  elif [ "$AIRDRIVER_BIN" = "$VENV/bin/python" ]; then
    "$AIRDRIVER_BIN" -m airdriver remove --all --yes || warn "Driver cleanup reported problems."
  else
    "$AIRDRIVER_BIN" remove --all --yes || warn "Driver cleanup reported problems."
  fi
  ok "Driver cleanup finished."
else
  say "Leaving installed Wi-Fi drivers in place."
  echo -e "     ${YELLOW}(re-run with --drivers to remove them as well)${RESET}"
fi

# --- 2. the launcher on PATH ------------------------------------------------
say "Removing the 'airdriver' launcher…"
for p in /usr/local/bin/airdriver "$HOME/.local/bin/airdriver" \
         "/home/${SUDO_USER:-$USER}/.local/bin/airdriver"; do
  if [ -e "$p" ]; then
    rm -f "$p" && ok "removed $p"
  fi
done

# --- 3. the virtualenv ------------------------------------------------------
if [ -d "$VENV" ]; then
  say "Removing the virtualenv…"
  rm -rf "$VENV" && ok "removed $VENV"
fi

# --- 4. the modprobe blacklist ---------------------------------------------
# Important: this must go, or the in-kernel drivers stay banned and the adapter
# is left with no driver at all.
if [ -f "$BLACKLIST" ]; then
  say "Removing AirDriver's modprobe blacklist…"
  rm -f "$BLACKLIST" && ok "removed $BLACKLIST"
  command -v depmod >/dev/null 2>&1 && depmod -a 2>/dev/null || true
fi

# --- 5. the Secure Boot signing key ----------------------------------------
if [ -d "$MOK_DIR" ]; then
  if [ "$REMOVE_KEYS" -eq 1 ]; then
    say "Removing the Secure Boot signing key…"
    rm -rf "$MOK_DIR" && ok "removed $MOK_DIR"
    warn "The key may still be enrolled in your firmware. Remove it with:"
    warn "    sudo mokutil --delete /var/lib/airdriver/MOK.der"
  else
    warn "Keeping the Secure Boot signing key in $MOK_DIR (use --all to delete it)."
  fi
fi

# --- 6. a clone made by the curl one-liner ---------------------------------
if [ "$HERE" = "/opt/airdriver" ] && [ -d "$HERE/.git" ]; then
  if confirm "Also delete the AirDriver source at $HERE?"; then
    cd /
    rm -rf "$HERE" && ok "removed $HERE"
  fi
fi

echo
echo -e "${GREEN}${BOLD}  AirDriver has been removed.${RESET}"
if [ "$REMOVE_DRIVERS" -eq 1 ]; then
  echo -e "  Your adapters will fall back to their in-kernel drivers — re-plug them, or reboot."
else
  echo -e "  The Wi-Fi drivers it installed are still there and still working."
fi
echo
