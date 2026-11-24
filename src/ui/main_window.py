import logging
import os
import threading

import fitz
from PySide6.QtCore import QEvent, QMargins, QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPalette, QPixmap, QShortcut
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from common.path import resource_path

from common.findings import finding_kind

from . import icons, motion, report_panel, report_pdf, styles
from .i18n import current_locale, language_signals, set_locale, t
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
        available = self.screen().availableGeometry()
        self.resize(min(1440, available.width()), min(860, available.height()))
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
        self.start_page.commandsRequested.connect(self.open_command_menu)
        self.start_page.prefetchRequested.connect(self.prefetch_document)

        self.start_page.deleteRequested.connect(self.delete_document)
        self.stack.addWidget(self.start_page)

        self.reader_container = QWidget()
        self.setup_reader_ui()
        self.stack.addWidget(self.reader_container)

        self.refresh_file_list()
        self.overlay = QFrame(self)
        self.overlay.setStyleSheet(styles.OVERLAY_STYLE)
        self.overlay.hide()

        self.toasts = motion.ToastHost(self)
        self._last_deleted = None
        self._palette = None
        self._setup_shortcuts()
        QApplication.instance().installEventFilter(self)
        self._focus_filter = motion.KeyboardFocusFilter(self)
        QApplication.instance().installEventFilter(self._focus_filter)
        self._report_ready = True

        language_signals.changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    # ------------------------------------------------------------ shortcuts and command menu
    def _setup_shortcuts(self):
        """Keyboard shortcuts of the whole window. The same keys are shown in tooltips and in the command menu."""
        def bind(key, callback):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(callback)
            return shortcut

        in_reader = lambda fn: (lambda: fn() if self.stack.currentIndex() == 1 else None)
        bind("Ctrl+K", self.open_command_menu)
        bind("Ctrl+O", self.open_file_dialog)
        bind("Ctrl+,", self.start_page.open_settings)
        bind("Ctrl+Shift+L", self.toggle_language)
        bind("Ctrl+Z", self.undo_delete)
        bind("Alt+Left", in_reader(self.go_back))
        bind("Ctrl+=", in_reader(self.zoom_in))
        bind("Ctrl++", in_reader(self.zoom_in))
        bind("Ctrl+-", in_reader(self.zoom_out))
        bind("Ctrl+G", in_reader(self.focus_page_input))
        bind("Ctrl+E", in_reader(self.export_pdf_with_annotations))
        bind("Ctrl+0", in_reader(self.zoom_reset))
        bind("Esc", in_reader(self._escape_back))

    def eventFilter(self, obj, event):
        """The side 'back' button of a mouse goes back from the reader, as in a browser."""
        if (event.type() == QEvent.KeyPress and obj in getattr(self, "thumb_buttons", ())
                and self._thumb_key(event)):
            return True
        if (event.type() == QEvent.MouseButtonPress and event.button() == Qt.BackButton
                and self.isActiveWindow() and self.stack.currentIndex() == 1):
            self.go_back()
            return True
        return super().eventFilter(obj, event)

    def _escape_back(self):
        """Esc goes back, unless it is meant for a text field (clearing or leaving it)."""
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit) or focus.__class__.__name__ in ("QPlainTextEdit", "QTextEdit"):
            focus.clearFocus()
            return
        self.go_back()

    def go_back(self):
        self._remember_view()
        motion.fade_to(self.stack, 0)

    def _remember_view(self):
        """Where the reader is (page and zoom), kept with the document for the next time it is opened."""
        if self.current_pdf_path and self.document.status() == QPdfDocument.Status.Ready:
            self.manager.set_view_state(
                self.current_pdf_path, self.pdf_view.pageNavigator().currentPage(), self.pdf_view.zoomFactor())

    def closeEvent(self, event):
        self._remember_view()
        super().closeEvent(event)

    def prefetch_document(self, path):
        """The pointer rested on a document: read its start from disk in the background so that opening it finds the
        file in the system cache."""
        def warm():
            try:
                with open(path, "rb") as handle:
                    while handle.read(1 << 20) and handle.tell() < (16 << 20):
                        pass
            except OSError:
                pass
        threading.Thread(target=warm, daemon=True).start()

    def focus_page_input(self):
        self.page_input.setFocus()
        self.page_input.selectAll()

    def toggle_language(self):
        set_locale("pl" if current_locale() == "en" else "en")

    def open_command_menu(self):
        if self._palette is not None and self._palette.isVisible():
            return
        commands = [
            motion.Command(t("palette.open_file"), self.open_file_dialog, "Ctrl+O", "pdf plik file add dodaj"),
            motion.Command(t("palette.settings"), self.start_page.open_settings, "Ctrl+,", "config ustawienia"),
            motion.Command(t("palette.language"), self.toggle_language, "Ctrl+Shift+L", "język language pl en"),
        ]
        if self.stack.currentIndex() == 1:
            commands += [
                motion.Command(t("palette.back"), self.go_back, "Alt+Left", "wróć back lista"),
                motion.Command(t("palette.go_to_page"), self.focus_page_input, "Ctrl+G", "strona page"),
                motion.Command(t("palette.zoom_in"), self.zoom_in, "Ctrl+=", "zoom powiększ"),
                motion.Command(t("palette.zoom_out"), self.zoom_out, "Ctrl+-", "zoom pomniejsz"),
                motion.Command(t("palette.export"), self.export_pdf_with_annotations, "Ctrl+E", "export eksport pdf"),
                motion.Command(t("palette.report"), lambda: send_report(self, self.current_pdf_path), None, "błąd bug"),
                motion.Command(t("palette.logs"), self.show_log_window, None, "logi logs"),
            ]
        if self._last_deleted:
            commands.insert(0, motion.Command(t("palette.undo"), self.undo_delete, "Ctrl+Z", "cofnij undo"))
        for doc in self.manager.data.get("documents", [])[:30]:
            path = doc.get("local_path", "")
            name = doc.get("file_name", os.path.basename(path))
            commands.append(motion.Command(t("palette.open_doc", name=name),
                                           lambda p=path: self.open_existing_file(p), None, name))
        self._palette = motion.CommandPalette(self, commands)
        self._palette.exec()

    def retranslate_ui(self, *_):
        """Re-apply all window texts after the UI language changes."""
        self.setWindowTitle(t("main.window_title"))
        self.v_label.setText(t("main.verification"))
        self.back_btn.setText("  " + t("main.back"))
        self.back_btn.setToolTip(motion.with_hint(t("main.back_tooltip"), "Alt+Left"))
        self.page_input.setAccessibleName(t("main.page_number"))
        self.page_input.setToolTip(motion.with_hint(t("main.page_number"), "Ctrl+G"))
        self.export_btn.setToolTip(motion.with_hint(t("main.export_pdf"), "Ctrl+E"))
        self.commands_btn.setText(t("palette.button"))
        self.commands_btn.setToolTip(motion.with_hint(t("palette.button"), "Ctrl+K"))
        self.btn_zoom_in.setToolTip(motion.with_hint(t("main.zoom_in"), "Ctrl+="))
        self.btn_zoom_in.setAccessibleName(t("main.zoom_in"))
        self.btn_zoom_out.setToolTip(motion.with_hint(t("main.zoom_out"), "Ctrl+-"))
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
        if hasattr(self, "toasts"):
            self.toasts.reposition()

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

            # Show the reader at once. The saved report is built right after; only when that takes longer than
            # 150 ms does a skeleton appear (a loader flashing for 40 ms looks like a glitch).
            self._report_ready = False
            QTimer.singleShot(150, self._show_report_skeleton)
            motion.fade_to(self.stack, 1)
            QTimer.singleShot(0, self._build_report_now)
            self._restore_view(path)

    def _show_report_skeleton(self):
        if not self._report_ready:
            self.report_scroll.setWidget(motion.skeleton_report())

    def _build_report_now(self):
        self.load_ai_analysis()
        self._report_ready = True

    def _restore_view(self, path):
        """Continue where the reader was left: the page and the zoom saved with the document."""
        state = self.manager.get_view_state(path)
        if not state:
            return
        zoom = float(state.get("zoom", 1.0))
        page = int(state.get("page", 0))

        def apply():
            if zoom and abs(zoom - self.pdf_view.zoomFactor()) > 0.001:
                self.pdf_view.setZoomFactor(zoom)
                self.zoom_label.setText(f"{int(zoom * 100)}%")
            if 0 < page < self.document.pageCount():
                self.pdf_view.pageNavigator().jump(page, QPointF(0, 0), self.pdf_view.zoomFactor())

        QTimer.singleShot(60, apply)

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
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setStyleSheet(
            styles.ICON_BUTTON_STYLE
            + f"QPushButton {{ padding: 0 12px 0 8px; font-size: 14px; font-weight: 500; color: {styles.TEXT_3}; }}"
        )
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.setFixedHeight(44)
        self.back_slop = motion.HitSlop(toolbar, self.back_btn)
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

        for label in (self.page_input, self.total_pages_label, self.zoom_label):
            motion.tabular(label)

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

        self.commands_btn = QPushButton()
        self.commands_btn.setIcon(icons.icon("search", styles.TEXT_3, 16, 2.25))
        self.commands_btn.setIconSize(QSize(16, 16))
        self.commands_btn.setFixedHeight(40)
        self.commands_btn.setCursor(Qt.PointingHandCursor)
        self.commands_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        self.commands_btn.clicked.connect(self.open_command_menu)
        l.addWidget(self.commands_btn)

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

            motion.fade_to(self.stack, 1)

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

            failure = report_data.get("analysis_error")
            if failure:
                MessageBox.warning(self, t("analysis.ai_failed_title"),
                                   t("analysis.ai_failed_text", error=failure.get("error", "?")))

    def generate_thumbnails(self):
        """Creates a button for every page at once, each with a blurred low-resolution preview, and then
        renders the sharp previews a few at a time while the window stays responsive."""
        for btn in self.thumb_buttons:
            self.thumb_group.removeButton(btn)
        self.thumb_buttons = []
        for i in reversed(range(self.thumb_layout.count())):
            w = self.thumb_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        self._thumb_generation = getattr(self, "_thumb_generation", 0) + 1
        self._thumb_queue = []
        thumb_w = 118
        for i in range(self.document.pageCount()):
            size_pt = self.document.pagePointSize(i)
            ratio = (size_pt.height() / size_pt.width()) if size_pt.width() > 0 else 1.414
            thumb_h = max(40, int(round(thumb_w * ratio)))

            btn = QToolButton()
            btn.setCheckable(True)
            btn.setText(str(i + 1))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setIcon(self._page_pixmap(i, thumb_w, thumb_h, blurred=True))
            btn.setIconSize(QSize(thumb_w, thumb_h))
            btn.setAccessibleName(t("main.page_n", n=i + 1))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(styles.THUMB_BUTTON_STYLE)
            motion.tabular(btn)
            btn.clicked.connect(
                lambda chk, idx=i: self.pdf_view.pageNavigator().jump(
                    idx, QPointF(0, 0), self.pdf_view.zoomFactor()
                )
            )
            self.thumb_group.addButton(btn)
            self.thumb_buttons.append(btn)
            self.thumb_layout.addWidget(btn, alignment=Qt.AlignHCenter)
            self._thumb_queue.append((i, thumb_w, thumb_h))

        if self.thumb_buttons:
            self.thumb_buttons[0].setChecked(True)
            self._set_thumb_tab_stop(0)
        QTimer.singleShot(0, lambda g=self._thumb_generation: self._render_thumbnails(g))

    def _page_pixmap(self, index, width, height, blurred=False):
        """Preview of one page. The blurred version is rendered tiny and scaled up smoothly: it shows the
        page's layout and tones right away, as a placeholder until the sharp one is ready."""
        render_w = max(8, width // 8) if blurred else width
        render_h = max(8, height // 8) if blurred else height
        image = self.document.render(index, QSize(render_w, render_h))
        pixmap = QPixmap.fromImage(image)
        if blurred:
            pixmap = pixmap.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(pixmap)
        painter.setPen(QColor(styles.BORDER_STRONG))
        painter.drawRect(0, 0, pixmap.width() - 1, pixmap.height() - 1)
        painter.end()
        return pixmap

    def _render_thumbnails(self, generation, batch=3):
        """Renders the next few sharp previews; stops when another document has been opened meanwhile."""
        if generation != self._thumb_generation:
            return
        for _ in range(batch):
            if not self._thumb_queue:
                return
            index, width, height = self._thumb_queue.pop(0)
            if index < len(self.thumb_buttons):
                self.thumb_buttons[index].setIcon(self._page_pixmap(index, width, height))
        QTimer.singleShot(0, lambda: self._render_thumbnails(generation))

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
        errors = self.manager.get_errors(self.current_pdf_path) if self.current_pdf_path else None
        content, self.raport_btn = report_panel.build_report_panel(report_data, self.generate_detailed_report,
                                                                   errors, self._go_to_page)
        self.report_scroll.setWidget(content)

    def _go_to_page(self, index):
        """Shows the page (counted from 0, as in the findings) in the viewer."""
        self.pdf_view.pageNavigator().jump(index, QPointF(0, 0), self.pdf_view.zoomFactor())

    ZOOM_DETENTS = (1.0, 1.5, 2.0)

    def _set_zoom(self, factor):
        """Zoom with magnetic detents: within 3% of 100%, 150% or 200% it lands exactly on it, so the usual sizes
        are easy to come back to."""
        for detent in self.ZOOM_DETENTS:
            if abs(factor - detent) <= 0.03 * detent:
                factor = detent
        self.pdf_view.setZoomFactor(factor)
        self.zoom_label.setText(f"{int(round(self.pdf_view.zoomFactor() * 100))}%")

    def zoom_in(self):
        """Increases the zoom of the document viewport."""
        self._set_zoom(self.pdf_view.zoomFactor() * 1.1)

    def zoom_out(self):
        """Decreases the zoom of the document viewport."""
        self._set_zoom(self.pdf_view.zoomFactor() / 1.1)

    def zoom_reset(self):
        self._set_zoom(1.0)

    def _set_thumb_tab_stop(self, idx, take_focus=False):
        """Roving tabindex: the thumbnail list is a single stop for Tab (the current page); inside it the arrow keys
        move. Fifty pages are no longer fifty presses of Tab."""
        for i, button in enumerate(self.thumb_buttons):
            button.setFocusPolicy(Qt.StrongFocus if i == idx else Qt.NoFocus)
        if take_focus and 0 <= idx < len(self.thumb_buttons):
            self.thumb_buttons[idx].setFocus(Qt.TabFocusReason)

    def _thumb_key(self, event):
        """Arrow keys, Home and End inside the thumbnail list move to another page."""
        key = event.key()
        current = self.pdf_view.pageNavigator().currentPage()
        last = len(self.thumb_buttons) - 1
        target = {Qt.Key_Down: current + 1, Qt.Key_Right: current + 1, Qt.Key_Up: current - 1,
                  Qt.Key_Left: current - 1, Qt.Key_Home: 0, Qt.Key_End: last}.get(key)
        if target is None:
            return False
        target = max(0, min(last, target))
        self.pdf_view.pageNavigator().jump(target, QPointF(0, 0), self.pdf_view.zoomFactor())
        self._set_thumb_tab_stop(target, take_focus=True)
        return True

    def update_page_input(self, idx):
        """Syncs the current page index back to the page box and highlights its thumbnail."""
        self.page_input.setText(str(idx + 1))
        if 0 <= idx < len(self.thumb_buttons):
            self.thumb_buttons[idx].setChecked(True)
            self.thumb_area.ensureWidgetVisible(self.thumb_buttons[idx], 0, 40)
            self._set_thumb_tab_stop(idx)

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
                if finding_kind(err) != "page":
                    continue
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

                        for extra in err.get("extra_rects", []):
                            ep = int(extra.get("page", page_num))
                            c = extra.get("coords", {})
                            if 0 <= ep < len(doc) and c.get("w", 0) > 0:
                                r = fitz.Rect(c["x"], c["y"], c["x"] + c["w"], c["y"] + c["h"])
                                extra_page = doc[ep]    # an annotation only weakly references its page
                                h2 = extra_page.add_highlight_annot(r)
                                h2.set_colors(stroke=(0.95, 0.35, 0.35))
                                h2.set_opacity(0.55)
                                h2.update()
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
                findings=self.manager.get_errors(self.current_pdf_path),
            )
            MessageBox.information(self, texts["success"], texts["rep_success_saved"].format(save_path))

        except Exception as e:
            logger.exception("Report generation failed")
            MessageBox.critical(self, texts["error"], texts["rep_err_gen"].format(str(e)))

    def delete_document(self, path):
        """Removes a document from the list at once (no confirmation) and offers to undo it for a few seconds.
        Only the list entry goes; the PDF file itself is never touched."""
        entry, position = self.manager.take_document(path)
        if entry is None:
            return
        self._last_deleted = (entry, position)
        self.refresh_file_list()
        name = entry.get("file_name", os.path.basename(path))
        self.toasts.show(
            t("toast.deleted", name=name), t("toast.undo"), on_action=self.undo_delete,
            action_hint=motion.shortcut_text("Ctrl+Z"),
            on_expire=lambda e=entry: self._forget_deleted(e),
        )

    def _forget_deleted(self, entry):
        if self._last_deleted and self._last_deleted[0] is entry:
            self._last_deleted = None

    def undo_delete(self):
        """Puts the last removed document back where it was."""
        if not self._last_deleted:
            return
        entry, position = self._last_deleted
        self._last_deleted = None
        self.toasts.dismiss_current()
        self.manager.restore_document(entry, position)
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