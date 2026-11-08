"""Design tokens and Qt style sheets for the whole UI.

Every constant that existed before keeps its name, so the other modules do not change.
Widget-specific sheets use object-name selectors where a plain QSS rule would cascade
into child widgets. Qt has no box-shadow or CSS variables, so tokens are substituted
into the sheets below with string.Template."""

from string import Template

# ----------------------------------------------------------------- tokens
BG = "#F8FAFC"
SURFACE = "#FFFFFF"
BORDER = "#E5E7EB"
BORDER_STRONG = "#D1D5DB"
TEXT = "#111827"
TEXT_2 = "#6B7280"
TEXT_3 = "#4B5563"
PRIMARY = "#1E8CFA"
PRIMARY_HOVER = "#1478DC"
PRIMARY_PRESSED = "#0F63B8"
PRIMARY_50 = "#F2F8FF"
PRIMARY_100 = "#DCEEFF"
PRIMARY_200 = "#BADCFE"
SUCCESS = "#047A68"
SUCCESS_BG = "#E6FAF6"
SUCCESS_DOT = "#04C8A7"
WARNING = "#B45309"
WARNING_BG = "#FFFBEB"
WARNING_DOT = "#F59E0B"
DANGER = "#B91C1C"
DANGER_BG = "#FEF2F2"
DANGER_DOT = "#EF4444"
NEUTRAL_BG = "#F3F4F6"
VIEWER_BG = "#EEF1F5"

FONT_STACK = '"Inter", "Segoe UI", "Roboto", "Helvetica Neue", "Noto Sans", "Ubuntu", sans-serif'

_T = {
    "bg": BG, "surface": SURFACE, "border": BORDER, "border_strong": BORDER_STRONG,
    "text": TEXT, "text2": TEXT_2, "text3": TEXT_3,
    "primary": PRIMARY, "primary_hover": PRIMARY_HOVER, "primary_pressed": PRIMARY_PRESSED,
    "primary50": PRIMARY_50, "primary100": PRIMARY_100, "primary200": PRIMARY_200,
    "success": SUCCESS, "success_bg": SUCCESS_BG, "success_dot": SUCCESS_DOT,
    "warning": WARNING, "warning_bg": WARNING_BG, "warning_dot": WARNING_DOT,
    "danger": DANGER, "danger_bg": DANGER_BG, "danger_dot": DANGER_DOT,
    "neutral_bg": NEUTRAL_BG, "viewer_bg": VIEWER_BG, "font": FONT_STACK,
}


def _q(sheet):
    return Template(sheet).substitute(_T)


