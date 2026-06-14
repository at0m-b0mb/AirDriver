"""GUI bootstrap: create the QApplication, apply the theme, show the window."""

from __future__ import annotations

import sys


def run() -> int:
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
    except ImportError:
        print("PySide6 is required for the GUI. Install it with:  pip install PySide6")
        return 1

    from .main_window import MainWindow
    from . import theme as T

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AirDriver")
    app.setStyleSheet(T.stylesheet())
    app.setFont(QFont("Inter", 10))

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
