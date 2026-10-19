"""AI setup: system check (what is installed, what is missing), CPU/GPU choice and the folder for the models.

Opened automatically the first time the detailed analysis mode is chosen, and from the settings at any time.
"""

import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from analysis.modules.llm import config as app_config
from common import gpu_check

from . import icons, styles
from .i18n import t
from .message_box import MessageBox

logger = logging.getLogger(__name__)

LEVEL_COLORS = {
    "ok": styles.SUCCESS_DOT,
    "warn": styles.WARNING_DOT,
    "fail": styles.DANGER_DOT,
    "info": styles.BORDER_STRONG,
}
FIX_COLORS = {"warn": styles.WARNING, "fail": styles.DANGER}


class _CheckWorker(QThread):
    """Runs the (slow) hardware check off the UI thread."""
    done = Signal(object)

    def __init__(self, model_dir, parent=None):
        super().__init__(parent)
        self._model_dir = model_dir

    def run(self):
        try:
            report = gpu_check.check_hardware(self._model_dir)
        except Exception:
            logger.exception("Hardware check failed")
            report = None
        self.done.emit(report)


def _field_style():
    return (
        f"QLineEdit {{ min-height: 20px; }}"
    )


def _section_label(text):
    label = QLabel(text)
    label.setStyleSheet(styles.SECTION_TITLE_DARK)
    return label


def _separator():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background-color: {styles.BORDER}; border: none;")
    return line