# ------------------------------------------------------- application-wide
APP_STYLE = _q("""
    QWidget { font-family: $font; }
    QToolTip {
        background-color: $text; color: white; border: none;
        padding: 6px 8px; border-radius: 6px; font-size: 13px;
    }
    QMenu {
        background-color: $surface; border: 1px solid $border; border-radius: 10px; padding: 4px;
    }
    QMenu::item { padding: 8px 14px; border-radius: 6px; color: $text; font-size: 14px; }
    QMenu::item:selected { background-color: $neutral_bg; color: $text; }
    QMenu::separator { height: 1px; background: $border; margin: 4px 6px; }

    QMessageBox, QInputDialog { background-color: $surface; }
    QMessageBox QLabel, QInputDialog QLabel { color: $text; font-size: 14px; }

    QPushButton {
        background-color: $surface; color: $text; border: 1px solid $border;
        border-radius: 8px; padding: 9px 18px; font-size: 14px; font-weight: 500;
    }
    QPushButton:hover { background-color: #F9FAFB; border-color: $border_strong; }
    QPushButton:pressed { background-color: $neutral_bg; }
    QPushButton:focus { border: 1px solid $primary; }
    QPushButton:disabled { color: #9CA3AF; background-color: #F9FAFB; border-color: $border; }

    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {
        background-color: $surface; color: $text; border: 1px solid $border;
        border-radius: 8px; padding: 9px 12px; font-size: 14px;
        selection-background-color: $primary200; selection-color: $text;
    }
    QLineEdit:hover, QComboBox:hover { border-color: $border_strong; }
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid $primary; }
    QLineEdit:disabled, QComboBox:disabled { background-color: #F9FAFB; color: #9CA3AF; }
    QComboBox::drop-down { border: none; width: 24px; }
    QComboBox QAbstractItemView {
        background-color: $surface; border: 1px solid $border; border-radius: 8px;
        selection-background-color: $primary50; selection-color: $text; outline: none; padding: 4px;
    }

    QGroupBox {
        border: 1px solid $border; border-radius: 10px; margin-top: 14px; padding: 14px 12px 10px 12px;
        font-size: 14px; font-weight: 600; color: $text;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: $text3; }

    QScrollBar:vertical { border: none; background: transparent; width: 10px; margin: 0; }
    QScrollBar::handle:vertical { background: $border_strong; min-height: 30px; border-radius: 5px; }
    QScrollBar::handle:vertical:hover { background: #9CA3AF; }
    QScrollBar:horizontal { border: none; background: transparent; height: 10px; margin: 0; }
    QScrollBar::handle:horizontal { background: $border_strong; min-width: 30px; border-radius: 5px; }
    QScrollBar::handle:horizontal:hover { background: #9CA3AF; }
    QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
    QScrollBar::add-page, QScrollBar::sub-page { background: none; }
""")


def _load_bundled_fonts():
    """Register Inter if its .ttf files are shipped in ui/assets/fonts (optional; falls back otherwise)."""
    try:
        import os
        from PySide6.QtGui import QFontDatabase
        from common.path import resource_path

        folder = resource_path(os.path.join("ui", "assets", "fonts"))
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith((".ttf", ".otf")):
                    QFontDatabase.addApplicationFont(os.path.join(folder, name))
    except Exception:
        pass


def _light_palette():
    """Fixed light colours for everything the stylesheet does not colour itself (dialog backgrounds, plain
    labels, check boxes, ...), so a dark system theme cannot turn parts of the UI dark."""
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    colors = {
        QPalette.Window: SURFACE, QPalette.WindowText: TEXT,
        QPalette.Base: SURFACE, QPalette.AlternateBase: BG,
        QPalette.Text: TEXT, QPalette.Button: SURFACE, QPalette.ButtonText: TEXT,
        QPalette.BrightText: "#FFFFFF", QPalette.PlaceholderText: "#9CA3AF",
        QPalette.ToolTipBase: TEXT, QPalette.ToolTipText: "#FFFFFF",
        QPalette.Highlight: PRIMARY, QPalette.HighlightedText: "#FFFFFF",
        QPalette.Link: PRIMARY_PRESSED, QPalette.LinkVisited: PRIMARY_PRESSED,
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#9CA3AF"))
    return palette


def apply_global_style(app):
    """Call once after creating QApplication (before showing any window)."""
    app.setStyle("Fusion")
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):          # Qt 6.8+: do not follow the system dark/light setting
        from PySide6.QtCore import Qt
        hints.setColorScheme(Qt.ColorScheme.Light)
    app.setPalette(_light_palette())
    _load_bundled_fonts()
    app.setStyleSheet(APP_STYLE)


# --------------------------------------------------------------- surfaces
MAIN_BG = f"background-color: {SURFACE};"
START_PAGE_BG = f"QWidget#StartPage {{ background-color: {BG}; }}"
TOOLBAR_STYLE = _q("""
    QWidget#Toolbar { background-color: $surface; border: none; border-bottom: 1px solid $border; }
""")
RIGHT_PANEL_STYLE = _q("""
    QWidget#RightPanel { background-color: $surface; border: none; border-left: 1px solid $border; }
""")
DIALOG_STYLE = _q("""
    QDialog#AnalysisDialog { background-color: $surface; border: 1px solid $border_strong; }
""")
HEADER_FRAME_STYLE = _q("""
    QFrame#AppBar { background-color: $surface; border: none; border-bottom: 1px solid $border; }
""")
OVERLAY_STYLE = "background-color: rgba(15, 23, 42, 140);"

