import logging
import os

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from analysis.modules.llm.config import (
    are_ai_models_downloaded,
    download_ai_models_with_progress,
    download_specific_language,
    llm_runtime_available,
    load_config,
    save_config,
)

from . import icons, styles
from .i18n import t
from .message_box import MessageBox

logger = logging.getLogger(__name__)

# key in the user's app_config.json: the requirements file (JSON) used last, offered again next time
LAST_CONFIG_KEY = "last_config_file"



class FileBadge(QFrame):
    removed = Signal()

    def __init__(self, filename, parent=None, *, info_text=None):
        super().__init__(parent)
        self.setObjectName("FileBadge")
        self.setStyleSheet(styles.FILE_BADGE_FRAME)
        self.setFixedHeight(80)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 12, 12)
        layout.setSpacing(14)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(46, 46)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setPixmap(icons.pixmap("json", styles.PRIMARY, 24))
        self.icon_label.setStyleSheet(
            f"background-color: {styles.PRIMARY_50}; border: none; border-radius: 10px;"
        )

        text_container = QWidget()
        text_container.setStyleSheet(styles.FILE_BADGE_INNER_LABELS)
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        self.name_label = QLabel(filename)
        self.name_label.setToolTip(filename)
        self.name_label.setStyleSheet(styles.FILE_BADGE_NAME_LABEL)

        self.info_label = QLabel(info_text or t("analysis.config_info"))
        self.info_label.setStyleSheet(styles.FILE_BADGE_INFO_LABEL)

        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.info_label)

        self.del_btn = QPushButton()
        self.del_btn.setFixedSize(32, 32)
        self.del_btn.setToolTip(t("analysis.delete"))
        self.del_btn.setAccessibleName(t("analysis.delete"))
        self.del_btn.setIcon(icons.icon("trash", styles.TEXT_2, 17))
        self.del_btn.setIconSize(QSize(17, 17))
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setStyleSheet(styles.ICON_BUTTON_STYLE)
        self.del_btn.clicked.connect(self.removed.emit)

        layout.addWidget(self.icon_label)
        layout.addWidget(text_container, 1)
        layout.addWidget(self.del_btn)


class ConfigDropFrame(QFrame):
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
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".json"):
                self._set_drag(True)
                event.acceptProposedAction()
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drag(False)
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            self.fileDropped.emit(file_path)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class PipelineWorker(QThread):
    progress_update = Signal(int, str)
    finished_success = Signal(dict)
    finished_error = Signal(str)

    def __init__(self, pdf_path, config_path, use_llm, language, download_models_flag=False):
        super().__init__()
        self.pdf_path = pdf_path
        self.config_path = config_path
        self.use_llm = use_llm
        self.language = language
        self.download_models_flag = download_models_flag

    def run(self):
        try:
            self.progress_update.emit(5, t("analysis.checking_language"))
            download_specific_language(self.language)

            if self.use_llm and self.download_models_flag:
                download_ai_models_with_progress(self.progress_update.emit)

            self.progress_update.emit(40, t("analysis.starting_engine"))
            from app.entry import run_analysis_for_pdf

            final_report = run_analysis_for_pdf(
                pdf_path=self.pdf_path,
                config_path=self.config_path,
                progress_callback=self.progress_update.emit,
                use_llm=self.use_llm,
                language=self.language,
            )

            report_objects = getattr(final_report, "linguistics_errors", [])
            ui_report = []
            for error in report_objects:
                if isinstance(error, dict):
                    page_nr = error.get("page", error.get("page_number", error.get("page_start", 1)))
                    bbox = error.get("bbox", error.get("bounding_box", None))
                    single_x = error.get("x", None)
                    single_y = error.get("y", None)
                    err_coord = error.get("error_coordinate", None)
                    category = error.get("category", error.get("ruleId", "Błąd językowy"))
                    text = error.get("content", error.get("text", error.get("matched_text", "[Brak tekstu]")))
                    comment = error.get("message", error.get("msg", error.get("comments", "Znaleziono błąd.")))
                else:
                    page_nr = getattr(error, "page", getattr(error, "page_number", getattr(error, "page_start", 1)))
                    bbox = getattr(error, "bbox", getattr(error, "bounding_box", None))
                    single_x = getattr(error, "x", None)
                    single_y = getattr(error, "y", None)
                    err_coord = getattr(error, "error_coordinate", None)
                    category = getattr(error, "category", getattr(error, "ruleId", "Błąd językowy"))
                    text = getattr(error, "content", getattr(error, "text", getattr(error, "matched_text", "[Brak tekstu]")))
                    comment = getattr(error, "message", getattr(error, "msg", getattr(error, "comments", "Znaleziono błąd.")))

                if not isinstance(page_nr, int) or page_nr <= 0:
                    page_nr = 1

                x, y, w, h = 50.0, 50.0, 20.0, 20.0
                if err_coord and isinstance(err_coord, list) and len(err_coord) > 0:
                    first_coord = err_coord[0]
                    if isinstance(first_coord, dict) and "coordinates" in first_coord:
                        bbox_list = first_coord["coordinates"]
                        if len(bbox_list) >= 4:
                            x1, y1, x2, y2 = bbox_list[:4]
                            x, y = float(x1), float(y1)
                            w, h = float(x2 - x1), float(y2 - y1)
                        if first_coord.get("page", -1) != -1:
                            page_nr = first_coord["page"]
                elif isinstance(bbox, (list, tuple)):
                    if len(bbox) == 4:
                        x1, y1, x2, y2 = bbox
                        x, y = float(x1), float(y1)
                        w, h = float(x2 - x1), float(y2 - y1)
                    elif len(bbox) == 2:
                        x, y = float(bbox[0]), float(bbox[1])
                elif single_x is not None and single_y is not None:
                    x, y = float(single_x), float(single_y)

                if w <= 0:
                    w = 20.0
                if h <= 0:
                    h = 20.0

                ui_report.append({
                    "page": page_nr,
                    "category": str(category),
                    "found_text": str(text),
                    "comment": str(comment),
                    "coords": {"x": x, "y": y, "w": w, "h": h},
                })

            sota_data = getattr(final_report, "llm_result", None)
            ui_data = {
                "errors": ui_report,
                "sota": sota_data if isinstance(sota_data, dict) else None,
                "language": self.language,
            }
            self.finished_success.emit(ui_data)

        except Exception as e:
            logger.exception("Analysis pipeline failed")
            self.finished_error.emit(str(e))