class AiSetupDialog(QDialog):
    """Result after exec(): `saved` (settings were written) and `download_requested` (user wants the models now)."""

    def __init__(self, parent=None, first_run=False):
        super().__init__(parent)
        self.setObjectName("AiSetupDialog")
        self.setWindowTitle(t("ai_setup.title"))
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry().height() if screen else 900
        self.setFixedSize(680, max(520, min(840, available - 60)))     # small screens: the content scrolls
        self.setStyleSheet(f"QDialog#AiSetupDialog {{ background-color: {styles.SURFACE}; }}" + _field_style())

        self.first_run = first_run
        self.saved = False
        self.download_requested = False
        self.report = None
        self._worker = None
        self._cfg = app_config.load_config()
        self._default_dir = Path(app_config.default_model_dir())

        self._build()
        self.start_check()

    # ------------------------------------------------------------ building
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(0)

        title = QLabel(t("ai_setup.title"))
        title.setStyleSheet(
            f"font-size: 22px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;"
        )
        subtitle = QLabel(t("ai_setup.subtitle_first" if self.first_run else "ai_setup.subtitle_check"))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(styles.SUBTITLE_STYLE)
        root.addWidget(title)
        root.addSpacing(6)
        root.addWidget(subtitle)
        root.addSpacing(18)

        # everything between the header and the buttons scrolls, so a long list of findings never pushes buttons away
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, 8, 0)
        self.body_layout.setSpacing(10)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.scroll = scroll
        self.body = body

        # --- system -------------------------------------------------------------
        head = QHBoxLayout()
        head.addWidget(_section_label(t("ai_setup.section_system")))
        head.addStretch(1)
        self.recheck_btn = QPushButton(t("ai_setup.recheck"))
        self.recheck_btn.setFixedHeight(34)
        self.recheck_btn.setCursor(Qt.PointingHandCursor)
        self.recheck_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE + "QPushButton { padding: 0 14px; }")
        self.recheck_btn.clicked.connect(self.start_check)
        head.addWidget(self.recheck_btn)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(_separator())

        self.status_label = QLabel(t("ai_setup.checking"))
        self.status_label.setStyleSheet(styles.MUTED_LABEL_STYLE)
        self.body_layout.addWidget(self.status_label)

        self.checks_box = QVBoxLayout()
        self.checks_box.setSpacing(8)
        self.body_layout.addLayout(self.checks_box)
        self.body_layout.addSpacing(10)

        # --- device -------------------------------------------------------------
        self.body_layout.addWidget(_section_label(t("ai_setup.section_device")))
        self.body_layout.addWidget(_separator())

        self.btn_cpu = QPushButton(t("ai_setup.device_cpu"))
        self.btn_gpu = QPushButton(t("ai_setup.device_gpu"))
        segment = QFrame()
        segment.setObjectName("Segment")
        segment.setStyleSheet(styles.SEGMENT_STYLE)
        lay = QHBoxLayout(segment)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        group = QButtonGroup(segment)
        group.setExclusive(True)
        for btn in (self.btn_cpu, self.btn_gpu):
            btn.setCheckable(True)
            btn.setFixedHeight(42)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(styles.MODE_BTN_STYLE)
            group.addButton(btn)
            lay.addWidget(btn, 1)
        self.btn_cpu.clicked.connect(self._update_device_widgets)
        self.btn_gpu.clicked.connect(self._update_device_widgets)
        self.body_layout.addWidget(segment)

        self.device_hint = QLabel()
        self.device_hint.setWordWrap(True)
        self.device_hint.setStyleSheet(styles.HINT_STYLE)
        self.body_layout.addWidget(self.device_hint)

        self.layers_row = QWidget()
        layers_lay = QHBoxLayout(self.layers_row)
        layers_lay.setContentsMargins(0, 0, 0, 0)
        layers_lay.setSpacing(12)
        layers_label = QLabel(t("ai_setup.layers"))
        layers_label.setStyleSheet(styles.FIELD_LABEL_STYLE)
        self.layers_input = QLineEdit()
        self.layers_input.setFixedSize(90, 40)
        layers_lay.addWidget(layers_label)
        layers_lay.addWidget(self.layers_input)
        layers_lay.addStretch(1)
        self.body_layout.addWidget(self.layers_row)
        self.layers_hint = QLabel()
        self.layers_hint.setWordWrap(True)
        self.layers_hint.setStyleSheet(styles.HINT_STYLE)
        self.body_layout.addWidget(self.layers_hint)
        self.body_layout.addSpacing(10)

        # --- models folder ---------------------------------------------------------
        self.body_layout.addWidget(_section_label(t("ai_setup.section_models")))
        self.body_layout.addWidget(_separator())
        desc = QLabel(t("ai_setup.models_desc", size=f"{gpu_check.AI_MODELS_SIZE_GB:.0f}"))
        desc.setWordWrap(True)
        desc.setStyleSheet(styles.HINT_STYLE)
        self.body_layout.addWidget(desc)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(10)
        self.dir_input = QLineEdit()
        self.dir_input.setFixedHeight(40)
        current = str(self._cfg.get("model_dir") or self._default_dir)
        self.dir_input.setText(os.path.normpath(current))
        self.dir_input.textChanged.connect(self._update_dir_status)
        browse = QPushButton("  " + t("ai_setup.browse"))
        browse.setIcon(icons.icon("folder", styles.TEXT_3, 16, 2.0))
        browse.setFixedHeight(40)
        browse.setCursor(Qt.PointingHandCursor)
        browse.setStyleSheet(styles.GRAY_BUTTON_STYLE + "QPushButton { padding: 0 14px; }")
        browse.clicked.connect(self._browse)
        dir_row.addWidget(self.dir_input, 1)
        dir_row.addWidget(browse)
        self.body_layout.addLayout(dir_row)

        self.dir_status = QLabel()
        self.dir_status.setWordWrap(True)
        self.body_layout.addWidget(self.dir_status)
        self.body_layout.addStretch(1)

        # --- buttons ---------------------------------------------------------------
        root.addSpacing(12)
        root.addWidget(_separator())
        root.addSpacing(16)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.cancel_btn = QPushButton(t("common.cancel"))
        self.cancel_btn.setFixedHeight(42)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton(t("ai_setup.save"))
        self.save_btn.setFixedHeight(42)
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        self.save_btn.clicked.connect(lambda: self._save(download=False))
        self.save_download_btn = QPushButton(t("ai_setup.save_download"))
        self.save_download_btn.setFixedHeight(42)
        self.save_download_btn.setCursor(Qt.PointingHandCursor)
        self.save_download_btn.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        self.save_download_btn.setDefault(True)
        self.save_download_btn.clicked.connect(lambda: self._save(download=True))
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.save_download_btn)
        root.addLayout(buttons)

        self._select_device(self._cfg.get("device") == "cuda")
        self.layers_input.setText(str(self._cfg.get("n_gpu_layers", 0)))
        self._update_device_widgets()
        self._update_dir_status()

    # ------------------------------------------------------------ system check
    def start_check(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.status_label.setText(t("ai_setup.checking"))
        self.status_label.setVisible(True)
        self.recheck_btn.setEnabled(False)
        self._worker = _CheckWorker(self._model_dir_text(), self)
        self._worker.done.connect(self._on_check_done)
        self._worker.start()

    def _on_check_done(self, report):
        self.recheck_btn.setEnabled(True)
        self.report = report
        if report is None:
            self.status_label.setText(t("common.error"))
            return
        self.status_label.setVisible(False)
        self._show_checks(report)

        first_time = not self._cfg.get("hardware_configured")
        if first_time:
            # nothing chosen yet: start from what this computer can do
            self._select_device(report.recommended_device == "cuda")
            self.layers_input.setText(str(report.recommended_layers))
        elif self.btn_gpu.isChecked() and not report.gpu_usable:
            self._select_device(False)
        self._update_device_widgets()

    def _show_checks(self, report):
        while self.checks_box.count():
            item = self.checks_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for check in report.checks:
            if check.id == "disk":          # shown next to the folder, which the user can still change
                continue
            self.checks_box.addWidget(self._check_row(check))
        self._fit_body()

    def _fit_body(self):
        """Wrapped labels have no fixed height; tell the scroll area how tall the content is at this width."""
        def fit():
            width = self.scroll.viewport().width()
            self.body.setMinimumHeight(self.body_layout.totalHeightForWidth(width))
        QTimer.singleShot(0, fit)

    @staticmethod
    def _check_row(check):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background-color: {LEVEL_COLORS.get(check.level, styles.BORDER_STRONG)};"
                          " border: none; border-radius: 5px;")
        dot_box = QVBoxLayout()
        dot_box.setContentsMargins(0, 6, 0, 0)
        dot_box.addWidget(dot)
        dot_box.addStretch(1)
        lay.addLayout(dot_box)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        main = QLabel(t(f"hw.{check.id}.{check.level}", **check.params))
        main.setWordWrap(True)
        main.setStyleSheet(f"font-size: 14px; color: {styles.TEXT}; background: transparent; border: none;")
        texts.addWidget(main)
        fix_key = f"hw.{check.id}.{check.level}_fix"
        fix = t(fix_key, **check.params)
        if fix != fix_key:
            fix_label = QLabel(fix)
            fix_label.setWordWrap(True)
            fix_label.setStyleSheet(
                f"font-size: 13px; color: {FIX_COLORS.get(check.level, styles.TEXT_2)};"
                " background: transparent; border: none;"
            )
            texts.addWidget(fix_label)
        lay.addLayout(texts, 1)
        return row

    # ------------------------------------------------------------ device
    def _select_device(self, gpu):
        self.btn_gpu.setChecked(bool(gpu))
        self.btn_cpu.setChecked(not gpu)

    def _gpu_available(self):
        """None while the check is still running."""
        return None if self.report is None else self.report.gpu_usable

    def _update_device_widgets(self):
        usable = self._gpu_available()
        gpu = self.btn_gpu.isChecked()
        self.btn_gpu.setEnabled(usable is not False)
        if usable is False:
            self.btn_gpu.setToolTip(t("ai_setup.device_gpu_unavailable"))
        else:
            self.btn_gpu.setToolTip("")
        if usable is False and gpu:
            self._select_device(False)
            gpu = False

        if gpu:
            name = self.report.gpu_name if self.report else "GPU"
            self.device_hint.setText(t("ai_setup.device_hint_gpu", name=name))
        elif usable is False:
            self.device_hint.setText(t("ai_setup.device_gpu_unavailable"))
        else:
            self.device_hint.setText(t("ai_setup.device_hint_cpu"))
        self.layers_row.setVisible(gpu)
        self.layers_hint.setVisible(gpu)
        layers = self.report.recommended_layers if self.report else 0
        self.layers_hint.setText(t("ai_setup.layers_hint", layers=layers))

    # ------------------------------------------------------------ models folder
    def _model_dir_text(self):
        return self.dir_input.text().strip() if hasattr(self, "dir_input") else str(self._default_dir)

    def _browse(self):
        start = self._model_dir_text() or str(self._default_dir)
        path = QFileDialog.getExistingDirectory(self, t("ai_setup.choose_dir"), start)
        if path:
            self.dir_input.setText(os.path.normpath(path))

    def _folder_state(self):
        """('present' | 'ok' | 'low' | 'readonly', free_gb) for the folder in the input field."""
        text = self._model_dir_text() or str(self._default_dir)
        directory = Path(text).expanduser()
        free = gpu_check.free_space_gb(directory)
        if app_config._models_present(directory):
            return "present", free
        if not _can_write(directory):
            return "readonly", free
        if free < gpu_check.NEEDED_FREE_GB:
            return "low", free
        return "ok", free

    def _update_dir_status(self):
        state, free = self._folder_state()
        needed = f"{gpu_check.AI_MODELS_SIZE_GB:.0f}"
        if state == "present":
            text, color = t("ai_setup.models_present"), styles.SUCCESS
        elif state == "readonly":
            text, color = t("ai_setup.folder_not_writable"), styles.DANGER
        elif state == "low":
            text, color = t("ai_setup.disk_low", free=f"{free:.0f}", needed=needed), styles.WARNING
        else:
            text, color = t("ai_setup.disk_ok", free=f"{free:.0f}", needed=needed), styles.TEXT_2
        self.dir_status.setText(text)
        self.dir_status.setStyleSheet(f"font-size: 13px; color: {color}; background: transparent; border: none;")
        self.save_download_btn.setVisible(state != "present")
        self.save_download_btn.setEnabled(state in ("ok", "low"))
        self.save_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE if state != "present" else styles.BLUE_BUTTON_STYLE)

    # ------------------------------------------------------------ saving
    def _save(self, download):
        gpu = self.btn_gpu.isChecked()
        try:
            layers = int(self.layers_input.text().strip())
        except ValueError:
            layers = self.report.recommended_layers if (self.report and self.report.recommended_layers) else 25
        text = self._model_dir_text()
        chosen = os.path.normpath(os.path.expanduser(text)) if text else ""
        if chosen and Path(chosen) == self._default_dir:
            chosen = ""             # follow the default, so moving the app folder moves the models with it

        cfg = app_config.load_config()
        cfg.update({
            "device": "cuda" if gpu else "cpu",
            "n_gpu_layers": layers if gpu else 0,
            "model_dir": chosen,
            "hardware_configured": True,
        })
        try:
            app_config.save_config(cfg)
            app_config.reload_config()
        except Exception as e:
            logger.exception("Could not save the AI settings")
            MessageBox.critical(self, t("common.error"), t("ai_setup.save_failed", error=str(e)))
            return
        self.saved = True
        self.download_requested = bool(download)
        self.accept()

    # ------------------------------------------------------------ closing
    def done(self, result):
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(15000)
        super().done(result)


def _can_write(directory):
    """The folder exists and is writable, or can be created (its nearest existing parent is writable)."""
    probe = Path(directory)
    while not probe.exists():
        if probe.parent == probe:
            return False
        probe = probe.parent
    return probe.is_dir() and os.access(probe, os.W_OK)