# ------------------------------------------------------------- typography
HEADER_TEXT = f"font-size: 30px; font-weight: 600; color: {TEXT}; border: none;"
HEADER_TITLE_STYLE = HEADER_TEXT + " background: transparent;"
SECTION_TITLE = f"font-size: 18px; font-weight: 600; color: {TEXT}; border: none;"
SECTION_TITLE_STYLE = SECTION_TITLE + " background: transparent;"
SECTION_TITLE_DARK = f"font-size: 14px; font-weight: 600; color: {TEXT_3}; background: transparent; border: none;"
NORMAL_LABEL_STYLE = f"font-size: 17px; font-weight: 600; color: {TEXT}; background: transparent; border: none;"
VERIFY_TITLE_STYLE = f"font-size: 18px; font-weight: 600; color: {TEXT}; background: transparent; border: none;"
SEPARATOR_STYLE = f"color: {BORDER_STRONG}; background: transparent; border: none;"
LANG_BTN_STYLE = "background: transparent; border: none;"
SUBTITLE_STYLE = f"font-size: 15px; color: {TEXT_2}; background: transparent; border: none;"
FIELD_LABEL_STYLE = f"font-size: 14px; font-weight: 500; color: {TEXT_3}; background: transparent; border: none;"
HINT_STYLE = f"font-size: 13px; color: {TEXT_2}; background: transparent; border: none;"
MUTED_LABEL_STYLE = f"font-size: 14px; color: {TEXT_2}; background: transparent; border: none;"
DRAG_TEXT_STYLE = f"font-size: 16px; font-weight: 500; color: {TEXT}; border: none; background: transparent;"
OR_LABEL_STYLE = f"font-size: 14px; color: {TEXT_2}; border: none; background: transparent;"

# ---------------------------------------------------------------- buttons
BLUE_BUTTON_STYLE = _q("""
    QPushButton {
        background-color: $primary; color: white; border: none; border-radius: 8px;
        padding: 11px 22px; font-weight: 600; font-size: 14px;
    }
    QPushButton:hover { background-color: $primary_hover; }
    QPushButton:pressed { background-color: $primary_pressed; }
    QPushButton:disabled { background-color: $border; color: #9CA3AF; }
""")

RED_BUTTON_STYLE = _q("""
    QPushButton {
        background-color: $danger; color: white; border: none; border-radius: 8px;
        padding: 9px 16px; font-weight: 500; font-size: 14px;
    }
    QPushButton:hover { background-color: #991B1B; }
    QPushButton:disabled { background-color: $border; color: #9CA3AF; }
""")

GRAY_BUTTON_STYLE = _q("""
    QPushButton {
        background-color: $surface; color: $text; border: 1px solid $border; border-radius: 8px;
        padding: 10px 20px; font-weight: 500; font-size: 14px;
    }
    QPushButton:hover { background-color: #F9FAFB; border-color: $border_strong; }
    QPushButton:pressed { background-color: $neutral_bg; }
    QPushButton:disabled { color: #9CA3AF; background-color: #F9FAFB; }
""")

SORT_BTN_STYLE = _q("""
    QPushButton {
        background-color: $surface; color: $text3; border: 1px solid $border; border-radius: 8px;
        padding: 10px 14px; font-size: 14px; font-weight: 500; text-align: left;
    }
    QPushButton:hover { background-color: #F9FAFB; border-color: $border_strong; }
""")

DELETE_BTN_STYLE = _q("""
    QPushButton {
        color: $danger; font-weight: 500; border: none; background: transparent;
        font-size: 14px; padding: 6px 10px; border-radius: 6px;
    }
    QPushButton:hover { background-color: $danger_bg; }
""")