class AnalysisDialog(QDialog):
    CONFIG_SIZE = (640, 720)
    PROGRESS_SIZE = (640, 300)

    def __init__(self, pdf_path, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.setObjectName("AnalysisDialog")
        self.setWindowTitle(t("analysis.title"))
        self.setFixedSize(*self.CONFIG_SIZE)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setStyleSheet(styles.DIALOG_STYLE)

        self.config_file_path = None
        self.ai_available = llm_runtime_available()
        self.models_available = are_ai_models_downloaded() if self.ai_available else False
        self.should_download_models = False
        self._gpu_info_ready = False

        self.setup_ui()
        self._restore_last_config()

    def check_gpu_vram(self):
        """Return (gpu name, VRAM in GB). Torch is imported lazily: it is slow and optional."""
        try:
            import torch
            if torch.cuda.is_available():
                device = torch.cuda.current_device()
                name = torch.cuda.get_device_name(device)
                vram_gb = torch.cuda.get_device_properties(device).total_memory / (1024 ** 3)
                return name, vram_gb
        except Exception:
            pass
        return None, 0.0

    def _ensure_gpu_info(self):
        """Fill the GPU hint label once, the first time the detailed mode is selected."""
        if self._gpu_info_ready:
            return
        self._gpu_info_ready = True

        gpu_name, vram_gb = self.check_gpu_vram()
        if gpu_name:
            if vram_gb >= 8.0:
                color, bg = styles.SUCCESS, styles.SUCCESS_BG
                rec_text = t("analysis.gpu_ok", name=gpu_name, vram=f"{vram_gb:.1f}")
            else:
                color, bg = styles.WARNING, styles.WARNING_BG
                rec_text = t("analysis.gpu_low", name=gpu_name, vram=f"{vram_gb:.1f}")
        else:
            color, bg = styles.WARNING, styles.WARNING_BG
            rec_text = t("analysis.gpu_none")

        self.gpu_info_label.setText(rec_text)
        self.gpu_info_label.setStyleSheet(
            f"font-size: 13px; color: {color}; background-color: {bg}; "
            "border: none; border-radius: 8px; padding: 8px 10px;"
        )

    @staticmethod
    def _field_label(text):
        label = QLabel(text)
        label.setStyleSheet(styles.FIELD_LABEL_STYLE)
        return label

    @staticmethod
    def _segment(buttons):
        """Wrap checkable buttons into a segmented control and make them mutually exclusive."""
        frame = QFrame()
        frame.setObjectName("Segment")
        frame.setStyleSheet(styles.SEGMENT_STYLE)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        group = QButtonGroup(frame)
        group.setExclusive(True)
        for btn in buttons:
            btn.setCheckable(True)
            btn.setFixedHeight(42)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(styles.MODE_BTN_STYLE)
            group.addButton(btn)
            lay.addWidget(btn, 1)
        return frame

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(32, 28, 32, 28)
        self.main_layout.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title_label = QLabel(t("analysis.title"))
        self.title_label.setStyleSheet(
            f"font-size: 21px; font-weight: 600; color: {styles.TEXT}; border: none; background: transparent;"
        )
        shown_name = os.path.basename(self.pdf_path) if self.pdf_path else ""
        self.subtitle_label = QLabel(shown_name)
        self.subtitle_label.setToolTip(self.pdf_path or "")
        self.subtitle_label.setStyleSheet(styles.SUBTITLE_STYLE)
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)

        self.close_btn = QPushButton()
        self.close_btn.setFixedSize(36, 36)
        self.close_btn.setToolTip(t("common.close"))
        self.close_btn.setAccessibleName(t("common.close"))
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setIcon(icons.icon("close", styles.TEXT_2, 20, 2.25))
        self.close_btn.setIconSize(QSize(20, 20))
        self.close_btn.setStyleSheet(styles.ICON_BUTTON_STYLE)
        self.close_btn.clicked.connect(self.reject)
        header.addLayout(title_col, 1)
        header.addWidget(self.close_btn, alignment=Qt.AlignTop)
        self.main_layout.addLayout(header)

        self.config_widget = QWidget()
        self.config_widget.setStyleSheet("background: transparent;")
        config_layout = QVBoxLayout(self.config_widget)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(20)

        # --- configuration file -------------------------------------------------
        file_section = QVBoxLayout()
        file_section.setSpacing(8)
        file_section.addWidget(self._field_label(t("analysis.config_file")))

        self.json_frame = ConfigDropFrame()
        self.json_frame.setStyleSheet(styles.JSON_FRAME_STYLE)
        self.json_frame.setFixedHeight(230)
        json_inner_layout = QVBoxLayout(self.json_frame)
        json_inner_layout.setContentsMargins(24, 16, 24, 16)
        json_inner_layout.setSpacing(6)

        self.json_icon = QLabel()
        self.json_icon.setFixedSize(70, 70)
        self.json_icon.setAlignment(Qt.AlignCenter)
        self.json_icon.setPixmap(icons.pixmap("json", styles.PRIMARY, 32))
        self.json_icon.setStyleSheet(styles.JSON_ICON_CIRCLE)
        self.json_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.drop_label = QLabel(t("analysis.drag_config"))
        self.drop_label.setStyleSheet(styles.DRAG_TEXT_STYLE)
        self.drop_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        or_row = QHBoxLayout()
        or_row.setSpacing(4)
        or_row.setAlignment(Qt.AlignCenter)
        or_lbl = QLabel(t("common.or"))
        or_lbl.setStyleSheet(styles.OR_LABEL_STYLE.replace("13px", "14px"))
        or_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.add_json_btn = QPushButton(t("analysis.add_config"))
        self.add_json_btn.setFixedHeight(42)
        self.add_json_btn.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        self.add_json_btn.setCursor(Qt.PointingHandCursor)
        or_row.addWidget(or_lbl)

        json_inner_layout.addStretch()
        json_inner_layout.addWidget(self.json_icon, alignment=Qt.AlignCenter)
        json_inner_layout.addWidget(self.drop_label, alignment=Qt.AlignCenter)
        json_inner_layout.addLayout(or_row)
        json_inner_layout.addWidget(self.add_json_btn, alignment=Qt.AlignCenter)
        json_inner_layout.addStretch()
        file_section.addWidget(self.json_frame)

        self.badge_container = QWidget()
        self.badge_container.setStyleSheet("background: transparent;")
        self.badge_layout = QVBoxLayout(self.badge_container)
        self.badge_layout.setContentsMargins(0, 0, 0, 0)
        self.badge_container.setVisible(False)
        file_section.addWidget(self.badge_container)
        config_layout.addLayout(file_section)

        # --- language -------------------------------------------------------------
        lang_section = QVBoxLayout()
        lang_section.setSpacing(8)
        self.btn_lang_pl = QPushButton(t("analysis.lang_pl"))
        self.btn_lang_en = QPushButton(t("analysis.lang_en"))
        lang_segment = self._segment([self.btn_lang_pl, self.btn_lang_en])
        self.btn_lang_pl.setChecked(True)
        lang_section.addWidget(self._field_label(t("analysis.thesis_language")))
        lang_section.addWidget(lang_segment)
        config_layout.addLayout(lang_section)

        # --- analysis mode --------------------------------------------------------
        mode_section = QVBoxLayout()
        mode_section.setSpacing(8)
        self.btn_szybki = QPushButton(t("analysis.mode_fast"))
        self.btn_dokladny = QPushButton(t("analysis.mode_detailed"))
        mode_segment = self._segment([self.btn_szybki, self.btn_dokladny])
        self.btn_szybki.setChecked(True)

        self.mode_hint_label = QLabel(t("analysis.mode_fast_hint"))
        self.mode_hint_label.setWordWrap(True)
        self.mode_hint_label.setStyleSheet(styles.HINT_STYLE)

        if not self.ai_available:
            self.btn_dokladny.setEnabled(False)
            self.btn_dokladny.setToolTip(
                t("analysis.ai_unavailable_tooltip")
            )
            self.mode_hint_label.setText(
                t("analysis.ai_unavailable_hint")
            )

        self.cb_images = QCheckBox(t("analysis.images_checkbox"))
        self.cb_images.setStyleSheet(styles.checkbox_style())
        self.cb_images.setChecked(True)
        self.cb_images.setVisible(False)

        self.gpu_info_label = QLabel()
        self.gpu_info_label.setWordWrap(True)
        self.gpu_info_label.setVisible(False)

        mode_section.addWidget(self._field_label(t("analysis.mode")))
        mode_section.addWidget(mode_segment)
        mode_section.addWidget(self.mode_hint_label)
        mode_section.addWidget(self.cb_images)
        mode_section.addWidget(self.gpu_info_label)

        def on_szybki_clicked():
            self.btn_szybki.setChecked(True)
            self.btn_dokladny.setChecked(False)
            self.cb_images.setVisible(False)
            self.gpu_info_label.setVisible(False)
            self.mode_hint_label.setVisible(True)

        def on_dokladny_clicked():
            if not are_ai_models_downloaded() and not self.should_download_models:
                reply = MessageBox.question(
                    self,
                    t("analysis.no_models_title"),
                    t("analysis.no_models_text"),
                    MessageBox.Yes | MessageBox.No,
                    MessageBox.No,
                )
                if reply != MessageBox.Yes:
                    self.btn_dokladny.setChecked(False)
                    self.btn_szybki.setChecked(True)
                    return
                self.should_download_models = True
                self.models_available = True

            self.btn_szybki.setChecked(False)
            self.btn_dokladny.setChecked(True)
            self._ensure_gpu_info()
            self.cb_images.setVisible(True)
            self.gpu_info_label.setVisible(True)
            self.mode_hint_label.setVisible(False)

        self.btn_szybki.clicked.connect(on_szybki_clicked)
        self.btn_dokladny.clicked.connect(on_dokladny_clicked)

        config_layout.addLayout(mode_section)
        config_layout.addStretch(1)
        self.main_layout.addWidget(self.config_widget, 1)

        # --- progress view ----------------------------------------------------------
        self.progress_widget = QWidget()
        self.progress_widget.setVisible(False)
        self.progress_widget.setStyleSheet("background: transparent;")
        progress_layout = QVBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(14)

        self.progress_label = QLabel(t("analysis.preparing"))
        self.progress_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.progress_label.setWordWrap(True)
        self.progress_label.setStyleSheet(
            f"font-size: 15px; color: {styles.TEXT_3}; background: transparent; border: none;"
        )

        self.pbar = QProgressBar()
        self.pbar.setStyleSheet(styles.PROGRESS_BAR_STYLE)
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        self.pbar.setTextVisible(False)

        self.cancel_btn = QPushButton(t("common.cancel"))
        self.cancel_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancel_analysis)

        progress_layout.addStretch()
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.pbar)
        progress_layout.addSpacing(8)
        progress_layout.addWidget(self.cancel_btn, alignment=Qt.AlignLeft)
        progress_layout.addStretch()
        self.main_layout.addWidget(self.progress_widget, 1)

        # --- footer -------------------------------------------------------------------
        self.footer = QWidget()
        self.footer.setStyleSheet("background: transparent;")
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)

        self.dismiss_btn = QPushButton(t("common.cancel"))
        self.dismiss_btn.setFixedHeight(48)
        self.dismiss_btn.setCursor(Qt.PointingHandCursor)
        self.dismiss_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        self.dismiss_btn.clicked.connect(self.reject)

        self.analyze_btn = QPushButton(t("analysis.analyze"))
        self.analyze_btn.setFixedHeight(48)
        self.analyze_btn.setCursor(Qt.PointingHandCursor)
        self.analyze_btn.setDefault(True)
        self.analyze_btn.setStyleSheet(styles.ANALIZA_BTN_STYLE)
        self.analyze_btn.clicked.connect(self.start_analysis)

        footer_layout.addStretch(1)
        footer_layout.addWidget(self.dismiss_btn)
        footer_layout.addWidget(self.analyze_btn)
        self.main_layout.addWidget(self.footer)

        self.add_json_btn.clicked.connect(self.open_file_dialog)
        self.json_frame.clicked.connect(self.open_file_dialog)
        self.json_frame.fileDropped.connect(self.set_config_file)

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, t("analysis.choose_config"), "", t("common.json_filter"))
        if path:
            self.set_config_file(path)

    def _clear_badge(self):
        while self.badge_layout.count():
            item = self.badge_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _restore_last_config(self):
        """Offer the requirements file used last time again; the trash icon on the badge lets the user pick another."""
        try:
            path = load_config().get(LAST_CONFIG_KEY)
        except Exception:
            logger.exception("Could not read the last used configuration file")
            return
        if isinstance(path, str) and path.lower().endswith(".json") and os.path.isfile(path):
            self.set_config_file(path, remembered=True)

    def _remember_config_file(self):
        """Store the chosen file as the latest one (or forget it when the analysis runs without a file)."""
        try:
            cfg = load_config()
            if cfg.get(LAST_CONFIG_KEY) == self.config_file_path:
                return
            if self.config_file_path:
                cfg[LAST_CONFIG_KEY] = self.config_file_path
            else:
                cfg.pop(LAST_CONFIG_KEY, None)
            save_config(cfg)
        except Exception:
            logger.exception("Could not remember the configuration file")

    def set_config_file(self, path, remembered=False):
        self.config_file_path = path
        self._clear_badge()
        badge = FileBadge(os.path.basename(path), info_text=t("analysis.config_last") if remembered else None)
        badge.removed.connect(self.remove_config_file)
        self.badge_layout.addWidget(badge)
        self.badge_container.setVisible(True)
        self.json_frame.setVisible(False)

    def remove_config_file(self):
        self.config_file_path = None
        self.badge_container.setVisible(False)
        self._clear_badge()
        self.json_frame.setVisible(True)

    def _resize_keep_center(self, size):
        """Resize the fixed-size dialog around its current centre."""
        centre = self.geometry().center()
        self.setFixedSize(*size)
        self.move(centre.x() - size[0] // 2, centre.y() - size[1] // 2)

    def start_analysis(self):
        self._remember_config_file()
        self._resize_keep_center(self.PROGRESS_SIZE)
        self.config_widget.setVisible(False)
        self.footer.setVisible(False)
        self.progress_widget.setVisible(True)
        self.title_label.setText(t("analysis.analyzing"))

        is_detailed = self.btn_dokladny.isChecked() and self.ai_available
        chosen_lang = "pl" if self.btn_lang_pl.isChecked() else "en"

        self.run_pipeline_worker(is_detailed, chosen_lang)

    def run_pipeline_worker(self, is_detailed, chosen_lang):
        self.worker = PipelineWorker(
            pdf_path=self.pdf_path,
            config_path=self.config_file_path,
            use_llm=is_detailed,
            language=chosen_lang,
            download_models_flag=self.should_download_models,
        )
        self.worker.progress_update.connect(self.update_progress)
        self.worker.finished_success.connect(self.on_analysis_success)
        self.worker.finished_error.connect(self.on_analysis_error)
        self.worker.start()

    def on_analysis_success(self, final_report):
        self.final_report = final_report
        self.accept()

    def on_analysis_error(self, message):
        """Tell the user what went wrong and return to the settings screen."""
        MessageBox.critical(
            self,
            t("analysis.error_title"),
            message or t("analysis.unknown_error"),
        )
        self.reset_ui_state()

    def cancel_analysis(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        self.reset_ui_state()

    def reset_ui_state(self):
        self._resize_keep_center(self.CONFIG_SIZE)
        self.pbar.setValue(0)
        self.progress_label.setText(t("analysis.preparing"))
        self.progress_widget.setVisible(False)
        self.config_widget.setVisible(True)
        self.footer.setVisible(True)
        self.close_btn.setEnabled(True)
        self.title_label.setText(t("analysis.title"))

    def update_progress(self, value, text):
        self.pbar.setValue(value)
        self.progress_label.setText(text)