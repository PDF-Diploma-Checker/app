import os
import re

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from common.path import resource_path
from common.version import APP_VERSION

from . import icons, styles
from .i18n import language_signals, t
from .language_switch import LanguageSwitch
from .settings import SettingsDialog
from .update_banner import UpdateBanner

# Column widths shared by the table header and every row, so they always line up.
ICON_W = 38
STATUS_W = 220
DATE_W = 130
ACTION_W = 40
COLUMN_GAP = 16
MAX_CONTENT_WIDTH = 1240



def _plain(text):
    """Drop leading symbols ("+ ", "⇅ ") that a translation may carry: our buttons already have an icon."""
    return re.sub(r"^[^\w]+", "", text or "")


def _docs_count_text(n):
    """"1 dokument" / "2 dokumenty" / "5 dokumentów" (the languages define the three forms)."""
    if n == 1:
        text = t("start.docs_one", n=n)
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        text = t("start.docs_few", n=n)
    else:
        text = t("start.docs_many", n=n)
    return text


def _file_size_text(path):
    """Human readable size of the file, or None when it cannot be read."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")
    return f"{max(1, round(size / 1024))} KB"


class TrashButton(QPushButton):
    """Icon-only delete button: grey at rest, red on hover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rest = icons.icon("trash", styles.TEXT_2, 20)
        self._hot = icons.icon("trash", styles.DANGER, 20)
        self.setIcon(self._rest)
        self.setIconSize(QSize(20, 20))
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(styles.TRASH_BUTTON_STYLE)

    def enterEvent(self, event):
        self.setIcon(self._hot)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setIcon(self._rest)
        super().leaveEvent(event)