ANALIZA_BTN_STYLE = _q("""
    QPushButton {
        background-color: $primary; color: white; border: none; border-radius: 8px;
        padding: 0 24px; font-weight: 600; font-size: 15px;
    }
    QPushButton:hover { background-color: $primary_hover; }
    QPushButton:pressed { background-color: $primary_pressed; }
    QPushButton:disabled { background-color: $border; color: #9CA3AF; }
""")

RAPORT_BTN_STYLE = _q("""
    QPushButton {
        background-color: $primary; color: white; border: none; border-radius: 8px;
        padding: 14px 18px; font-weight: 600; font-size: 15px;
    }
    QPushButton:hover { background-color: $primary_hover; }
    QPushButton:pressed { background-color: $primary_pressed; }
""")

ICON_BUTTON_STYLE = _q("""
    QPushButton { border: none; background: transparent; border-radius: 8px; padding: 0; }
    QPushButton:hover { background-color: $neutral_bg; }
    QPushButton:pressed { background-color: $border; }
    QPushButton:disabled { background: transparent; }
""")
TRASH_BUTTON_STYLE = _q("""
    QPushButton { border: none; background: transparent; border-radius: 8px; padding: 0; }
    QPushButton:hover { background-color: $danger_bg; }
    QPushButton:pressed { background-color: #FEE2E2; }
""")
REPORT_BUTTON_STYLE = _q("""
    QPushButton {
        background-color: $warning_bg; color: $warning; border: 1px solid #FCD34D;
        border-radius: 8px; padding: 10px 18px; font-weight: 600; font-size: 14px;
    }
    QPushButton:hover { background-color: #FEF3C7; border-color: $warning_dot; }
    QPushButton:pressed { background-color: #FDE68A; }
    QPushButton:disabled { color: #9CA3AF; background-color: #F9FAFB; border-color: $border; }
""")
BACK_BTN_STYLE = ICON_BUTTON_STYLE

LINK_BUTTON_STYLE = _q("""
    QPushButton {
        border: none; background: transparent; color: $primary_hover; font-size: 15px;
        font-weight: 600; padding: 0; text-align: left;
    }
    QPushButton:hover { color: $primary_hover; text-decoration: underline; }
""")

MODE_BTN_STYLE = _q("""
    QPushButton {
        border: 1px solid transparent; border-radius: 8px; padding: 0 16px;
        background-color: transparent; font-size: 14px; font-weight: 500;
        color: $text2; text-align: center;
    }
    QPushButton:hover { color: $text; }
    QPushButton:checked {
        border: 1px solid $border; background-color: $surface; color: $text;
    }
    QPushButton:disabled { color: #B6BCC6; }
""")
SEGMENT_STYLE = _q("""
    QFrame#Segment { background-color: $neutral_bg; border: none; border-radius: 10px; }
""")

TABLE_ROW_NAME_BUTTON = _q("""
    QPushButton {
        text-align: left; font-weight: 500; font-size: 15px; color: $text;
        border: none; background: transparent; padding: 0;
    }
    QPushButton:hover { color: $primary; }
""")

# ----------------------------------------------------------------- fields
SEARCH_STYLE = _q("""
    QLineEdit {
        border: 1px solid $border; border-radius: 8px; padding: 9px 12px 9px 4px;
        color: $text; background-color: $surface; font-size: 14px;
    }
    QLineEdit:hover { border-color: $border_strong; }
    QLineEdit:focus { border: 1px solid $primary; }
""")
PAGE_INPUT_STYLE = _q("""
    QLineEdit {
        border: 1px solid $border; border-radius: 6px; padding: 3px 4px;
        color: $text; background-color: $surface; font-size: 14px; font-weight: 500;
    }
    QLineEdit:focus { border: 1px solid $primary; }
""")

