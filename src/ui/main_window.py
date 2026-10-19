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

from . import icons, report_panel, report_pdf, styles
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
        """Rebuilds the verification panel (look shared with the detailed PDF report, see ui/report_panel.py)."""
        content, self.raport_btn = report_panel.build_report_panel(report_data, self.generate_detailed_report)
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
                            hl.set_colors(stroke=(0.95, 0.35, 0.35))
                            hl.set_opacity(0.55)
                            hl.set_info({"title": t("main.annot_verification"), "content": opis})
                            hl.update()
                        else:
                            point = fitz.Point(x, y - 15)
                            annot = page.add_text_annot(point, opis, icon="Comment")
                            annot.set_colors(stroke=(0.85, 0.15, 0.15))
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
        """Saves the detailed content analysis report (content grade, image checks, sentence statistics) as a
        designed PDF. The layout lives in ui/report_pdf.py."""
        report_data = None
        if self.current_pdf_path:
            for p in self.manager.data.get("documents", []):
                if p.get("local_path") == self.current_pdf_path:
                    report_data = p.get("sota_result")
                    break

        lang = report_data.get("language", "pl") if report_data else "pl"
        texts = report_pdf.STRINGS.get(lang, report_pdf.STRINGS["pl"])

        if not report_data:
            MessageBox.warning(self, texts["warning"], texts["rep_no_data_warn"])
            return

        default_name = f"{texts['rep_file_prefix']}{os.path.basename(self.current_pdf_path)}"
        save_path, _ = QFileDialog.getSaveFileName(self, texts["rep_dialog_title"], default_name, "Pliki PDF (*.pdf)")

        if not save_path:
            return

        try:
            report_pdf.build_report_pdf(
                report_data,
                os.path.basename(self.current_pdf_path),
                lang,
                save_path,
                font_regular=resource_path(os.path.join("ui", "assets", "Roboto-Regular.ttf")),
                font_bold=resource_path(os.path.join("ui", "assets", "Roboto-Bold.ttf")),
                logo_path=resource_path(os.path.join("ui", "assets", "logo.png")),
            )
            MessageBox.information(self, texts["success"], texts["rep_success_saved"].format(save_path))

        except Exception as e:
            logger.exception("Report generation failed")
            MessageBox.critical(self, texts["error"], texts["rep_err_gen"].format(str(e)))

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