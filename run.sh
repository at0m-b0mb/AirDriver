#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  AirDriver quick-run — no install, no root needed.
#
#  Sets up a local virtualenv on first run, then launches AirDriver.
#
#    ./run.sh              # open the GUI
#    ./run.sh scan         # any CLI command works too
#    ./run.sh doctor
#
#  Tip: run this WITHOUT sudo. The GUI opens as your user (so X works) and only
#  the actual driver-install steps ask for your sudo password. For a system-wide
#  command and root-smooth installs, use ./install.sh instead.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"
PYBIN="$VENV/bin/python"

green() { printf '\033[32m%s\033[0m\n' "$1"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$1"; }

if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
  yellow "Heads up: running under sudo. For the GUI it's usually nicer to run"
  yellow "  ./run.sh   (without sudo) — it'll ask for a password only when installing."
fi

# First run: create the venv and install deps (GUI if possible).
if [ ! -x "$PYBIN" ]; then
  green "First run — setting up a local environment (.venv)…"
  python3 -m venv "$VENV"
  "$PYBIN" -m pip install --quiet --upgrade pip wheel || true
  if ! "$PYBIN" -m pip install --quiet -e "$HERE[gui]"; then
    yellow "Could not install the GUI (PySide6). Falling back to CLI-only."
    "$PYBIN" -m pip install --quiet -e "$HERE"
  fi
fi

exec "$PYBIN" -m airdriver "$@"