CHECKBOX_STYLE = _q("""
    QCheckBox { color: $text3; font-size: 14px; spacing: 8px; background: transparent; }
    QCheckBox::indicator {
        width: 16px; height: 16px; border: 1px solid $border_strong; border-radius: 4px;
        background-color: $surface;
    }
    QCheckBox::indicator:hover { border-color: $primary; }
    QCheckBox::indicator:checked { background-color: $primary; border: 1px solid $primary; }
""")

PROGRESS_BAR_STYLE = _q("""
    QProgressBar { border: none; border-radius: 5px; background-color: $neutral_bg; max-height: 10px; min-height: 10px; }
    QProgressBar::chunk { border-radius: 4px; background-color: $primary; }
""")
PROGRESS_THIN_STYLE = _q("""
    QProgressBar { border: none; border-radius: 3px; background-color: $neutral_bg; max-height: 6px; min-height: 6px; }
    QProgressBar::chunk { border-radius: 3px; background-color: $primary; }
""")

# ------------------------------------------------------------ drop zones
UPLOAD_ZONE_STYLE = _q("""
    QFrame#DropZone {
        border: 2px dashed $primary; border-radius: 12px; background-color: $primary50;
    }
    QFrame#DropZone:hover, QFrame#DropZone[drag="true"] {
        border-color: $primary_hover; background-color: #E8F3FF;
    }
""")
JSON_FRAME_STYLE = UPLOAD_ZONE_STYLE

ICON_CIRCLE_STYLE = f"QLabel {{ background-color: {PRIMARY_100}; border: none; border-radius: 35px; }}"
PDF_ICON_LABEL_STYLE = ICON_CIRCLE_STYLE
JSON_ICON_CIRCLE = ICON_CIRCLE_STYLE
CHIP_STYLE = _q("""
    QLabel {
        background-color: $neutral_bg; color: $text3; border: none; border-radius: 10px;
        padding: 2px 10px; font-size: 13px; font-weight: 500;
    }
""")

FILE_BADGE_FRAME = _q("""
    QFrame#FileBadge { border: 1px solid $border; border-radius: 12px; background-color: $surface; }
""")
FILE_BADGE_INNER_LABELS = "border: none; background: transparent;"
FILE_BADGE_NAME_LABEL = f"font-weight: 500; font-size: 15px; color: {TEXT}; border: none; background: transparent;"
FILE_BADGE_INFO_LABEL = f"color: {TEXT_2}; font-size: 14px; border: none; background: transparent;"
FILE_TILE_STYLE = _q("""
    QLabel {
        background-color: $neutral_bg; border: 1px solid $border; border-radius: 6px;
        color: $text3; font-size: 11px; font-weight: 600;
    }
""")

# ------------------------------------------------------- documents list
DOCS_CARD_STYLE = _q("""
    QFrame#DocsCard { background-color: $surface; border: 1px solid $border; border-radius: 12px; }
""")
TABLE_CONTAINER = "border: none; background: transparent;"
TABLE_CONTAINER_STYLE = TABLE_CONTAINER
TABLE_HEADER_TEXT = f"color: {TEXT_2}; font-weight: 500; font-size: 13px; border: none; background: transparent;"
TABLE_HEADER_ROW_TEXT = TABLE_HEADER_TEXT
TABLE_HEADER_ROW_STYLE = _q("""
    QWidget#TableHeader {
        background-color: #F9FAFB; border: none;
        border-top: 1px solid $border; border-bottom: 1px solid $border;
    }
""")
TABLE_ROW_STYLE = _q("""
    QWidget#DocRow { background-color: transparent; border: none; border-bottom: 1px solid #F1F2F4; }
    QWidget#DocRow:hover { background-color: #FAFBFC; }
""")
TABLE_ROW_SUBTITLE = f"color: {TEXT_2}; font-size: 14px; border: none; background: transparent;"
TABLE_ROW_DATE = f"color: {TEXT_3}; border: none; background: transparent; font-size: 15px;"
EMPTY_TITLE_STYLE = f"color: {TEXT}; font-size: 17px; font-weight: 600; background: transparent; border: none;"
EMPTY_TEXT_STYLE = f"color: {TEXT_2}; font-size: 15px; background: transparent; border: none;"
START_PAGE_SCROLL_STYLE = _q("""
    QScrollArea { border: none; background: transparent; }
    QScrollArea > QWidget > QWidget { background: transparent; }
""")

