"""The verification panel on the right of the reader, in the same look as the detailed PDF report (ui/report_pdf.py):
sections with a blue accent bar, cards with coloured progress bars, notices and chips. Only the essentials are shown;
the rest is in the detailed report.

    widget, download_button = build_report_panel(report_data, on_download)

`report_data` is the AI result stored for the document. The texts come from the app language (t()).
"""

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from . import icons, styles
from .i18n import t

TRACK = "#E5E7EB"
INDIGO = "#6366F1"
TRANSPARENT = "background: transparent; border: none;"


# ----------------------------------------------------------------------------- helpers
def _number(value, default=0.0):
    try:
        return float(str(value).replace("%", "").replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def _fmt(value):
    value = _number(value)
    return str(int(value)) if value == int(value) else f"{value:.1f}".rstrip("0").rstrip(".")


def _ratio_colors(ratio):
    """(text colour, background, bar colour) for a 0..1 score: green, amber or red."""
    if ratio >= 0.7:
        return styles.SUCCESS, styles.SUCCESS_BG, styles.SUCCESS_DOT
    if ratio >= 0.4:
        return styles.WARNING, styles.WARNING_BG, styles.WARNING_DOT
    return styles.DANGER, styles.DANGER_BG, styles.DANGER_DOT


class _FlowLayout(QLayout):
    """Lays small widgets out left to right and wraps them onto new lines (for the figure chips)."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, apply):
        x, y, row_h = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and row_h > 0:
                x, y, row_h = rect.x(), y + row_h + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y()


def _label(text, style, wrap=True):
    lbl = QLabel(text)
    lbl.setWordWrap(wrap)
    lbl.setStyleSheet(style)
    return lbl


def _section(title):
    """Section title with the blue accent bar of the PDF report."""
    box = QWidget()
    box.setStyleSheet("background: transparent;")
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 2, 0, 0)
    row.setSpacing(8)
    bar = QFrame()
    bar.setFixedSize(4, 17)
    bar.setStyleSheet(f"background-color: {styles.PRIMARY}; border: none; border-radius: 2px;")
    row.addWidget(bar)
    row.addWidget(_label(title, f"font-size: 15px; font-weight: 700; color: {styles.TEXT}; {TRANSPARENT}"), 1)
    return box


def _card():
    card = QFrame()
    card.setObjectName("Card")
    card.setStyleSheet(styles.CARD_STYLE)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(10)
    return card, lay


def _bar(label, value_text, ratio, color=None, description=None):
    """Label and value on one line, a coloured bar below, an optional grey description."""
    ratio = max(0.0, min(1.0, ratio))
    text_c, _bg, bar_c = _ratio_colors(ratio)
    text_c, bar_c = color or text_c, color or bar_c
    box = QWidget()
    box.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    head = QHBoxLayout()
    head.addWidget(_label(label, f"font-size: 14px; font-weight: 600; color: {styles.TEXT}; {TRANSPARENT}"), 1)
    head.addWidget(_label(value_text, f"font-size: 14px; font-weight: 700; color: {text_c}; {TRANSPARENT}", wrap=False))
    lay.addLayout(head)
    bar = QProgressBar()
    bar.setRange(0, 1000)
    bar.setValue(int(ratio * 1000))
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    bar.setStyleSheet(
        f"QProgressBar {{ border: none; border-radius: 4px; background-color: {TRACK}; }}"
        f"QProgressBar::chunk {{ border-radius: 4px; background-color: {bar_c}; }}"
    )
    lay.addWidget(bar)
    if description:
        lay.addWidget(_label(description, f"font-size: 12px; color: {styles.TEXT_2}; {TRANSPARENT}"))
    return box


def _note(text, kind):
    """A coloured notice: 'ok' (green), 'bad' (red) or 'off' (grey)."""
    fg, bg, dot = {
        "ok": (styles.SUCCESS, styles.SUCCESS_BG, styles.SUCCESS_DOT),
        "bad": (styles.DANGER, styles.DANGER_BG, styles.DANGER_DOT),
        "off": (styles.TEXT_2, styles.NEUTRAL_BG, styles.TEXT_2),
    }[kind]
    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background-color: {bg}; border: none; border-radius: 8px; }}")
    lay = QHBoxLayout(frame)
    lay.setContentsMargins(12, 9, 12, 9)
    lay.setSpacing(9)
    mark = QFrame()
    mark.setFixedSize(8, 8)
    mark.setStyleSheet(f"background-color: {dot}; border: none; border-radius: 4px;")
    lay.addWidget(mark, alignment=Qt.AlignVCenter)
    lay.addWidget(_label(text, f"font-size: 13px; font-weight: 500; color: {fg}; {TRANSPARENT}"), 1)
    return frame


def _chips(labels):
    box = QWidget()
    box.setStyleSheet("background: transparent;")
    flow = _FlowLayout(box, spacing=6)
    for text in labels:
        chip = QLabel(text)
        chip.setStyleSheet(
            f"background-color: {styles.PRIMARY_50}; color: {styles.PRIMARY_PRESSED}; border: 1px solid {styles.PRIMARY_200}; "
            "border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 700;"
        )
        flow.addWidget(chip)
    box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return box


def _bullets(items, color):
    lines = "".join(
        f"<tr><td style='color:{color}; padding-right:6px;' valign='top'>&#9679;</td>"
        f"<td style='color:{styles.TEXT};'>{_escape(item)}</td></tr>"
        for item in items
    )
    lbl = QLabel(f"<table cellspacing='3'>{lines}</table>")
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setStyleSheet(f"font-size: 13px; {TRANSPARENT}")
    return lbl


def _escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ----------------------------------------------------------------------------- the panel
def build_report_panel(report_data, on_download):
    """Returns (scrollable content widget, the "download report" button)."""
    data = report_data or {}
    content = QWidget()
    content.setStyleSheet("background: transparent; border: none;")
    root = QVBoxLayout(content)
    root.setContentsMargins(0, 4, 10, 20)
    root.setSpacing(12)

    grade_info = data.get("content_grade")
    img = data.get("image_analysis")
    img = img if isinstance(img, dict) else {}
    total_figs = int(_number(img.get("total", 0)))
    stats = data.get("statystyki_zdan")

    grade, max_g, off_topic, p_off, headings = 0.0, 100.0, 0, 0, []
    if grade_info is not None:
        if isinstance(grade_info, dict):
            grade = _number(grade_info.get("grade", 0))
            max_g = _number(grade_info.get("max_grade", 100), 100.0) or 100.0
            off_topic = int(_number(grade_info.get("off_topic_sections", 0)))
            p_off = grade_info.get("p_off", 0)
            headings = grade_info.get("off_topic_headings", []) or []
        else:
            grade = _number(grade_info)

    # ---- content grade
    root.addWidget(_section(t("main.overall_grade")))
    card, lay = _card()
    if grade_info is None:
        lay.addWidget(_note(t("main.no_content_analysis"), "off"))
    else:
        lay.addWidget(_bar(t("main.score_label"), f"{_fmt(grade)} / {_fmt(max_g)} {t('main.points')}", grade / max_g))
        lay.addWidget(_label(t("main.off_topic", count=off_topic, percent=p_off),
                             f"font-size: 13px; color: {styles.TEXT_3}; {TRANSPARENT}"))
        if off_topic > 0 and headings:
            lay.addWidget(_label(t("main.off_topic_list"), f"font-size: 13px; font-weight: 700; color: {styles.DANGER}; {TRANSPARENT}"))
            lay.addWidget(_bullets(headings, styles.DANGER_DOT))
    root.addWidget(card)

    # ---- figures
    root.addWidget(_section(t("main.graphics_header")))
    card, lay = _card()
    if grade_info is not None and total_figs > 0:
        quality, fonts = data.get("jakosc_obrazkow") or [], data.get("czcionki_obrazkow") or []
        lay.addWidget(_note(t("main.image_quality_errors", count=len(quality)) if quality else t("main.image_quality_ok"),
                            "bad" if quality else "ok"))
        lay.addWidget(_note(t("main.font_consistency_errors", count=len(fonts)) if fonts else t("main.font_consistency_ok"),
                            "bad" if fonts else "ok"))
    else:
        lay.addWidget(_note(t("main.no_figures_checked"), "off"))
    raster = img.get("image_raster", []) or []
    if raster:
        lay.addWidget(_label(t("main.raster_detected"), f"font-size: 12px; font-weight: 600; color: {styles.TEXT_2}; {TRANSPARENT}"))
        lay.addWidget(_chips([t("main.figure_chip", num=n) for n in raster]))
    root.addWidget(card)

    # ---- sentence statistics
    if stats:
        root.addWidget(_section(t("main.stats_header")))
        card, lay = _card()
        lay.setSpacing(12)
        for key, name, colour in (("active_ratio", "main.stats_active", styles.PRIMARY),
                                  ("passive_ratio", "main.stats_passive", INDIGO),
                                  ("verbless_ratio", "main.stats_verbless", styles.TEXT_2)):
            value = _number(stats.get(key, 0))
            lay.addWidget(_bar(t(name).rstrip(":"), f"{_fmt(value)}%", value / 100, color=colour))
        root.addWidget(card)

    root.addStretch()

    button = QPushButton(t("main.download_report"))
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(styles.RAPORT_BTN_STYLE)
    button.clicked.connect(on_download)
    root.addWidget(button)
    return content, button
