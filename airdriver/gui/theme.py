"""Dark theme for the AirDriver GUI — a calm 'terminal-on-glass' look.

Colours are defined once here and referenced from the stylesheet so the whole
app can be re-skinned in one place.
"""

# Palette -------------------------------------------------------------------- #
BG = "#0b0f16"          # window background (a touch deeper for contrast)
BG_LOG = "#070a10"      # console / log surface
PANEL = "#151b24"       # cards / panels
PANEL_HI = "#1c2331"    # hovered / selected panel
PANEL_HOVER = "#222b3b"  # button hover
BORDER = "#283042"
BORDER_HI = "#37425a"   # brighter divider / hover border
TEXT = "#e6edf3"
DIM = "#8b949e"
ACCENT = "#2ee6a6"      # primary (teal-green)
ACCENT_DK = "#1f9e72"
ACCENT_SOFT = "rgba(46, 230, 166, 0.12)"   # translucent accent wash
CYAN = "#38bdf8"
WARN = "#f5a623"
DANGER = "#ff6b6b"
DANGER_SOFT = "rgba(255, 107, 107, 0.12)"
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
        selection-background-color: {ACCENT_DK};
        selection-color: {TEXT};
    }}

    /* The universal rule above is what gives the window its background, but it
       also paints {BG} behind every *child* widget — so each label sitting on a
       lighter card was drawing its own dark rectangle, and the cards looked like
       they were full of mismatched boxes. Labels/checkboxes never want their own
       fill; they should show whatever panel they happen to sit on. */
    QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}

    /* ---- typography & label roles ------------------------------------ */
    QLabel#H1 {{ font-size: 22px; font-weight: 800; }}
    QLabel#H2 {{ font-size: 15px; font-weight: 600; }}
    QLabel#Dim {{ color: {DIM}; }}
    QLabel#Link {{ color: {CYAN}; }}
    QLabel#Tag {{ color: {ACCENT}; font-weight: 600; }}
    QLabel#Good {{ color: {GOOD}; font-weight: 600; }}
    QLabel#Warn {{ color: {WARN}; font-weight: 600; }}
    QLabel#Danger {{ color: {DANGER}; font-weight: 600; }}

    /* ---- spec grid ---------------------------------------------------- */
    QFrame#Spec {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 11px;
    }}
    QLabel#SpecKey {{
        color: {DIM}; font-size: 11px; font-weight: 700;
        letter-spacing: 0.6px; text-transform: uppercase;
    }}

    /* The "this is the one to use" flag on the top adapter card. */
    QLabel#Flag {{
        background: {ACCENT_SOFT}; color: {ACCENT};
        border: 1px solid {ACCENT}; border-radius: 8px;
        padding: 1px 7px; font-size: 9px; font-weight: 800; letter-spacing: 1px;
    }}

    QLabel#Pill {{
        background: {PANEL_HI}; color: {DIM};
        border: 1px solid {BORDER}; border-radius: 10px;
        padding: 3px 10px; font-size: 11px; font-weight: 600;
    }}

    /* ---- cards & panels ---------------------------------------------- */
    QFrame#Card {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 13px;
    }}
    QFrame#Card:hover {{ border: 1px solid {BORDER_HI}; background: {PANEL_HI}; }}
    QFrame#Card[selected="true"] {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {PANEL_HI}, stop:1 {PANEL});
        border: 1px solid {ACCENT};
    }}

    QFrame#Header {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {PANEL_HI}, stop:0.6 {PANEL}, stop:1 {BG});
        border-bottom: 1px solid {BORDER};
    }}
    QFrame#StatusStrip {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {PANEL_HI}, stop:1 {PANEL});
        border: 1px solid {BORDER}; border-radius: 11px;
    }}
    QFrame#Footer {{ background: {BG}; border-top: 1px solid {BORDER}; }}

    /* ---- verdict strip ----------------------------------------------- */
    /* One line at the top of the detail pane answering "is this adapter
       ready?". The left edge carries the colour, so the answer is legible
       from across the room without reading the words. */
    QFrame#Verdict {{
        background: {PANEL}; border: 1px solid {BORDER};
        border-left: 3px solid {BORDER_HI}; border-radius: 11px;
    }}
    QFrame#Verdict[tone="good"] {{
        border-left: 3px solid {GOOD};
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(63, 185, 80, 0.14), stop:0.5 {PANEL}, stop:1 {PANEL});
    }}
    QFrame#Verdict[tone="warn"] {{
        border-left: 3px solid {WARN};
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(245, 166, 35, 0.14), stop:0.5 {PANEL}, stop:1 {PANEL});
    }}
    QFrame#Verdict[tone="bad"] {{
        border-left: 3px solid {DANGER};
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {DANGER_SOFT}, stop:0.5 {PANEL}, stop:1 {PANEL});
    }}
    QFrame#Verdict[tone="busy"] {{
        border-left: 3px solid {CYAN};
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(56, 189, 248, 0.14), stop:0.5 {PANEL}, stop:1 {PANEL});
    }}

    /* ---- progress ---------------------------------------------------- */
    QProgressBar#Progress {{
        background: {BG_LOG}; border: 1px solid {BORDER}; border-radius: 3px;
    }}
    QProgressBar#Progress::chunk {{
        border-radius: 3px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_DK}, stop:1 {ACCENT});
    }}

    /* ---- buttons ----------------------------------------------------- */
    QPushButton {{
        background: {PANEL_HI}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 9px;
        padding: 7px 14px; font-weight: 600;
    }}
    QPushButton:hover {{ background: {PANEL_HOVER}; border: 1px solid {ACCENT}; }}
    QPushButton:pressed {{ background: {PANEL}; }}
    QPushButton:disabled {{ background: {PANEL}; color: {DIM}; border: 1px solid {BORDER}; }}

    QPushButton#Primary {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {ACCENT}, stop:1 {ACCENT_DK});
        color: #04130d; border: none; border-radius: 9px;
        padding: 8px 18px; font-weight: 700;
    }}
    QPushButton#Primary:hover {{ background: {ACCENT}; }}
    QPushButton#Primary:pressed {{ background: {ACCENT_DK}; }}
    QPushButton#Primary:disabled {{ background: {BORDER}; color: {DIM}; }}

    QPushButton#Ghost {{
        background: transparent; color: {DIM}; border: 1px solid {BORDER};
    }}
    QPushButton#Ghost:hover {{
        background: {DANGER_SOFT}; color: {DANGER}; border: 1px solid {DANGER};
    }}

    /* ---- console / log ----------------------------------------------- */
    QPlainTextEdit, QTextEdit {{
        background: {BG_LOG}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 11px;
        font-family: {MONO}; font-size: 12px;
        padding: 10px; selection-background-color: {ACCENT_DK};
    }}
    QTextBrowser {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 11px; padding: 10px;
    }}

    /* ---- scrollbars -------------------------------------------------- */
    QScrollArea {{ border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 32px; }}
    QScrollBar::handle:vertical:hover {{ background: {BORDER_HI}; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 32px; }}
    QScrollBar::handle:horizontal:hover {{ background: {BORDER_HI}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ---- inputs ------------------------------------------------------ */
    QCheckBox {{ color: {TEXT}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 17px; height: 17px; border-radius: 5px;
        border: 1px solid {BORDER_HI}; background: {BG};
    }}
    QCheckBox::indicator:hover {{ border: 1px solid {ACCENT}; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}

    QComboBox {{
        background: {PANEL_HI}; border: 1px solid {BORDER};
        border-radius: 8px; padding: 6px 12px;
    }}
    QComboBox:hover {{ border: 1px solid {ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
        selection-background-color: {ACCENT_DK}; outline: none; padding: 4px;
    }}

    QToolTip {{
        background: {PANEL}; color: {TEXT}; border: 1px solid {ACCENT};
        padding: 5px 9px; border-radius: 7px;
    }}
    """