# ---------------------------------------------------------------- badges
BADGE_FRAME_SUCCESS = f"QFrame {{ background-color: {SUCCESS_BG}; border-radius: 12px; border: none; }}"
BADGE_ICON_SUCCESS = f"QLabel {{ background-color: {SUCCESS_DOT}; border-radius: 8px; border: none; }}"
BADGE_FRAME_ERROR = f"QFrame {{ background-color: {WARNING_BG}; border-radius: 12px; border: none; }}"
BADGE_ICON_ERROR = f"QLabel {{ background-color: {WARNING_DOT}; border-radius: 8px; border: none; }}"
BADGE_FRAME_FAIL = f"QFrame {{ background-color: {DANGER_BG}; border-radius: 12px; border: none; }}"
BADGE_ICON_FAIL = f"QLabel {{ background-color: {DANGER_DOT}; border-radius: 8px; border: none; }}"

BADGE_TEXT_DEFAULT = f"color: {TEXT}; font-weight: 500; font-size: 13px; border: none; background: transparent;"
BADGE_TEXT_SUCCESS = f"color: {SUCCESS}; font-weight: 500; font-size: 13px; border: none; background: transparent;"
BADGE_TEXT_ERROR = f"color: {WARNING}; font-weight: 500; font-size: 13px; border: none; background: transparent;"
BADGE_TEXT_FAIL = f"color: {DANGER}; font-weight: 500; font-size: 13px; border: none; background: transparent;"

STATUS_BADGE_STYLE = _q("""
    QLabel {
        background-color: $success_bg; color: $success; border-radius: 10px;
        padding: 2px 10px; font-size: 13px; font-weight: 500; border: none;
    }
""")

# ---------------------------------------------------- reader: left column
THUMB_AREA_STYLE = _q("""
    QScrollArea { border: none; border-right: 1px solid $border; background-color: $surface; }
    QScrollArea > QWidget > QWidget { background-color: $surface; }
""")
THUMB_BUTTON_STYLE = _q("""
    QToolButton {
        border: 1px solid transparent; border-radius: 10px; background: transparent;
        padding: 8px 6px 6px 6px; color: $text2; font-size: 13px; font-weight: 500;
    }
    QToolButton:hover { background-color: #F8FAFF; border-color: $primary200; }
    QToolButton:checked { background-color: $primary50; border-color: $primary; color: $primary_pressed; }
""")

# ------------------------------------------------------ reader: viewer
PDF_VIEW_STYLE = _q("""
    QPdfView { background-color: $viewer_bg; border: none; }
    QScrollBar:vertical { border: none; background: transparent; width: 12px; margin: 0px; }
    QScrollBar::handle:vertical { background: #C4C9D2; min-height: 30px; border-radius: 6px; }
    QScrollBar::handle:vertical:hover { background: #9CA3AF; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
    QScrollBar:horizontal { border: none; background: transparent; height: 12px; margin: 0px; }
    QScrollBar::handle:horizontal { background: #C4C9D2; min-width: 30px; border-radius: 6px; }
    QScrollBar::handle:horizontal:hover { background: #9CA3AF; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
""")
VIEW_TOOLS_STYLE = _q("""
    QFrame#ViewTools { background-color: $surface; border: 1px solid $border; border-radius: 10px; }
""")
TOOLS_LABEL_STYLE = f"font-size: 14px; font-weight: 500; color: {TEXT}; background: transparent; border: none;"
TOOLS_MUTED_STYLE = f"font-size: 14px; color: {TEXT_2}; background: transparent; border: none;"
TOOLS_DIVIDER_STYLE = f"background-color: {BORDER}; border: none;"

