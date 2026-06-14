#!/usr/bin/env bash
# AirDriver bootstrap installer for Kali Linux / Parrot OS (and Debian/Ubuntu).
# Sets up a virtualenv, installs the GUI deps, and drops a launcher on PATH.
#
#   chmod +x install.sh && sudo ./install.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GREEN='\033[32m'; YELLOW='\033[33m'; CYAN='\033[36m'; RESET='\033[0m'
say() { echo -e "${CYAN}[airdriver]${RESET} $*"; }
ok()  { echo -e "${GREEN}[ ok ]${RESET} $*"; }
warn(){ echo -e "${YELLOW}[warn]${RESET} $*"; }

if [ "$(id -u)" -ne 0 ]; then
  warn "Not running as root. System packages won't be installed automatically."
  warn "Re-run with sudo for the full setup, or continue for a user-only install."
fi

# --- 1. system packages (best effort; needs root) --------------------------
if command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
  say "Installing system prerequisites…"
  apt-get update -qq || warn "apt update failed (offline?) — continuing."
  apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip \
      dkms build-essential bc libelf-dev git \
      "linux-headers-$(uname -r)" \
      pkg-config usbutils pciutils iw aircrack-ng \
    || warn "Some packages failed to install — install them manually if a build fails."
  ok "System prerequisites done."
else
  warn "Skipping apt step (no apt or not root)."
fi

# --- 2. python venv + GUI deps --------------------------------------------
say "Creating virtualenv at $HERE/.venv…"
python3 -m venv "$HERE/.venv"
# shellcheck disable=SC1091
source "$HERE/.venv/bin/activate"
pip install --upgrade pip >/dev/null
say "Installing AirDriver (with GUI extras)…"
pip install -e "$HERE[gui]" || pip install PySide6 && pip install -e "$HERE"
ok "Python deps installed."

# --- 3. launcher -----------------------------------------------------------
LAUNCHER="/usr/local/bin/airdriver"
if [ -w "$(dirname "$LAUNCHER")" ] || [ "$(id -u)" -eq 0 ]; then
  cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$HERE/.venv/bin/python" -m airdriver "\$@"
EOF
  chmod +x "$LAUNCHER"
  ok "Installed launcher: $LAUNCHER"
else
  warn "Could not write $LAUNCHER. Launch manually with:"
  warn "  $HERE/.venv/bin/python -m airdriver"
fi

echo
ok "AirDriver installed."
echo -e "  Launch the GUI:   ${GREEN}sudo airdriver${RESET}"
echo -e "  Or the CLI:       ${GREEN}sudo airdriver scan${RESET}"
echo -e "  Bundle drivers:   ${GREEN}./scripts/fetch_offline_drivers.sh${RESET}  (run while online)"
