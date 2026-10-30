"""Download of the AI models outside an analysis (from the settings or right after the AI setup)."""

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from analysis.modules.llm import config as app_config
from common import gpu_check, run_control
from common.cancellation import AnalysisCancelled, CancelToken

from . import styles
from .i18n import t
from .message_box import MessageBox

logger = logging.getLogger(__name__)


class _DownloadWorker(QThread):
    progress = Signal(int, str)
    failed = Signal(str)
    succeeded = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = CancelToken()

    def _report(self, value, text):
        self.token.check()
        if value >= 0:
            self.progress.emit(value, text)

    def run(self):
        run_control.bind(self.token, self._report)
        try:
            app_config.download_ai_models_with_progress(self._report)
            self.succeeded.emit()
        except AnalysisCancelled:
            logger.info("Model download cancelled by the user")
        except Exception as e:
            logger.exception("Model download failed")
            self.failed.emit(str(e))
        finally:
            run_control.unbind()


class ModelDownloadDialog(QDialog):
    """Downloads the missing models into the models folder in use. `ok` is True after a complete download."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ok = False
        self.setWindowTitle(t("models.title"))
        self.setFixedWidth(520)
        self.setStyleSheet(f"QDialog {{ background-color: {styles.SURFACE}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(12)

        title = QLabel(t("models.title"))
        title.setStyleSheet(f"font-size: 19px; font-weight: 600; color: {styles.TEXT}; background: transparent;")
        where = QLabel(t("models.where", size=f"{gpu_check.AI_MODELS_SIZE_GB:.0f}", path=app_config.MODEL_DIR))
        where.setWordWrap(True)
        where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        where.setStyleSheet(styles.HINT_STYLE)
        self.status = QLabel(t("models.starting"))
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"font-size: 14px; color: {styles.TEXT_3}; background: transparent;")
        self.bar = QProgressBar()
        self.bar.setStyleSheet(styles.PROGRESS_BAR_STYLE)
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 0)         # busy until the first stage is reported

        self.cancel_btn = QPushButton(t("common.cancel"))
        self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)

        layout.addWidget(title)
        layout.addWidget(where)
        layout.addSpacing(6)
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addSpacing(6)
        layout.addLayout(buttons)

        self.worker = _DownloadWorker()
        self.worker.progress.connect(self._on_progress)
        self.worker.failed.connect(self._on_failed)
        self.worker.succeeded.connect(self._on_done)
        self.worker.start()

    def _on_progress(self, value, text):
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 100)
        self.bar.setValue(max(value, self.bar.value()))
        self.status.setText(text)

    def _on_done(self):
        self.ok = app_config.are_ai_models_downloaded()
        MessageBox.information(self, t("models.title"), t("models.done"))
        self.accept()

    def _on_failed(self, message):
        MessageBox.critical(self, t("common.error"), message)
        super().reject()

    def reject(self):
        """Cancel: the download stops between files (a file being downloaded is finished first)."""
        if self.worker.isRunning():
            self.worker.token.cancel()
            self.cancel_btn.setEnabled(False)
            self.status.setText(t("models.cancelling"))
            self.worker.finished.connect(lambda: QDialog.reject(self))
            return
        super().reject()


def download_models(parent):
    """Show the download dialog when the models are missing; True when they are there afterwards."""
    if app_config.are_ai_models_downloaded():
        return True
    if not app_config.llm_runtime_available():
        MessageBox.warning(parent, t("models.title"), t("models.no_runtime"))
        return False
    dialog = ModelDownloadDialog(parent)
    dialog.exec()
    return dialog.ok