def _pdf_icon_label(width, height):
    """The original pdf_file.svg, fitted into width x height (fallback: generic file glyph)."""
    lbl = QLabel()
    lbl.setFixedSize(width, height)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet("background: transparent; border: none;")
    path = resource_path(os.path.join("ui", "assets", "pdf_file.svg"))
    pm = icons.svg_file_pixmap(path, height - 4) if os.path.exists(path) else None
    if pm is None:
        pm = icons.pixmap("file", styles.PRIMARY, height - 10, 1.8)
    else:
        dpr = pm.devicePixelRatio() or 1.0
        if pm.width() / dpr > width:
            pm = pm.scaledToWidth(int(width * dpr), Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
    lbl.setPixmap(pm)
    return lbl


class PDFDropFrame(QFrame):
    """provides drag-and-drop capabilities specialized for filtering and accepting PDF files."""
    fileDropped = Signal(str)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("DropZone")
        self.setCursor(Qt.PointingHandCursor)

    def _set_drag(self, active):
        self.setProperty("drag", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        """Filter incoming drag events to ensure only local files with a .pdf extension are accepted"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith('.pdf'):
                self._set_drag(True)
                event.acceptProposedAction()
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        """Handle valid drop operations, parse the local absolute pathway"""
        self._set_drag(False)
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith('.pdf'):
                self.fileDropped.emit(path)
                event.acceptProposedAction()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class StartPage(QWidget):
    """The landing view interface containing file drop zones, history indexing tables"""
    fileDropped = Signal(str)
    openRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StartPage")
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(styles.START_PAGE_BG)

        self.sort_newest = True
        self.all_files = []
        self.search_text = ""

        self.setup_ui()
        self.retranslate_ui()
        language_signals.changed.connect(self.retranslate_ui)
        self.update_banner.start_check()     # background check; the notice stays hidden unless a newer release exists

    def dragEnterEvent(self, event):
        """Accept initial window dragging protocols if the user enters the active landing space with system URL"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Process layout actions when dropping documents outside the designated boundary box framework."""
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith('.pdf'):
                self.fileDropped.emit(path)
            event.acceptProposedAction()

    # ------------------------------------------------------------------ UI
    def setup_ui(self):
        """Assemble structural drop zones, header controls, query filter panels, and historical document data tables."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._build_app_bar())

        self.update_banner = UpdateBanner()
        main_layout.addWidget(self.update_banner)

        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(self.content_widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        column = QWidget()
        column.setMaximumWidth(MAX_CONTENT_WIDTH)
        column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        content_layout = QVBoxLayout(column)
        content_layout.setContentsMargins(40, 36, 40, 56)
        content_layout.setSpacing(28)

        content_layout.addLayout(self._build_page_head())
        content_layout.addWidget(self._build_dropzone())
        content_layout.addWidget(self._build_docs_card())
        content_layout.addStretch(1)

        outer.addStretch(1)
        outer.addWidget(column, 1000)
        outer.addStretch(1)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.content_widget)
        scroll_area.setStyleSheet(styles.START_PAGE_SCROLL_STYLE)
        main_layout.addWidget(scroll_area, 1)

    def _build_app_bar(self):
        self.header_frame = QFrame()
        self.header_frame.setObjectName("AppBar")
        self.header_frame.setFixedHeight(76)
        self.header_frame.setStyleSheet(styles.HEADER_FRAME_STYLE)

        bar = QHBoxLayout(self.header_frame)
        bar.setContentsMargins(32, 0, 28, 0)
        bar.setSpacing(14)

        self.logo_label = QLabel()
        self.logo_label.setStyleSheet("background: transparent; border: none;")
        self.logo_label.setAccessibleName("DiplomaChecker")
        logo_pixmap = icons.svg_file_pixmap(resource_path(os.path.join("ui", "assets", "logo.svg")), 60)
        if logo_pixmap is not None:
            self.logo_label.setPixmap(logo_pixmap)
        else:
            self.logo_label.setFixedSize(40, 40)
            self.logo_label.setAlignment(Qt.AlignCenter)
            self.logo_label.setPixmap(icons.pixmap("logo", "#FFFFFF", 22, 2.5))
            self.logo_label.setStyleSheet(f"background-color: {styles.PRIMARY}; border-radius: 10px;")
        bar.addWidget(self.logo_label)

        brand = QLabel("DiplomaChecker")
        brand.setStyleSheet(
            f"font-size: 21px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;"
        )
        bar.addWidget(brand)
        version = QLabel(f"v{APP_VERSION}")
        version.setToolTip(t("settings.version", version=APP_VERSION))
        version.setStyleSheet(
            f"font-size: 12px; font-weight: 500; color: {styles.TEXT_2}; background-color: {styles.NEUTRAL_BG};"
            " border: none; border-radius: 8px; padding: 2px 8px;"
        )
        bar.addWidget(version, 0, Qt.AlignVCenter)
        bar.addStretch(1)

        self.lang_switch = LanguageSwitch()
        bar.addWidget(self.lang_switch)
        bar.addSpacing(6)

        self.settings_btn = QPushButton()
        self.settings_btn.setFixedSize(42, 42)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setStyleSheet(styles.ICON_BUTTON_STYLE)
        self.settings_btn.setIcon(icons.icon("settings", styles.TEXT_2, 22))
        self.settings_btn.setIconSize(QSize(22, 22))
        self.settings_btn.clicked.connect(self.open_settings)
        bar.addWidget(self.settings_btn)
        return self.header_frame

    def _build_page_head(self):
        head = QHBoxLayout()
        head.setSpacing(16)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel()
        self.title_label.setStyleSheet(styles.HEADER_TITLE_STYLE)
        self.subtitle_label = QLabel()
        self.subtitle_label.setStyleSheet(styles.SUBTITLE_STYLE)
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        head.addLayout(titles)
        head.addStretch(1)
        return head

    def _build_dropzone(self):
        self.upload_frame = PDFDropFrame()
        self.upload_frame.fileDropped.connect(self.fileDropped.emit)
        self.upload_frame.setStyleSheet(styles.UPLOAD_ZONE_STYLE)
        self.upload_frame.setFixedHeight(270)

        up_layout = QVBoxLayout(self.upload_frame)
        up_layout.setSpacing(10)

        self.pdf_icon = QLabel()
        self.pdf_icon.setFixedSize(76, 76)
        self.pdf_icon.setAlignment(Qt.AlignCenter)
        icon_path = resource_path(os.path.join("ui", "assets", "pdf_file.svg"))
        pdf_pixmap = icons.svg_file_pixmap(icon_path, 46) if os.path.exists(icon_path) else None
        self.pdf_icon.setPixmap(pdf_pixmap if pdf_pixmap is not None else icons.pixmap("file", styles.PRIMARY, 38, 1.8))
        self.pdf_icon.setStyleSheet(styles.PDF_ICON_LABEL_STYLE.replace("35px", "38px"))
        self.pdf_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.txt_drag = QLabel()
        self.txt_drag.setStyleSheet(styles.DRAG_TEXT_STYLE)
        self.txt_drag.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.or_label = QLabel()
        self.or_label.setStyleSheet(styles.OR_LABEL_STYLE)
        self.or_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.add_btn = QPushButton()
        self.add_btn.setIcon(icons.icon("plus", "#FFFFFF", 18, 2.5, disabled="#FFFFFF"))
        self.add_btn.setIconSize(QSize(18, 18))
        self.add_btn.setFixedHeight(46)
        self.add_btn.setMinimumWidth(170)
        self.add_btn.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        self.add_btn.setCursor(Qt.PointingHandCursor)

        up_layout.addStretch()
        up_layout.addWidget(self.pdf_icon, alignment=Qt.AlignCenter)
        up_layout.addWidget(self.txt_drag, alignment=Qt.AlignCenter)
        up_layout.addWidget(self.or_label, alignment=Qt.AlignCenter)
        up_layout.addWidget(self.add_btn, alignment=Qt.AlignCenter)
        up_layout.addStretch()

        self.upload_frame.clicked.connect(self.add_btn.click)
        return self.upload_frame

    def _build_docs_card(self):
        self.docs_card = QFrame()
        self.docs_card.setObjectName("DocsCard")
        self.docs_card.setStyleSheet(styles.DOCS_CARD_STYLE)

        card_layout = QVBoxLayout(self.docs_card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        toolbar = QWidget()
        toolbar.setStyleSheet("background: transparent;")
        search_section = QHBoxLayout(toolbar)
        search_section.setContentsMargins(24, 22, 24, 18)
        search_section.setSpacing(12)

        self.section_title = QLabel()
        self.section_title.setStyleSheet(styles.SECTION_TITLE_STYLE)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(styles.MUTED_LABEL_STYLE)

        self.search_input = QLineEdit()
        self.search_input.setClearButtonEnabled(True)
        self.search_input.addAction(icons.icon("search", "#9CA3AF", 16), QLineEdit.LeadingPosition)
        self.search_input.setStyleSheet(styles.SEARCH_STYLE)
        self.search_input.setFixedWidth(330)
        self.search_input.setFixedHeight(42)
        self.search_input.textChanged.connect(self.on_search)

        self.sort_btn = QPushButton()
        self.sort_btn.setIcon(icons.icon("sort", styles.TEXT_3, 15))
        self.sort_btn.setIconSize(QSize(15, 15))
        self.sort_btn.setStyleSheet(styles.SORT_BTN_STYLE)
        self.sort_btn.setCursor(Qt.PointingHandCursor)
        self.sort_btn.setFixedWidth(250)
        self.sort_btn.setFixedHeight(42)
        self.sort_btn.clicked.connect(self.toggle_sort)

        search_section.addWidget(self.section_title)
        search_section.addWidget(self.count_label)
        search_section.addStretch(1)
        search_section.addWidget(self.search_input)
        search_section.addWidget(self.sort_btn)
        card_layout.addWidget(toolbar)

        self.table_container = QWidget()
        self.table_container.setStyleSheet(styles.TABLE_CONTAINER_STYLE)
        self.table_layout = QVBoxLayout(self.table_container)
        self.table_layout.setContentsMargins(0, 0, 0, 0)
        self.table_layout.setSpacing(0)
        card_layout.addWidget(self.table_container)
        return self.docs_card

    # ------------------------------------------------------------- actions
    def open_settings(self):
        """Otwiera okno dialogowe ustawień konfiguracyjnych"""
        dialog = SettingsDialog(self)
        dialog.exec()

    def on_search(self, text):
        self.search_text = text.lower()
        self._apply_sort_and_render()

    def toggle_sort(self):
        self.sort_newest = not self.sort_newest
        self._update_sort_text()
        self._apply_sort_and_render()

    def _update_sort_text(self):
        self.sort_btn.setText("  " + _plain(t("start.sort_newest") if self.sort_newest else t("start.sort_oldest")))

    def retranslate_ui(self, *_):
        """Re-apply all texts after the UI language changes."""
        self.title_label.setText(t("start.title"))
        self.subtitle_label.setText(t("start.subtitle"))
        self.settings_btn.setToolTip(t("start.settings_tooltip"))
        self.settings_btn.setAccessibleName(t("start.settings_tooltip"))
        self.txt_drag.setText(t("start.drag_here"))
        self.or_label.setText(t("common.or"))
        self.add_btn.setText("  " + _plain(t("start.add_file")))
        self.section_title.setText(t("start.my_documents"))
        self.search_input.setPlaceholderText(t("start.search_placeholder"))
        self.search_input.setAccessibleName(t("start.search_placeholder"))
        self._update_sort_text()
        self._apply_sort_and_render()

    def render_doc_list(self, pliki):
        self.all_files = pliki
        self._apply_sort_and_render()

    # ------------------------------------------------------------ rendering
    def _clear_table(self):
        while self.table_layout.count():
            child = self.table_layout.takeAt(0)
            if child.widget():
                child.widget().hide()
                child.widget().deleteLater()

    def _apply_sort_and_render(self):
        filtered = [p for p in self.all_files if self.search_text in p.get('file_name', '').lower()]
        filtered.sort(key=lambda x: (x.get('date_added', ''), x.get('file_name', '')), reverse=self.sort_newest)

        self.count_label.setText(_docs_count_text(len(filtered)))
        self._clear_table()

        if not filtered:
            self._add_empty_state(has_documents=bool(self.all_files))
            return

        header_row = QWidget()
        header_row.setObjectName("TableHeader")
        header_row.setAttribute(Qt.WA_StyledBackground, True)
        header_row.setStyleSheet(styles.TABLE_HEADER_ROW_STYLE)
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(24, 12, 24, 12)
        header_layout.setSpacing(COLUMN_GAP)

        h_name = QLabel(t("start.col_name"))
        h_name.setStyleSheet(styles.TABLE_HEADER_ROW_TEXT)
        h_name.setContentsMargins(ICON_W + 12, 0, 0, 0)
        h_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        h_config = QLabel(t("start.col_config"))
        h_config.setStyleSheet(styles.TABLE_HEADER_ROW_TEXT)
        h_config.setFixedWidth(STATUS_W)
        h_date = QLabel(t("start.col_date"))
        h_date.setStyleSheet(styles.TABLE_HEADER_ROW_TEXT)
        h_date.setFixedWidth(DATE_W)

        header_layout.addWidget(h_name, 1)
        header_layout.addWidget(h_config)
        header_layout.addWidget(h_date)
        action_gap = QWidget()
        action_gap.setFixedWidth(ACTION_W)
        header_layout.addWidget(action_gap)
        self.table_layout.addWidget(header_row)

        for p in filtered:
            has_config = p.get('plik_konfiguracyjny', p.get('config_path') is not None or True)
            self.add_row(
                name=p.get('file_name', t("start.unknown_name")),
                path=p.get('local_path', ''),
                date=p.get('date_added', t("start.no_date")),
                has_config=has_config,
            )

    def _add_empty_state(self, has_documents):
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(24, 44, 24, 52)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignCenter)

        # Same soft blue circle as the drop zone above, so the empty state belongs to the page.
        circle = QLabel()
        circle.setFixedSize(68, 68)
        circle.setAlignment(Qt.AlignCenter)
        circle.setPixmap(icons.pixmap("search" if has_documents else "folder", styles.PRIMARY, 30, 1.8))
        circle.setStyleSheet(
            f"background-color: {styles.PRIMARY_50}; border: 1px solid {styles.PRIMARY_100}; border-radius: 34px;"
        )

        if has_documents:
            title_text = t("start.no_results_title")
            shown = self.search_text.strip()
            if shown:
                body_text = t("start.no_results_body_query", query=shown)
            else:
                body_text = t("start.no_results_body")
        else:
            title_text = t("start.empty_title")
            body_text = t("start.empty_body")
        title = QLabel(title_text)
        title.setStyleSheet(styles.EMPTY_TITLE_STYLE)
        body = QLabel(body_text)
        body.setStyleSheet(styles.EMPTY_TEXT_STYLE)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignCenter)
        body.setFixedWidth(440)   # keeps the sentence on one or two even lines

        lay.addWidget(circle, alignment=Qt.AlignCenter)
        lay.addSpacing(18)
        lay.addWidget(title, alignment=Qt.AlignCenter)
        lay.addSpacing(6)
        lay.addWidget(body, alignment=Qt.AlignCenter)
        self.table_layout.addWidget(box)

    def _build_status_badge(self, has_config):
        badge = QFrame()
        badge.setFixedHeight(28)
        badge_layout = QHBoxLayout(badge)
        badge_layout.setContentsMargins(4, 0, 12, 0)
        badge_layout.setSpacing(6)

        icon_circle = QLabel()
        icon_circle.setAlignment(Qt.AlignCenter)
        icon_circle.setFixedSize(20, 20)
        text_lbl = QLabel()

        if has_config:
            badge.setStyleSheet(styles.BADGE_FRAME_SUCCESS)
            icon_circle.setPixmap(icons.pixmap("check", "#FFFFFF", 12, 3))
            icon_circle.setStyleSheet(styles.BADGE_ICON_SUCCESS)
            text_lbl.setText(t("start.config_attached"))
            text_lbl.setStyleSheet(styles.BADGE_TEXT_SUCCESS)
        else:
            badge.setStyleSheet(styles.BADGE_FRAME_ERROR)
            icon_circle.setPixmap(icons.pixmap("alert", "#FFFFFF", 12, 3))
            icon_circle.setStyleSheet(styles.BADGE_ICON_ERROR)
            text_lbl.setText(t("start.config_missing"))
            text_lbl.setStyleSheet(styles.BADGE_TEXT_ERROR)

        badge_layout.addWidget(icon_circle)
        badge_layout.addWidget(text_lbl)
        return badge

    def add_row(self, name, path, date, has_config=True):
        row = QWidget()
        row.setObjectName("DocRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setStyleSheet(styles.TABLE_ROW_STYLE)
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(24, 16, 24, 16)
        row_l.setSpacing(COLUMN_GAP)

        name_cell = QWidget()
        name_cell.setStyleSheet("background: transparent;")
        name_cell.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        name_l = QHBoxLayout(name_cell)
        name_l.setContentsMargins(0, 0, 0, 0)
        name_l.setSpacing(12)

        tile = _pdf_icon_label(ICON_W, 46)

        text_vbox = QVBoxLayout()
        text_vbox.setContentsMargins(0, 0, 0, 0)
        text_vbox.setSpacing(0)

        shown_name = QFontMetrics(self.font()).elidedText(name, Qt.ElideMiddle, 620)
        name_btn = QPushButton(shown_name)
        name_btn.setToolTip(name)
        name_btn.setStyleSheet(styles.TABLE_ROW_NAME_BUTTON)
        name_btn.setCursor(Qt.PointingHandCursor)
        name_btn.clicked.connect(lambda _, p=path: self.openRequested.emit(p))

        size_text = _file_size_text(path)
        subtitle = QLabel(f"PDF · {size_text}" if size_text else t("start.pdf_file"))
        subtitle.setStyleSheet(styles.TABLE_ROW_SUBTITLE)

        text_vbox.addWidget(name_btn, alignment=Qt.AlignLeft)
        text_vbox.addWidget(subtitle)

        name_l.addWidget(tile)
        name_l.addLayout(text_vbox, 1)

        status_container = QWidget()
        status_container.setStyleSheet("background: transparent;")
        status_container.setFixedWidth(STATUS_W)
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.addWidget(self._build_status_badge(has_config))
        status_layout.addStretch(1)

        date_lbl = QLabel(str(date))
        date_lbl.setStyleSheet(styles.TABLE_ROW_DATE)
        date_lbl.setFixedWidth(DATE_W)

        del_btn = TrashButton()
        del_btn.setFixedSize(ACTION_W, ACTION_W)
        del_btn.setToolTip(t("start.delete"))
        del_btn.setAccessibleName(f"{t('start.delete')} {name}")
        del_btn.clicked.connect(lambda _=False, p=path: self.deleteRequested.emit(p))

        row_l.addWidget(name_cell, 1)
        row_l.addWidget(status_container)
        row_l.addWidget(date_lbl)
        row_l.addWidget(del_btn)

        self.table_layout.addWidget(row)