ERROR_MARKER_STYLE = """
    QPushButton {
        background-color: rgba(220, 38, 38, 220); border: 2px solid white; border-radius: 8px;
        color: white; font-weight: bold; padding: 0px;
    }
    QPushButton:hover { background-color: #B91C1C; }
"""
COMMENT_MARKER_STYLE = """
    QPushButton {
        background-color: rgba(37, 99, 235, 220); border: 2px solid white; border-radius: 8px;
        color: white; font-weight: bold; padding: 0px;
    }
    QPushButton:hover { background-color: #1D4ED8; }
"""
HIGHLIGHT_BOX_ERROR = "background-color: rgba(239, 68, 68, 55); border: none;"
HIGHLIGHT_BOX_COMMENT = "background-color: rgba(37, 99, 235, 55); border: none;"
HIGHLIGHT_BOX_DEFAULT = "background-color: rgba(37, 99, 235, 65); border: none;"
HIGHLIGHT_BOX_CUSTOM_COMMENT_STYLE = HIGHLIGHT_BOX_COMMENT

# -------------------------------------------------- reader: right panel
CARD_STYLE = _q("""
    QFrame#Card { background-color: $surface; border: 1px solid $border; border-radius: 12px; }
""")
CONTENT_GRADE_FRAME = CARD_STYLE
CONTENT_GRADE_TITLE = f"color: {TEXT_2}; font-size: 14px; font-weight: 500; border: none; background: transparent;"
CONTENT_GRADE_VALUE = f"color: {TEXT}; font-size: 30px; font-weight: 600; border: none; background: transparent;"
CONTENT_GRADE_DETAILS = f"color: {TEXT_2}; font-size: 14px; border: none; background: transparent;"
CONTENT_GRADE_MISSING = f"color: {TEXT_2}; font-style: italic; border: none; padding-left: 2px;"
AI_NONE_LABEL_STYLE = CONTENT_GRADE_MISSING

GRAPHICS_HEADER_STYLE = f"color: {TEXT}; font-size: 15px; font-weight: 600; border: none; background: transparent;"
STATS_HEADER_STYLE = GRAPHICS_HEADER_STYLE

CRITERION_STYLE = _q("""
    QFrame#Criterion { background-color: $surface; border: 1px solid $border; border-radius: 10px; }
""")
CRITERION_NAME_STYLE = f"color: {TEXT}; font-size: 15px; font-weight: 500; border: none; background: transparent;"
ROW_LABEL_CLEAN = CRITERION_NAME_STYLE

STATS_FRAME_STYLE = CARD_STYLE
STATS_ROW_NAME = f"color: {TEXT_3}; font-size: 14px; border: none; background: transparent;"
STATS_ROW_VALUE = f"color: {TEXT}; font-size: 14px; font-weight: 600; border: none; background: transparent;"

OFF_TOPIC_TITLE_STYLE = f"font-size: 13px; font-weight: 600; color: {DANGER}; margin-top: 8px; background: transparent; border: none;"
OFF_TOPIC_ITEM_STYLE = f"color: {DANGER}; font-size: 13px; padding-left: 5px; background: transparent; border: none;"

RASTER_TAG_STYLE = _q("""
    QLabel {
        background-color: $primary50; color: $primary_hover; border: 1px solid $primary100;
        border-radius: 6px; padding: 2px 8px; font-size: 13px; font-weight: 500;
    }
""")
RASTER_TITLE_STYLE = f"color: {TEXT_2}; font-size: 13px; font-weight: 500; background: transparent; border: none;"
RASTER_ITEM_STYLE = f"color: {TEXT_3}; font-size: 13px; background: transparent; border: none;"


def checkbox_style():
    """Checkbox style with a drawn tick. Needs QApplication, so it is built on demand."""
    from . import icons
    tick = icons.png_path("check", "#FFFFFF", 12, 3.0)
    return CHECKBOX_STYLE + f"QCheckBox::indicator:checked {{ image: url({tick}); }}"