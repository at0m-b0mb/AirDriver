"""Dark theme for the AirDriver GUI — a calm 'terminal-on-glass' look.

Colours are defined once here and referenced from the stylesheet so the whole
app can be re-skinned in one place.
"""

# Palette -------------------------------------------------------------------- #
BG = "#0d1117"          # window background
PANEL = "#161b22"       # cards / panels
PANEL_HI = "#1c2230"    # hovered / selected panel
BORDER = "#283042"
TEXT = "#e6edf3"
DIM = "#8b949e"
ACCENT = "#2ee6a6"      # primary (teal-green)
ACCENT_DK = "#1f9e72"
CYAN = "#38bdf8"
WARN = "#f5a623"
DANGER = "#ff6b6b"
GOOD = "#3fb950"

MONO = "Menlo, 'DejaVu Sans Mono', 'Cascadia Mono', Consolas, monospace"
SANS = "-apple-system, 'Segoe UI', 'Inter', 'Helvetica Neue', sans-serif"


def stylesheet() -> str:
    return f"""
    QWidget {{
        background: {BG};
        color: {TEXT};
        font-family: {SANS};
        font-size: 13px;
    }}
    QLabel#H1 {{ font-size: 22px; font-weight: 700; }}
    QLabel#H2 {{ font-size: 15px; font-weight: 600; }}
    QLabel#Dim {{ color: {DIM}; }}
    QLabel#Pill {{
        background: {PANEL_HI}; color: {DIM};
        border: 1px solid {BORDER}; border-radius: 9px;
        padding: 2px 8px; font-size: 11px;
    }}

    QFrame#Card {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px;
    }}
    QFrame#Card[selected="true"] {{
        background: {PANEL_HI}; border: 1px solid {ACCENT};
    }}
    QFrame#Header {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
    QFrame#StatusStrip {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
    }}

    QPushButton {{
        background: {PANEL_HI}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 8px;
        padding: 7px 14px; font-weight: 600;
    }}
    QPushButton:hover {{ border: 1px solid {ACCENT}; }}
    QPushButton:disabled {{ color: {DIM}; border: 1px solid {BORDER}; }}
    QPushButton#Primary {{
        background: {ACCENT}; color: #04130d; border: none;
    }}
    QPushButton#Primary:hover {{ background: {ACCENT_DK}; color: {TEXT}; }}
    QPushButton#Primary:disabled {{ background: {BORDER}; color: {DIM}; }}
    QPushButton#Ghost {{ background: transparent; }}

    QPlainTextEdit, QTextEdit {{
        background: #0a0e14; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 10px;
        font-family: {MONO}; font-size: 12px;
        padding: 8px;
    }}

    QScrollArea {{ border: none; }}
    QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {DIM}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

    QCheckBox {{ color: {TEXT}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid {BORDER}; background: {BG};
    }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}

    QComboBox {{
        background: {PANEL_HI}; border: 1px solid {BORDER};
        border-radius: 8px; padding: 6px 10px;
    }}
    QComboBox QAbstractItemView {{
        background: {PANEL}; border: 1px solid {BORDER};
        selection-background-color: {ACCENT_DK};
    }}
    QToolTip {{
        background: {PANEL}; color: {TEXT}; border: 1px solid {ACCENT};
        padding: 4px 8px; border-radius: 6px;
    }}
    """
