"""GUI bootstrap: repair the display environment, create the QApplication,
apply the theme, and show the window.

The single most common reason "it installed but won't run" is launching a Qt GUI
under ``sudo`` — sudo strips ``$DISPLAY`` / ``$XAUTHORITY`` so Qt's xcb plugin
can't reach the X server. We repair that here so both ``airdriver`` (as your
user) and ``sudo airdriver`` open the window, and we fail with a *useful*
message on headless boxes instead of a cryptic Qt abort.
"""

from __future__ import annotations

import os
import sys


# --------------------------------------------------------------------------- #
# Display environment repair                                                  #
# --------------------------------------------------------------------------- #
def _repair_display_env() -> str | None:
    """Make a usable X/Wayland session reachable, even when run via sudo.

    Returns ``None`` on success, or a human-readable error string explaining
    what to do (e.g. on a headless / SSH box with no display).
    """
    # When root via sudo, borrow the invoking user's graphical session.
    sudo_user = os.environ.get("SUDO_USER")
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    if is_root and sudo_user:
        home = None
        try:
            import pwd
            home = pwd.getpwnam(sudo_user).pw_dir
        except (KeyError, ImportError):
            home = os.path.expanduser(f"~{sudo_user}")

        os.environ.setdefault("DISPLAY", ":0")
        if "XAUTHORITY" not in os.environ and home:
            xauth = os.path.join(home, ".Xauthority")
            if os.path.exists(xauth):
                os.environ["XAUTHORITY"] = xauth
        # Let root connect to the user's X server (best-effort, harmless if absent).
        import shutil
        import subprocess
        if shutil.which("xhost"):
            try:
                subprocess.run(["xhost", "+SI:localuser:root"], timeout=4,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                pass

    # On Linux we need *some* display server to talk to.
    if sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return (
                "No graphical display found (DISPLAY / WAYLAND_DISPLAY are unset).\n"
                "  • On a headless box or over SSH, use the CLI instead:\n"
                "        airdriver scan      airdriver doctor      airdriver install\n"
                "  • At the desktop, open AirDriver from a terminal in that session."
            )
    return None


_XCB_HINT = (
    "The GUI could not start. If you saw a Qt 'xcb' / platform-plugin error above,\n"
    "the Qt runtime libraries are missing. Install them with:\n\n"
    "    sudo apt install -y libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 \\\n"
    "                        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \\\n"
    "                        libxcb-randr0 libxcb-render-util0 libxcb-shape0 libegl1\n\n"
    "Then try again — or just use the CLI, which needs none of this:\n"
    "    airdriver scan      airdriver doctor      airdriver install"
)


def run() -> int:
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
    except ImportError:
        print("PySide6 is required for the graphical app. Install it with:\n"
              "    pip install PySide6\n"
              "…or just use the CLI (no GUI deps needed):  airdriver scan")
        return 1

    err = _repair_display_env()
    if err and os.environ.get("AIRDRIVER_FORCE_GUI") != "1":
        print(err)
        return 1

    try:
        from .main_window import MainWindow
        from . import theme as T

        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName("AirDriver")
        app.setApplicationDisplayName("AirDriver")
        app.setStyleSheet(T.stylesheet())
        app.setFont(QFont("Inter", 10))

        win = MainWindow()
        win.show()
        return app.exec()
    except Exception as exc:  # noqa: BLE001 — turn cryptic Qt failures into guidance
        print(f"{exc}\n\n{_XCB_HINT}")
        return 1


if __name__ == "__main__":
    sys.exit(run())
