import datetime
import logging
import os

import fitz
from PySide6.QtCore import QMargins, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from common.path import resource_path

from . import icons, styles
from .i18n import language_signals, t
from .language_switch import LanguageSwitch
from .analysis_dialog import AnalysisDialog
from .log_window import LogWindow
from .message_box import MessageBox
from .report_bug import send_report
from .saving_files import SavingFiles
from .select_text import CommentMarker, HighlightBox, SelectablePdfView
from .start_page import StartPage

logger = logging.getLogger(__name__)



class PDFReader(QMainWindow):
    """The main window component of the Diploma Checker application.
    Manages the user interface flow, PDF rendering, and view states."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("main.window_title"))
        self.resize(1440, 860)
        self.manager = SavingFiles()
        self.own_comments = []
        self.current_pdf_path = None
        self.document = QPdfDocument(self)
        self._log_window = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.start_page = StartPage()

        self.start_page.add_btn.clicked.connect(self.open_file_dialog)
        self.start_page.fileDropped.connect(self.load_and_switch)

        self.start_page.openRequested.connect(self.open_existing_file)

        self.start_page.deleteRequested.connect(self.delete_document)
        self.stack.addWidget(self.start_page)

        self.reader_container = QWidget()
        self.setup_reader_ui()
        self.stack.addWidget(self.reader_container)

        self.refresh_file_list()
        self.overlay = QFrame(self)
        self.overlay.setStyleSheet(styles.OVERLAY_STYLE)
        self.overlay.hide()

        language_signals.changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def retranslate_ui(self, *_):
        """Re-apply all window texts after the UI language changes."""
        self.setWindowTitle(t("main.window_title"))
        self.v_label.setText(t("main.verification"))
        self.back_btn.setText("  " + t("main.back"))
        self.back_btn.setToolTip(t("main.back_tooltip"))
        self.page_input.setAccessibleName(t("main.page_number"))
        self.btn_zoom_in.setToolTip(t("main.zoom_in"))
        self.btn_zoom_in.setAccessibleName(t("main.zoom_in"))
        self.btn_zoom_out.setToolTip(t("main.zoom_out"))
        self.btn_zoom_out.setAccessibleName(t("main.zoom_out"))
        self.export_btn.setText("  " + t("main.export_pdf"))
        self.report_btn.setText("  " + t("main.report_problem"))
        self.logs_btn.setText(t("main.logs"))
        if self.current_pdf_path:
            self.load_ai_analysis()
        else:
            self.title_label.setText(t("main.no_document"))
            self.report_scroll.setWidget(self._build_report_placeholder())

    def resizeEvent(self, event):
        """Keep the dimming overlay the same size as the window."""
        super().resizeEvent(event)
        if hasattr(self, "overlay") and self.overlay is not None:
            self.overlay.resize(event.size())

    def open_existing_file(self, path):
        """Loads an already listed file from the disk storage and transitions the interface view
        into the reading/annotation viewport."""
        self.load_pdf(path)
        if self.document.status() == QPdfDocument.Status.Ready:
            report_data = None
            for p in self.manager.data.get("documents", []):
                if p.get("local_path") == path:
                    report_data = p.get("sota_result")
                    break

            lang = report_data.get("language", "pl") if report_data else "pl"

            errors = self.manager.get_errors(path)
            if errors:
                self.pdf_view.add_errors(errors, lang=lang)
                if hasattr(self.pdf_view, "update_markers_pos"):
                    self.pdf_view.update_markers_pos()
                else:
                    self.pdf_view.update()

            self.load_ai_analysis()
            self.stack.setCurrentIndex(1)

    def setup_reader_ui(self):
        """Assembles layout components, content areas, sidebar panels and toolbar items."""
        layout = QVBoxLayout(self.reader_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toolbar = self._create_toolbar()
        layout.addWidget(self.toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        self.thumb_buttons = []
        self.thumb_group = QButtonGroup(self)
        self.thumb_group.setExclusive(True)

        self.thumb_area = QScrollArea()
        self.thumb_area.setFixedWidth(176)
        self.thumb_area.setWidgetResizable(True)
        self.thumb_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumb_area.setStyleSheet(styles.THUMB_AREA_STYLE)

        self.thumb_widget = QWidget()
        self.thumb_layout = QVBoxLayout(self.thumb_widget)
        self.thumb_layout.setContentsMargins(12, 16, 12, 16)
        self.thumb_layout.setSpacing(6)
        self.thumb_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.thumb_area.setWidget(self.thumb_widget)

        self.pdf_view = SelectablePdfView()
        self.pdf_view.setDocument(self.document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setStyleSheet(styles.PDF_VIEW_STYLE)
        # QPdfView paints its backdrop with the palette's Dark role; style sheets do not reach it.
        view_palette = self.pdf_view.palette()
        view_palette.setColor(QPalette.Dark, QColor(styles.VIEWER_BG))
        self.pdf_view.setPalette(view_palette)
        self.pdf_view.setDocumentMargins(QMargins(16, 16, 16, 16))
        self.pdf_view.setPageSpacing(16)
        self.pdf_view.pageNavigator().currentPageChanged.connect(self.update_page_input)
        self.pdf_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pdf_view.customContextMenuRequested.connect(self.add_comment)
        self.pdf_view.commentAdded.connect(self.save_custom_comment)

        self.right_panel = QWidget()
        self.right_panel.setObjectName("RightPanel")
        self.right_panel.setAttribute(Qt.WA_StyledBackground, True)
        self.right_panel.setFixedWidth(380)
        self.right_panel.setStyleSheet(styles.RIGHT_PANEL_STYLE)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(24, 24, 24, 0)
        right_layout.setSpacing(12)
        self.v_label = QLabel()
        self.v_label.setStyleSheet(styles.VERIFY_TITLE_STYLE)
        right_layout.addWidget(self.v_label)

        self.report_scroll = QScrollArea()
        self.report_scroll.setWidgetResizable(True)
        self.report_scroll.setFrameShape(QFrame.NoFrame)
        self.report_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.report_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        right_layout.addWidget(self.report_scroll, 1)
        self.report_scroll.setWidget(self._build_report_placeholder())

        splitter.addWidget(self.thumb_area)
        splitter.addWidget(self.pdf_view)
        splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)
        self.toolbar.raise_()

    def _build_report_placeholder(self):
        """Empty state shown in the verification panel until a document has been analysed."""
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 8, 0, 0)
        lbl = QLabel(t("main.report_placeholder"))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(styles.MUTED_LABEL_STYLE)
        lay.addWidget(lbl)
        lay.addStretch(1)
        return box

    @staticmethod
    def _tool_button(icon_name, tooltip, accessible):
        btn = QPushButton()
        btn.setFixedSize(34, 34)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setAccessibleName(accessible)
        btn.setStyleSheet(styles.ICON_BUTTON_STYLE)
        btn.setIcon(icons.icon(icon_name, styles.TEXT_3, 18, 2.25))
        btn.setIconSize(QSize(18, 18))
        return btn

    @staticmethod
    def _divider():
        line = QFrame()
        line.setFixedSize(1, 20)
        line.setStyleSheet(styles.TOOLS_DIVIDER_STYLE)
        return line

    def _create_toolbar(self):
        """Factory method that builds, styles, and links triggers for the top application toolbar."""
        toolbar = QWidget()
        toolbar.setObjectName("Toolbar")
        toolbar.setAttribute(Qt.WA_StyledBackground, True)
        toolbar.setFixedHeight(68)
        toolbar.setStyleSheet(styles.TOOLBAR_STYLE)

        l = QHBoxLayout(toolbar)
        l.setContentsMargins(18, 0, 24, 0)
        l.setSpacing(12)

        self.back_btn = QPushButton()
        self.back_btn.setIcon(icons.icon("arrow-left", styles.TEXT_3, 18, 2.25))
        self.back_btn.setIconSize(QSize(18, 18))
        self.back_btn.setFixedHeight(40)
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setStyleSheet(
            styles.ICON_BUTTON_STYLE
            + f"QPushButton {{ padding: 0 12px 0 8px; font-size: 14px; font-weight: 500; color: {styles.TEXT_3}; }}"
        )
        self.back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        l.addWidget(self.back_btn)
        l.addWidget(self._divider())

        self.title_label = QLabel(t("main.no_document"))
        self.title_label.setStyleSheet(styles.NORMAL_LABEL_STYLE)
        l.addWidget(self.title_label)
        l.addStretch(1)

        tools = QFrame()
        tools.setObjectName("ViewTools")
        tools.setStyleSheet(styles.VIEW_TOOLS_STYLE)
        tools.setFixedHeight(48)
        tl = QHBoxLayout(tools)
        tl.setContentsMargins(8, 4, 8, 4)
        tl.setSpacing(6)

        self.page_input = QLineEdit("1")
        self.page_input.setFixedWidth(48)
        self.page_input.setAlignment(Qt.AlignCenter)
        self.page_input.setStyleSheet(styles.PAGE_INPUT_STYLE)
        self.total_pages_label = QLabel(" / 0 ")
        self.total_pages_label.setStyleSheet(styles.TOOLS_MUTED_STYLE)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(52)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setStyleSheet(styles.TOOLS_LABEL_STYLE)

        self.btn_zoom_in = self._tool_button("plus", "", "")
        self.btn_zoom_in.clicked.connect(self.zoom_in)

        self.btn_zoom_out = self._tool_button("minus", "", "")
        self.btn_zoom_out.clicked.connect(self.zoom_out)

        tl.addWidget(self.page_input)
        tl.addWidget(self.total_pages_label)
        tl.addWidget(self._divider())
        tl.addWidget(self.btn_zoom_out)
        tl.addWidget(self.zoom_label)
        tl.addWidget(self.btn_zoom_in)
        l.addWidget(tools, alignment=Qt.AlignVCenter)
        l.addStretch(1)

        self.lang_switch = LanguageSwitch()
        l.addWidget(self.lang_switch)
        l.addSpacing(8)

        self.export_btn = QPushButton()
        self.export_btn.setIcon(icons.icon("download", "#FFFFFF", 18, 2.25, disabled="#FFFFFF"))
        self.export_btn.setIconSize(QSize(18, 18))
        self.export_btn.setFixedHeight(42)
        self.export_btn.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self.export_pdf_with_annotations)
        l.addWidget(self.export_btn)

        self.report_btn = QPushButton()
        self.report_btn.setIcon(icons.icon("alert", styles.WARNING, 18, 2.25))
        self.report_btn.setIconSize(QSize(18, 18))
        self.report_btn.setFixedHeight(42)
        self.report_btn.setStyleSheet(styles.REPORT_BUTTON_STYLE)
        self.report_btn.setCursor(Qt.PointingHandCursor)
        self.report_btn.clicked.connect(
            lambda: send_report(self, getattr(self, "current_pdf_path", None))
        )
        l.addWidget(self.report_btn)

        self.logs_btn = QPushButton()
        self.logs_btn.setFixedHeight(42)
        self.logs_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        self.logs_btn.setCursor(Qt.PointingHandCursor)
        self.logs_btn.clicked.connect(self.show_log_window)
        l.addWidget(self.logs_btn)

        return toolbar

    def show_log_window(self):
        """Show the live log window, creating it on first use."""
        if self._log_window is None:
            self._log_window = LogWindow(self)
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()

    def open_file_dialog(self):
        """Opens a native file dialog filtered for PDF files."""
        path, _ = QFileDialog.getOpenFileName(self, t("main.choose_pdf"), "", t("common.pdf_filter"))
        if path:
            self.load_and_switch(path)

    def load_and_switch(self, path):
        """Imports a new document into the index manager, loads its content,
        and switches the active UI view stack to the PDF reader interface."""
        self.overlay.show()
        dialog = AnalysisDialog(path, self)
        result = dialog.exec()

        self.overlay.hide()

        if result == QDialog.Accepted:
            self.load_pdf(path)
            self.manager.add_document(os.path.basename(path), path, "PDF")
            self.refresh_file_list()

            final_rep_obj = getattr(dialog, "final_report", None)
            errors = []
            report_data = {}
            lang = "pl"

            if isinstance(final_rep_obj, dict):
                errors = final_rep_obj.get("errors", [])
                report_data = final_rep_obj.get("sota") or {}
                lang = final_rep_obj.get("language", "pl")
            elif final_rep_obj is not None:
                errors = getattr(final_rep_obj, "linguistics_errors", [])
                report_data = getattr(final_rep_obj, "llm_result", {}) or {}
                lang = report_data.get("language", "pl")

            report_data["language"] = lang

            self.manager.save_errors(path, errors)
            self.manager.save_ai_result(path, report_data)

            self.stack.setCurrentIndex(1)

            if errors:
                self.pdf_view.add_errors(errors, lang=lang)
                if hasattr(self.pdf_view, "update_markers_pos"):
                    self.pdf_view.update_markers_pos()
                else:
                    self.pdf_view.update()

            if report_data:
                self.update_report_panel(report_data)
            else:
                self.load_ai_analysis()

    def generate_thumbnails(self):
        """Clears out old thumbnails and renders a preview for each page of the loaded PDF."""
        for btn in self.thumb_buttons:
            self.thumb_group.removeButton(btn)
        self.thumb_buttons = []
        for i in reversed(range(self.thumb_layout.count())):
            w = self.thumb_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        thumb_w = 118
        for i in range(self.document.pageCount()):
            size_pt = self.document.pagePointSize(i)
            ratio = (size_pt.height() / size_pt.width()) if size_pt.width() > 0 else 1.414
            thumb_h = max(40, int(round(thumb_w * ratio)))

            btn = QToolButton()
            btn.setCheckable(True)
            btn.setText(str(i + 1))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            page_pixmap = QPixmap.fromImage(self.document.render(i, QSize(thumb_w, thumb_h)))
            painter = QPainter(page_pixmap)
            painter.setPen(QColor(styles.BORDER_STRONG))
            painter.drawRect(0, 0, page_pixmap.width() - 1, page_pixmap.height() - 1)
            painter.end()
            btn.setIcon(page_pixmap)
            btn.setIconSize(QSize(thumb_w, thumb_h))
            btn.setAccessibleName(t("main.page_n", n=i + 1))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(styles.THUMB_BUTTON_STYLE)
            btn.clicked.connect(
                lambda chk, idx=i: self.pdf_view.pageNavigator().jump(
                    idx, QPointF(0, 0), self.pdf_view.zoomFactor()
                )
            )
            self.thumb_group.addButton(btn)
            self.thumb_buttons.append(btn)
            self.thumb_layout.addWidget(btn, alignment=Qt.AlignHCenter)

        if self.thumb_buttons:
            self.thumb_buttons[0].setChecked(True)

    def add_comment(self, pos):
        """Converts a context-menu click position to PDF coordinates and adds a note there."""
        if not self.current_pdf_path:
            return

        if self.pdf_view.selection_box.isVisible() and self.pdf_view.selection_box.geometry().contains(pos):
            return

        tekst, ok = QInputDialog.getMultiLineText(self, t("main.own_comment_title"), t("main.own_comment_prompt"))

        if ok and tekst.strip():
            aktualna_strona = self.pdf_view.pageNavigator().currentPage()
            zoom = self.pdf_view.zoomFactor()

            scroll_x = self.pdf_view.horizontalScrollBar().value()
            scroll_y = self.pdf_view.verticalScrollBar().value()
            dpi_x, dpi_y = self.pdf_view.logicalDpiX(), self.pdf_view.logicalDpiY()

            doc = self.document
            size_pt = doc.pagePointSize(aktualna_strona)
            page_w_px = size_pt.width() * zoom * (dpi_x / 72.0)
            viewport_w = self.pdf_view.viewport().width()

            x_start_px = (
                self.pdf_view.documentMargins().left()
                if self.pdf_view.horizontalScrollBar().maximum() > 0
                else (viewport_w - page_w_px) / 2
            )

            target_page_y_px = self.pdf_view.documentMargins().top()
            for i in range(aktualna_strona):
                page_size = doc.pagePointSize(i)
                page_h_px = int((page_size.height() * zoom * (dpi_y / 72.0)) + 0.5)
                target_page_y_px += page_h_px + self.pdf_view.pageSpacing()

            pdf_x = ((pos.x() + scroll_x - x_start_px) / zoom) * (72.0 / dpi_x)
            pdf_y = ((pos.y() + scroll_y - target_page_y_px) / zoom) * (72.0 / dpi_y)

            comment_data = {
                "strona": aktualna_strona + 1,
                "wspolrzedne": {"x": pdf_x, "y": pdf_y},
                "tekst_komentarza": tekst.strip(),
                "znaleziony_tekst": t("main.comment_empty_spot"),
            }
            marker = CommentMarker(comment_data, self.pdf_view.viewport())
            self.pdf_view.comment_markers.append(marker)
            self.pdf_view.update_markers_pos()
            self.save_custom_comment(comment_data)

    def update_report_panel(self, report_data):
        """Rebuilds the verification panel with the evaluated AI quality metrics,
        image checks, off-topic lists and sentence statistics."""
        if not report_data:
            report_data = {}

        def make_card():
            card = QFrame()
            card.setObjectName("Card")
            card.setStyleSheet(styles.CARD_STYLE)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            card_layout.setSpacing(6)
            return card, card_layout

        content = QWidget()
        content.setStyleSheet("background: transparent; border: none;")
        l = QVBoxLayout(content)
        l.setContentsMargins(0, 4, 10, 20)
        l.setSpacing(16)

        content_grade = report_data.get("content_grade")
        if content_grade is not None:
            if isinstance(content_grade, dict):
                grade = content_grade.get("grade", 0.0)
                max_grade = content_grade.get("max_grade", 100.0)
                p_off = content_grade.get("p_off", 0.0)
                off_topic = content_grade.get("off_topic_sections", 0)
            elif isinstance(content_grade, (float, int)):
                grade = float(content_grade)
                max_grade = 100.0
                p_off = 0.0
                off_topic = 0
            else:
                grade = 0.0
                max_grade = 100.0
                p_off = 0.0
                off_topic = 0

            cg_frame, cg_layout = make_card()

            cg_title = QLabel(t("main.overall_grade"))
            cg_title.setStyleSheet(styles.CONTENT_GRADE_TITLE)

            cg_val = QLabel(
                f"{grade} <span style='font-size: 15px; font-weight: 400; color: {styles.TEXT_2};'>"
                f"/ {max_grade} {t('main.points')}</span>"
            )
            cg_val.setStyleSheet(styles.CONTENT_GRADE_VALUE)

            cg_bar = QProgressBar()
            cg_bar.setRange(0, 100)
            try:
                cg_bar.setValue(int(max(0, min(100, float(grade) / float(max_grade) * 100))))
            except (TypeError, ValueError, ZeroDivisionError):
                cg_bar.setValue(0)
            cg_bar.setTextVisible(False)
            cg_bar.setStyleSheet(styles.PROGRESS_THIN_STYLE)

            detale_lbl = QLabel(t("main.off_topic", count=off_topic, percent=p_off))
            detale_lbl.setWordWrap(True)
            detale_lbl.setStyleSheet(styles.CONTENT_GRADE_DETAILS)

            cg_layout.addWidget(cg_title)
            cg_layout.addWidget(cg_val)
            cg_layout.addWidget(cg_bar)
            cg_layout.addSpacing(2)
            cg_layout.addWidget(detale_lbl)

            l.addWidget(cg_frame)
        else:
            none_label = QLabel(t("main.no_content_analysis"))
            none_label.setStyleSheet(styles.AI_NONE_LABEL_STYLE)
            l.addWidget(none_label)

        def create_badge_row(label_text, is_met):
            """One verification criterion: status icon, name and a status pill."""
            row = QFrame()
            row.setObjectName("Criterion")
            row.setStyleSheet(styles.CRITERION_STYLE)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 12, 14, 12)
            row_layout.setSpacing(10)

            icon_circle = QLabel()
            icon_circle.setFixedSize(30, 30)
            icon_circle.setAlignment(Qt.AlignCenter)

            if is_met:
                fg, bg = styles.SUCCESS, styles.SUCCESS_BG
                icon_circle.setPixmap(icons.pixmap("check", fg, 16, 2.5))
                status_text = t("main.criterion_met")
            else:
                fg, bg = styles.DANGER, styles.DANGER_BG
                icon_circle.setPixmap(icons.pixmap("close", fg, 16, 2.5))
                status_text = t("main.criterion_not_met")
            icon_circle.setStyleSheet(f"background-color: {bg}; border: none; border-radius: 8px;")

            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(4)

            lbl = QLabel(label_text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(styles.CRITERION_NAME_STYLE)

            pill = QLabel(status_text)
            pill.setStyleSheet(
                f"background-color: {bg}; color: {fg}; border: none; border-radius: 9px; "
                "padding: 2px 10px; font-size: 13px; font-weight: 500;"
            )

            text_col.addWidget(lbl)
            text_col.addWidget(pill, alignment=Qt.AlignLeft)

            row_layout.addWidget(icon_circle, alignment=Qt.AlignTop)
            row_layout.addLayout(text_col, 1)
            return row

        graphics_container = QWidget()
        graphics_layout = QVBoxLayout(graphics_container)
        graphics_layout.setContentsMargins(0, 0, 0, 0)
        graphics_layout.setSpacing(8)

        graphics_header = QLabel(t("main.graphics_header"))
        graphics_header.setStyleSheet(styles.GRAPHICS_HEADER_STYLE)
        graphics_layout.addWidget(graphics_header)

        img_data = report_data.get("image_analysis", {})
        if not isinstance(img_data, dict):
            img_data = {}
        has_images_checked = img_data.get("total", 0) > 0

        if content_grade is not None and has_images_checked:
            quality_errors = report_data.get("jakosc_obrazkow", [])
            font_errors = report_data.get("czcionki_obrazkow", [])

            if not quality_errors:
                graphics_layout.addWidget(create_badge_row(t("main.image_quality_ok"), True))
            else:
                graphics_layout.addWidget(create_badge_row(t("main.image_quality_errors", count=len(quality_errors)), False))

            if not font_errors:
                graphics_layout.addWidget(create_badge_row(t("main.font_consistency_ok"), True))
            else:
                graphics_layout.addWidget(create_badge_row(t("main.font_consistency_errors", count=len(font_errors)), False))
        else:
            no_checks = QLabel(t("main.no_figures_checked"))
            no_checks.setStyleSheet(styles.MUTED_LABEL_STYLE)
            graphics_layout.addWidget(no_checks)

        raster_nums = img_data.get("image_raster", [])

        if raster_nums:
            raster_card, raster_box_layout = make_card()
            raster_box_layout.setSpacing(4)

            raster_title = QLabel(t("main.raster_detected"))
            raster_title.setWordWrap(True)
            raster_title.setStyleSheet(styles.RASTER_TITLE_STYLE)
            raster_box_layout.addWidget(raster_title)

            raster_list = QLabel("  ·  ".join(t("main.figure_item", num=num) for num in raster_nums))
            raster_list.setWordWrap(True)
            raster_list.setStyleSheet(
                f"color: {styles.TEXT}; font-size: 14px; font-weight: 500; background: transparent; border: none;"
            )
            raster_box_layout.addWidget(raster_list)

            graphics_layout.addWidget(raster_card)
        l.addWidget(graphics_container)

        stats_data = report_data.get("statystyki_zdan")
        if stats_data:
            stats_container = QWidget()
            stats_vbox = QVBoxLayout(stats_container)
            stats_vbox.setContentsMargins(0, 0, 0, 0)
            stats_vbox.setSpacing(8)

            stats_header = QLabel(t("main.stats_header"))
            stats_header.setStyleSheet(styles.STATS_HEADER_STYLE)
            stats_vbox.addWidget(stats_header)

            stats_frame, stats_layout = make_card()
            stats_layout.setSpacing(10)

            def create_stat_row(name, val):
                row = QWidget()
                row.setStyleSheet("background: transparent;")
                row_l = QHBoxLayout(row)
                row_l.setContentsMargins(0, 0, 0, 0)
                lbl_name = QLabel(name)
                lbl_name.setStyleSheet(styles.STATS_ROW_NAME)
                lbl_val = QLabel(f"{val}")
                lbl_val.setStyleSheet(styles.STATS_ROW_VALUE)
                row_l.addWidget(lbl_name, 1)
                row_l.addWidget(lbl_val, alignment=Qt.AlignRight)
                return row

            stats_layout.addWidget(create_stat_row(t("main.stats_active"), stats_data.get("active_ratio", "0%")))
            stats_layout.addWidget(create_stat_row(t("main.stats_passive"), stats_data.get("passive_ratio", "0%")))
            stats_layout.addWidget(create_stat_row(t("main.stats_verbless"), stats_data.get("verbless_ratio", "0%")))

            stats_vbox.addWidget(stats_frame)
            l.addWidget(stats_container)

        l.addStretch()

        self.raport_btn = QPushButton(t("main.download_report"))
        self.raport_btn.setCursor(Qt.PointingHandCursor)
        self.raport_btn.setStyleSheet(styles.RAPORT_BTN_STYLE)
        self.raport_btn.clicked.connect(self.generate_detailed_report)
        l.addWidget(self.raport_btn)

        self.report_scroll.setWidget(content)

    def zoom_in(self):
        """Increases the zoom of the document viewport."""
        self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() * 1.1)
        self.zoom_label.setText(f"{int(self.pdf_view.zoomFactor() * 100)}%")

    def zoom_out(self):
        """Decreases the zoom of the document viewport."""
        self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() / 1.1)
        self.zoom_label.setText(f"{int(self.pdf_view.zoomFactor() * 100)}%")

    def update_page_input(self, idx):
        """Syncs the current page index back to the page box and highlights its thumbnail."""
        self.page_input.setText(str(idx + 1))
        if 0 <= idx < len(self.thumb_buttons):
            self.thumb_buttons[idx].setChecked(True)
            self.thumb_area.ensureWidgetVisible(self.thumb_buttons[idx], 0, 40)

    def export_pdf_with_annotations(self):
        """Writes automated remarks and user comments into a copy of the PDF as annotations."""
        if not self.current_pdf_path:
            MessageBox.warning(self, t("common.warning"), t("main.no_doc_to_export"))
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, t("main.save_annotated_pdf"),
            f"{t('main.annotated_prefix')}{os.path.basename(self.current_pdf_path)}",
            t("common.pdf_filter"),
        )

        if not save_path:
            return

        try:
            doc = fitz.open(self.current_pdf_path)

            errors_do_zapisu = self.manager.get_errors(self.current_pdf_path)

            for err in errors_do_zapisu:
                try:
                    page_num = int(err.get("page", err.get("strona", 1)))
                    if 0 <= page_num < len(doc):
                        page = doc[page_num]
                        coords = err.get("coords", err.get("wspolrzedne", {}))

                        x = float(coords.get("x", 0))
                        y = float(coords.get("y", 0))
                        w = float(coords.get("w", 0))
                        h = float(coords.get("h", 0))

                        kat = str(err.get("category", err.get("kategoria", t("main.annot_default_category"))))
                        msg = str(err.get("comment", err.get("komentarz", "")))
                        txt = str(err.get("found_text", err.get("znaleziony_tekst", "")))
                        opis = f"[{kat}]\n{msg}\n\n{t('main.annot_text', text=txt)}"

                        if w > 0 and h > 0:
                            rect = fitz.Rect(x, y, x + w, y + h)
                            hl = page.add_highlight_annot(rect)
                            hl.set_colors(stroke=(1.0, 0.85, 0.85))
                            hl.set_opacity(0.6)
                            hl.set_info({"title": t("main.annot_verification"), "content": opis})
                            hl.update()
                        else:
                            point = fitz.Point(x, y - 15)
                            annot = page.add_text_annot(point, opis, icon="Comment")
                            annot.set_colors(stroke=(1.0, 0.7, 0.7))
                            annot.set_info({"title": t("main.annot_verification")})
                            annot.update()
                except Exception:
                    logger.exception("Error exporting an automatic error annotation")

            saved_comments = self.manager.get_comments(self.current_pdf_path)
            for notatka in saved_comments:
                try:
                    page_idx = int(notatka.get("strona", 1))
                    if 0 <= page_idx < len(doc):
                        page = doc[page_idx]
                        coords = notatka.get("wspolrzedne", {})
                        x = float(coords.get("x", 0))
                        y = float(coords.get("y", 0))
                        w = float(coords.get("w", 0))
                        h = float(coords.get("h", 0))
                        tresc_komentarza = notatka.get("tekst_komentarza", "")

                        if w > 0 and h > 0:
                            rect = fitz.Rect(x, y, x + w, y + h)
                            hl = page.add_highlight_annot(rect)
                            hl.set_colors(stroke=(0.85, 0.92, 1.0))
                            hl.set_opacity(0.5)
                            hl.set_info({"title": t("main.annot_my_comment"), "content": tresc_komentarza})
                            hl.update()
                        else:
                            point = fitz.Point(x, y - 15)
                            annot = page.add_text_annot(point, tresc_komentarza, icon="Note")
                            annot.set_colors(stroke=(0.2, 0.6, 1.0))
                            annot.set_info({"title": t("main.annot_my_comment")})
                            annot.update()
                except Exception:
                    logger.exception("Error exporting a user comment annotation")

            doc.save(save_path)
            doc.close()
            MessageBox.information(self, t("common.success"), t("main.export_saved", path=save_path))

        except Exception as e:
            logger.exception("PDF export failed")
            MessageBox.critical(self, t("common.error"), t("main.export_error", error=str(e)))

    def save_custom_comment(self, comment_data):
        """Passes a newly created comment over to the persistence layer."""
        if self.current_pdf_path:
            self.manager.save_comment(self.current_pdf_path, comment_data)

    def load_custom_comments(self):
        """Clears all comment visuals and re-paints the saved ones for the current file."""
        self.pdf_view.clear_comments()
        if not self.current_pdf_path:
            return

        saved_comments = self.manager.get_comments(self.current_pdf_path)
        for c_data in saved_comments:
            coords = c_data.get("wspolrzedne", {})
            if coords.get("w", 0) > 0:
                box = HighlightBox(c_data, self.pdf_view.viewport())
                box.is_error = False
                box.setStyleSheet(styles.HIGHLIGHT_BOX_CUSTOM_COMMENT_STYLE)
                self.pdf_view.highlight_boxes.append(box)

            marker = CommentMarker(c_data, self.pdf_view.viewport())
            self.pdf_view.comment_markers.append(marker)

        self.pdf_view.update_markers_pos()

    def generate_detailed_report(self):
        """Builds a standalone multi-page PDF report with the content grade, image checks
        and sentence statistics."""

        LANG_DICT = {
            "pl": {
                "yes_upper": "TAK", "no_upper": "NIE", "error": "Błąd", "success": "Sukces",
                "warning": "Ostrzeżenie", "unknown_fig": "Nieznany rysunek", "no_format": "Brak formatu",
                "no_title": "Brak tytułu", "panel_pts": "pkt", "panel_fig_prefix": "Rys.",
                "rep_no_data_warn": "Brak danych szczegółowej analizy merytorycznej dla tego dokumentu.",
                "rep_file_prefix": "Raport_Merytoryczny_", "rep_dialog_title": "Zapisz Raport Szczegółowy",
                "rep_main_title": "Szczegółowy Raport Analizy Merytorycznej", "rep_doc_label": "Dokument:",
                "rep_eval_title": "Ogólna ocena merytoryczna", "rep_score_lbl": "Wynik punktowy:",
                "rep_off_topic_lbl": "Podrozdziały poza tematem:", "rep_off_topic_ident": "Zidentyfikowane sekcje niezgodne z celem pracy:",
                "rep_theory_title": "Weryfikacja merytoryczna rozdziału teoretycznego", "rep_chapter_analyzed": "Analizowany rozdział:",
                "rep_completion_lvl": "Poziom realizacji wytycznych:", "rep_crit_1": "Analiza i ocena istniejących rozwiązań:",
                "rep_crit_2": "Wskazanie luki badawczej lub problemu naukowego:", "rep_crit_3": "Synteza i krytyczne porównanie metod:",
                "rep_ai_eval_title": "Ogólna ocena merytoryczna (AI)", "rep_skipped_fast": "Analiza została pominięta (wybrano Tryb Szybki).",
                "rep_img_title": "Analiza spójności grafik i wykresów (AI)", "rep_img_total": "Wszystkich zweryfikowanych rysunków:",
                "rep_img_bad": "Rysunki z błędnym opisem w tekście:", "rep_img_good": "Rysunki poprawne:",
                "rep_raster_ident": "Zidentyfikowane grafiki rastrowe podlegające badaniu:", "rep_img_details": "Lista szczegółowa rozbieżności:",
                "rep_qual_title": "Ocena jakości obrazów (DPI i czytelność)", "rep_qual_all_ok": "Wszystkie obrazy mają odpowiednią jakość i czytelność.",
                "rep_qual_err_1": "Wykryto problemy z jakością w", "rep_qual_err_2": "obrazach:", "rep_format_lbl": "Format:",
                "rep_fonts_title": "Spójność czcionek na obrazach", "rep_fonts_all_ok": "Brak wykrytych problemów ze spójnością czcionek na rysunkach.",
                "rep_fonts_err_1": "Wykryto problemy z czcionkami w", "rep_fonts_err_2": "elementach:",
                "rep_img_skip_title": "Ocena jakości obrazów i czcionek", "rep_img_skip_desc": "Analiza została pominięta na życzenie użytkownika lub dokument nie zawiera grafik.",
                "rep_stats_title": "Analiza statystyczna struktury zdań", "rep_stats_desc": "Struktura gramatyczna i stylistyczna badanej pracy dyplomowej:",
                "rep_active_lbl": "Zdania w stronie czynnej:", "rep_active_desc": "Zalecana forma wypowiedzi w tekstach naukowych podnosząca dynamikę wywodu.",
                "rep_passive_lbl": "Zdania w stronie biernej:", "rep_passive_desc": "Stosowana przy opisie procedur badawczych oraz stanu wiedzy.",
                "rep_verbless_lbl": "Równoważniki zdań:", "rep_verbless_desc": "Konstrukcje bezorzecznikowe, dopuszczalne głównie w nagłówkach i spisach.",
                "rep_stats_no_data": "Brak dostępnych danych statystycznych (uruchom analizę w Trybie Dokładnym).",
                "rep_footer_date": "Data:", "rep_success_saved": "Raport został zapisany pomyślnie:\n{}", "rep_err_gen": "Błąd podczas generowania raportu:\n{}"
            },
            "en": {
                "yes_upper": "YES", "no_upper": "NO", "error": "Error", "success": "Success",
                "warning": "Warning", "unknown_fig": "Unknown figure", "no_format": "No format",
                "no_title": "No title", "panel_pts": "pts", "panel_fig_prefix": "Fig.",
                "rep_no_data_warn": "No detailed substantive analysis data for this document.",
                "rep_file_prefix": "Content_Report_", "rep_dialog_title": "Save Detailed Report",
                "rep_main_title": "Detailed Content Analysis Report", "rep_doc_label": "Document:",
                "rep_eval_title": "Overall Content Evaluation", "rep_score_lbl": "Score:",
                "rep_off_topic_lbl": "Off-topic subsections:", "rep_off_topic_ident": "Identified sections irrelevant to the thesis objective:",
                "rep_theory_title": "Theoretical Chapter Verification", "rep_chapter_analyzed": "Analyzed chapter:",
                "rep_completion_lvl": "Guideline completion level:", "rep_crit_1": "Analysis and evaluation of existing solutions:",
                "rep_crit_2": "Identification of research gap or problem:", "rep_crit_3": "Synthesis and critical comparison of methods:",
                "rep_ai_eval_title": "Overall Content Evaluation (AI)", "rep_skipped_fast": "Analysis skipped (Fast Mode selected).",
                "rep_img_title": "Graphics and Charts Consistency Analysis (AI)", "rep_img_total": "Total verified figures:",
                "rep_img_bad": "Figures with incorrect textual description:", "rep_img_good": "Correct figures:",
                "rep_raster_ident": "Identified raster graphics subject to analysis:", "rep_img_details": "Detailed list of discrepancies:",
                "rep_qual_title": "Image Quality Assessment (DPI & Legibility)", "rep_qual_all_ok": "All images have adequate quality and legibility.",
                "rep_qual_err_1": "Quality issues detected in", "rep_qual_err_2": "images:", "rep_format_lbl": "Format:",
                "rep_fonts_title": "Font Consistency in Images", "rep_fonts_all_ok": "No font consistency issues detected in figures.",
                "rep_fonts_err_1": "Font issues detected in", "rep_fonts_err_2": "elements:",
                "rep_img_skip_title": "Image Quality and Fonts Assessment", "rep_img_skip_desc": "Analysis skipped by user request or document contains no graphics.",
                "rep_stats_title": "Sentence Structure Statistical Analysis", "rep_stats_desc": "Grammatical and stylistic structure of the analyzed thesis:",
                "rep_active_lbl": "Active voice sentences:", "rep_active_desc": "Recommended form of expression in academic texts, enhancing narrative dynamics.",
                "rep_passive_lbl": "Passive voice sentences:", "rep_passive_desc": "Used when describing research procedures and state of knowledge.",
                "rep_verbless_lbl": "Sentence equivalents:", "rep_verbless_desc": "Verbless constructions, acceptable mainly in headers and lists.",
                "rep_stats_no_data": "No statistical data available (run analysis in Detailed Mode).",
                "rep_footer_date": "Date:", "rep_success_saved": "Report saved successfully:\n{}", "rep_err_gen": "Error during report generation:\n{}"
            }
        }

        report_data = None
        if self.current_pdf_path:
            for p in self.manager.data.get("documents", []):
                if p.get("local_path") == self.current_pdf_path:
                    report_data = p.get("sota_result")
                    break

        lang = report_data.get("language", "pl") if report_data else "pl"
        t = LANG_DICT.get(lang, LANG_DICT["pl"])

        if not report_data:
            MessageBox.warning(self, t.get("warning", "Ostrzeżenie"), t["rep_no_data_warn"])
            return

        default_name = f"{t['rep_file_prefix']}{os.path.basename(self.current_pdf_path)}"
        save_path, _ = QFileDialog.getSaveFileName(self, t["rep_dialog_title"], default_name, "Pliki PDF (*.pdf)")

        if not save_path:
            return

        try:
            report_pdf = fitz.open()
            page = report_pdf.new_page()

            font_path = resource_path(os.path.join("ui", "assets", "Roboto-Regular.ttf"))
            font_bold_path = resource_path(os.path.join("ui", "assets", "Roboto-Bold.ttf"))

            use_roboto = os.path.exists(font_path) and os.path.exists(font_bold_path)
            if use_roboto:
                f_main, f_bold = "roboto", "roboto-bold"
            else:
                f_main, f_bold = "helv", "hebo"

            def setup_page_fonts(p):
                if use_roboto:
                    p.insert_font(fontname="roboto", fontfile=font_path, encoding=0)
                    p.insert_font(fontname="roboto-bold", fontfile=font_bold_path, encoding=0)

            setup_page_fonts(page)

            pos_y = 50
            margin = 50

            def check_new_page(y_coord, pdf_doc, current_page):
                if y_coord > 750:
                    new_p = pdf_doc.new_page()
                    setup_page_fonts(new_p)
                    return 50, new_p
                return y_coord, current_page

            def wrap_text(text, max_len=90):
                words = text.split()
                lines = []
                current_line = ""
                for word in words:
                    if len(current_line) + len(word) + 1 <= max_len:
                        current_line += (word + " ")
                    else:
                        lines.append(current_line.strip())
                        current_line = word + " "
                if current_line:
                    lines.append(current_line.strip())
                return lines

            page.insert_text((margin, pos_y), t["rep_main_title"],
                             fontsize=22, fontname=f_bold, color=(0.13, 0.58, 0.95))
            pos_y += 45
            page.insert_text((margin, pos_y), f"{t['rep_doc_label']} {os.path.basename(self.current_pdf_path)}",
                             fontsize=12, fontname=f_main, color=(0.2, 0.2, 0.2))
            pos_y += 40

            content_grade = report_data.get("content_grade")
            has_llm_data = content_grade is not None

            if has_llm_data:
                if isinstance(content_grade, dict):
                    grade = content_grade.get("grade", 0)
                    max_g = content_grade.get("max_grade", 100)
                    off_topic = content_grade.get("off_topic_sections", 0)
                    p_off = content_grade.get("p_off", 0)
                    off_topic_headings = content_grade.get("off_topic_headings", [])
                else:
                    grade = content_grade
                    max_g = 100
                    off_topic = 0
                    p_off = 0
                    off_topic_headings = []

                page.insert_text((margin, pos_y), t["rep_eval_title"],
                                 fontsize=14, fontname=f_bold)
                pos_y += 25
                page.insert_text((margin, pos_y), f"{t['rep_score_lbl']} {grade} / {max_g} {t['panel_pts']}",
                                 fontsize=12, fontname=f_main)
                pos_y += 20
                page.insert_text((margin, pos_y),
                                 f"{t['rep_off_topic_lbl']} {off_topic} ({p_off}%)",
                                 fontsize=11, fontname=f_main)
                pos_y += 25

                if off_topic > 0 and off_topic_headings:
                    page.insert_text((margin, pos_y), t["rep_off_topic_ident"],
                                     fontsize=11, fontname=f_bold, color=(0.86, 0.2, 0.27))
                    pos_y += 18
                    for heading in off_topic_headings:
                        pos_y, page = check_new_page(pos_y, report_pdf, page)
                        wrapped_heading = wrap_text(str(heading), 85)
                        for idx, line in enumerate(wrapped_heading):
                            pos_y, page = check_new_page(pos_y, report_pdf, page)
                            prefix = "- " if idx == 0 else "  "
                            page.insert_text((margin + 15, pos_y), f"{prefix}{line}", fontsize=10, fontname=f_main)
                            pos_y += 14
                    pos_y += 15
                else:
                    pos_y += 15

                pos_y, page = check_new_page(pos_y, report_pdf, page)
                page.insert_text((margin, pos_y), t["rep_theory_title"],
                                 fontsize=14, fontname=f_bold)
                pos_y += 25

                chapter_title = report_data.get("tytul", t["no_title"])
                page.insert_text((margin, pos_y), f"{t['rep_chapter_analyzed']} {chapter_title}",
                                 fontsize=12, fontname=f_main)
                pos_y += 20

                score = report_data.get("ocena", 0)
                page.insert_text((margin, pos_y), f"{t['rep_completion_lvl']} {score}%",
                                 fontsize=12, fontname=f_main)
                pos_y += 30

                criteria = [
                    (t["rep_crit_1"], report_data.get("r1")),
                    (t["rep_crit_2"], report_data.get("r2")),
                    (t["rep_crit_3"], report_data.get("r3")),
                ]

                for label, met in criteria:
                    pos_y, page = check_new_page(pos_y, report_pdf, page)
                    status = t["yes_upper"] if met else t["no_upper"]
                    color = (0.17, 0.62, 0.35) if met else (0.86, 0.2, 0.27)
                    page.insert_text((margin + 20, pos_y), f"{label} {status}",
                                     fontsize=11, fontname=f_bold if met else f_main, color=color)
                    pos_y += 20
            else:
                page.insert_text((margin, pos_y), t["rep_ai_eval_title"],
                                 fontsize=14, fontname=f_bold)
                pos_y += 25
                page.insert_text((margin, pos_y), t["rep_skipped_fast"],
                                 fontsize=11, fontname=f_main, color=(0.5, 0.5, 0.5))
                pos_y += 25

            pos_y, page = check_new_page(pos_y + 15, report_pdf, page)
            img_data = report_data.get("image_analysis", {})
            has_images_checked = img_data.get("total", 0) > 0 if isinstance(img_data, dict) else False

            if has_images_checked:
                page.insert_text((margin, pos_y), t["rep_img_title"],
                                 fontsize=14, fontname=f_bold)
                pos_y += 25

                page.insert_text((margin, pos_y), f"{t['rep_img_total']} {img_data.get('total', 0)}",
                                 fontsize=11, fontname=f_main)
                pos_y += 18

                color_bad = (0.86, 0.2, 0.27) if img_data.get("bad_count", 0) > 0 else (0.2, 0.2, 0.2)
                page.insert_text((margin, pos_y), f"{t['rep_img_bad']} {img_data.get('bad_count', 0)}",
                                 fontsize=11, fontname=f_main, color=color_bad)
                pos_y += 18

                page.insert_text((margin, pos_y), f"{t['rep_img_good']} {img_data.get('good_count', 0)}",
                                 fontsize=11, fontname=f_main, color=(0.17, 0.62, 0.35))
                pos_y += 25

                raster_nums = img_data.get("raster_numbers", img_data.get("image_raster", []))
                if raster_nums:
                    pos_y, page = check_new_page(pos_y, report_pdf, page)
                    wrapped_header = wrap_text(t["rep_raster_ident"], 85)
                    for line in wrapped_header:
                        pos_y, page = check_new_page(pos_y, report_pdf, page)
                        page.insert_text((margin, pos_y), line, fontsize=10, fontname=f_bold, color=(0.05, 0.27, 0.63))
                        pos_y += 14

                    for n in raster_nums:
                        wrapped_item = wrap_text(f"- {t['panel_fig_prefix']} {n}", 85)
                        for line in wrapped_item:
                            pos_y, page = check_new_page(pos_y, report_pdf, page)
                            page.insert_text((margin + 10, pos_y), line, fontsize=10, fontname=f_main, color=(0.1, 0.1, 0.1))
                            pos_y += 14

                    pos_y, page = check_new_page(pos_y, report_pdf, page)
                    pos_y += 10

                if img_data.get("details", []):
                    page.insert_text((margin, pos_y), t["rep_img_details"], fontsize=12, fontname=f_bold)
                    pos_y += 20
                    for line_text in img_data.get("details", []):
                        wrapped_lines = wrap_text(line_text, 90)
                        for idx, chunk in enumerate(wrapped_lines):
                            pos_y, page = check_new_page(pos_y, report_pdf, page)
                            indent = margin + 15 if idx == 0 else margin + 25
                            txt_col = (0, 0, 0) if idx == 0 else (0.4, 0.4, 0.4)
                            page.insert_text((indent, pos_y), chunk, fontsize=10, fontname=f_main, color=txt_col)
                            pos_y += 15
                        pos_y += 4

                pos_y, page = check_new_page(pos_y + 15, report_pdf, page)
                page.insert_text((margin, pos_y), t["rep_qual_title"], fontsize=14, fontname=f_bold)
                pos_y += 25

                quality_errors = report_data.get("jakosc_obrazkow", [])
                if not quality_errors:
                    page.insert_text((margin, pos_y), t["rep_qual_all_ok"],
                                     fontsize=11, fontname=f_main, color=(0.17, 0.62, 0.35))
                    pos_y += 25
                else:
                    page.insert_text((margin, pos_y), f"{t['rep_qual_err_1']} {len(quality_errors)} {t['rep_qual_err_2']}",
                                     fontsize=11, fontname=f_main, color=(0.86, 0.2, 0.27))
                    pos_y += 20
                    for err in quality_errors:
                        pos_y, page = check_new_page(pos_y, report_pdf, page)
                        rys = err.get("rysunek", t["unknown_fig"])
                        fmt = err.get("format", t["no_format"])
                        powody = err.get("powody_odrzucenia", [])

                        page.insert_text((margin + 15, pos_y), f"{rys} ({t['rep_format_lbl']} {fmt}):", fontsize=11, fontname=f_bold)
                        pos_y += 16
                        for powod in powody:
                            wrapped_powod = wrap_text(powod, 85)
                            for idx, line in enumerate(wrapped_powod):
                                pos_y, page = check_new_page(pos_y, report_pdf, page)
                                prefix = "- " if idx == 0 else "  "
                                page.insert_text((margin + 25, pos_y), f"{prefix}{line}", fontsize=10, fontname=f_main)
                                pos_y += 14
                        pos_y += 5

                pos_y, page = check_new_page(pos_y + 15, report_pdf, page)
                page.insert_text((margin, pos_y), t["rep_fonts_title"], fontsize=14, fontname=f_bold)
                pos_y += 25

                font_errors = report_data.get("czcionki_obrazkow", [])
                if not font_errors:
                    page.insert_text((margin, pos_y), t["rep_fonts_all_ok"],
                                     fontsize=11, fontname=f_main, color=(0.17, 0.62, 0.35))
                    pos_y += 25
                else:
                    page.insert_text((margin, pos_y), f"{t['rep_fonts_err_1']} {len(font_errors)} {t['rep_fonts_err_2']}",
                                     fontsize=11, fontname=f_main, color=(0.86, 0.2, 0.27))
                    pos_y += 20
                    for err in font_errors:
                        if isinstance(err, dict):
                            pos_y, page = check_new_page(pos_y, report_pdf, page)
                            rys = err.get("rysunek", t["unknown_fig"])
                            errors = err.get("errors", err.get("powody_odrzucenia", [str(err)]))

                            page.insert_text((margin + 15, pos_y), f"{rys}:", fontsize=11, fontname=f_bold)
                            pos_y += 16
                            for b in errors:
                                wrapped_blad = wrap_text(str(b), 85)
                                for idx, line in enumerate(wrapped_blad):
                                    pos_y, page = check_new_page(pos_y, report_pdf, page)
                                    prefix = "- " if idx == 0 else "  "
                                    page.insert_text((margin + 25, pos_y), f"{prefix}{line}", fontsize=10, fontname=f_main)
                                    pos_y += 14
                            pos_y += 5
                        else:
                            wrapped_err = wrap_text(str(err), 85)
                            for idx, line in enumerate(wrapped_err):
                                pos_y, page = check_new_page(pos_y, report_pdf, page)
                                prefix = "- " if idx == 0 else "  "
                                page.insert_text((margin + 15, pos_y), f"{prefix}{line}", fontsize=10, fontname=f_main)
                                pos_y += 14
                            pos_y += 5
            else:
                pos_y, page = check_new_page(pos_y + 15, report_pdf, page)
                page.insert_text((margin, pos_y), t["rep_img_skip_title"], fontsize=14, fontname=f_bold)
                pos_y += 25
                page.insert_text((margin, pos_y), t["rep_img_skip_desc"],
                                 fontsize=11, fontname=f_main, color=(0.5, 0.5, 0.5))
                pos_y += 25

            stats_data = report_data.get("statystyki_zdan")

            if stats_data:
                pos_y, page = check_new_page(pos_y + 15, report_pdf, page)
                page.insert_text((margin, pos_y), t["rep_stats_title"], fontsize=14, fontname=f_bold)
                pos_y += 22
                page.insert_text((margin + 15, pos_y), t["rep_stats_desc"], fontsize=10, fontname=f_main, color=(0.3, 0.3, 0.3))
                pos_y += 18

                struktura_zdan = [
                    (f"{t['rep_active_lbl']} {stats_data.get('active_ratio', '0%')}", t["rep_active_desc"]),
                    (f"{t['rep_passive_lbl']} {stats_data.get('passive_ratio', '0%')}", t["rep_passive_desc"]),
                    (f"{t['rep_verbless_lbl']} {stats_data.get('verbless_ratio', '0%')}", t["rep_verbless_desc"]),
                ]

                for label, opis in struktura_zdan:
                    pos_y, page = check_new_page(pos_y, report_pdf, page)
                    page.insert_text((margin + 15, pos_y), label, fontsize=10, fontname=f_bold)
                    pos_y += 14
                    pos_y, page = check_new_page(pos_y, report_pdf, page)
                    page.insert_text((margin + 25, pos_y), opis, fontsize=9, fontname=f_main, color=(0.4, 0.4, 0.4))
                    pos_y += 16
            else:
                pos_y, page = check_new_page(pos_y + 15, report_pdf, page)
                page.insert_text((margin, pos_y), t["rep_stats_title"], fontsize=14, fontname=f_bold)
                pos_y += 22
                page.insert_text((margin + 15, pos_y), t["rep_stats_no_data"], fontsize=10, fontname=f_main, color=(0.5, 0.5, 0.5))
                pos_y += 20

            # Footer at the bottom of the current page (new page only when there is no room).
            if pos_y > 790:
                page = report_pdf.new_page()
                setup_page_fonts(page)
            page.insert_text((margin, 820), f"{t['rep_footer_date']} {datetime.date.today()}",
                             fontsize=9, fontname=f_main, color=(0.5, 0.5, 0.5))

            report_pdf.save(save_path)
            report_pdf.close()

            MessageBox.information(self, t["success"], t["rep_success_saved"].format(save_path))

        except Exception as e:
            logger.exception("Report generation failed")
            MessageBox.critical(self, t["error"], t["rep_err_gen"].format(str(e)))

    def delete_document(self, path):
        """Removes a document from the index and refreshes the start page."""
        reply = MessageBox.question(
            self, t("main.confirm_title"),
            t("main.confirm_delete"),
            MessageBox.Yes | MessageBox.No, MessageBox.No,
        )

        if reply == MessageBox.Yes:
            self.manager.delete_document(path)
            self.refresh_file_list()

    def refresh_file_list(self):
        """Synchronizes the start page list with the data store managed by SavingFiles."""
        pliki = self.manager.data.get("documents", [])
        self.start_page.render_doc_list(pliki)

    def load_ai_analysis(self):
        """Loads the saved evaluation for the current file into the sidebar panel."""
        if not self.current_pdf_path:
            return

        try:
            report_data = None
            for p in self.manager.data.get("documents", []):
                if p.get("local_path") == self.current_pdf_path:
                    report_data = p.get("sota_result")
                    break
            self.update_report_panel(report_data)

        except Exception:
            logger.exception("Error while loading the saved analysis")

    def load_pdf(self, path):
        """Loads a PDF into the QPdfDocument, sets tracking variables and refreshes the view."""
        if not path or not os.path.exists(path):
            MessageBox.critical(self, t("common.error"), t("main.file_not_found", path=path))
            return

        self.current_pdf_path = path
        self.document.load(path)

        if self.document.status() == QPdfDocument.Status.Ready:
            self.title_label.setText(os.path.basename(path))
            self.total_pages_label.setText(f" / {self.document.pageCount()}")
            self.page_input.setText("1")

            self.pdf_view.clear_markers()
            self.pdf_view.clear_comments()
            self.generate_thumbnails()
            self.load_custom_comments()

            logger.info("Loaded PDF: %s", os.path.basename(path))
        else:
            MessageBox.critical(self, t("common.error"), t("main.pdf_init_failed"))