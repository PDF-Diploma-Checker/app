"""Right after the launch: tells the user what the GPU mode is still missing and what to do about it.

The check runs off the UI thread (see common.gpu_startup), so the window opens at once; the dialog appears only when
something is missing and the user has not asked not to be reminded of exactly these problems.
"""

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from common import gpu_startup

from . import styles
from .i18n import t
from .message_box import fit_minimum_height

logger = logging.getLogger(__name__)


class _CheckWorker(QThread):
    done = Signal(object)

    def run(self):
        try:
            issues = gpu_startup.check()
        except Exception:
            logger.exception("GPU startup check failed")
            issues = []
        self.done.emit(issues)


class GpuStartupDialog(QDialog):
    """Lists every missing piece with its next step. `open_setup` is True when the user wants the AI setup."""

    def __init__(self, issues, parent=None):
        super().__init__(parent)
        self.issues = issues
        self.open_setup = False
        self.setObjectName("GpuStartupDialog")
        self.setWindowTitle(t("gpu_startup.title"))
        self.setMinimumWidth(560)
        self.setMaximumHeight(720)
        self.setStyleSheet(f"QDialog#GpuStartupDialog {{ background-color: {styles.SURFACE}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)

        title = QLabel(t("gpu_startup.title"))
        title.setStyleSheet(f"font-size: 20px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;")
        intro = QLabel(t("gpu_startup.intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet(styles.SUBTITLE_STYLE)
        root.addWidget(title)
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 4, 8, 4)
        lay.setSpacing(14)
        for issue in issues:
            lay.addWidget(self._issue_row(issue))
        lay.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        guide = QLabel(t("gpu_startup.guide", url=gpu_startup.GUIDE_URL))
        guide.setOpenExternalLinks(True)
        guide.setStyleSheet(styles.HINT_STYLE)
        root.addWidget(guide)

        self.dont_remind = QCheckBox(t("gpu_startup.dont_remind"))
        self.dont_remind.setStyleSheet(styles.checkbox_style())
        root.addWidget(self.dont_remind)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        later = QPushButton(t("gpu_startup.later"))
        later.setFixedHeight(42)
        later.setCursor(Qt.PointingHandCursor)
        later.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        later.clicked.connect(self.reject)
        setup = QPushButton(t("gpu_startup.open_setup"))
        setup.setFixedHeight(42)
        setup.setCursor(Qt.PointingHandCursor)
        setup.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        setup.setDefault(True)
        setup.clicked.connect(self._open_setup)
        buttons.addStretch(1)
        buttons.addWidget(later)
        buttons.addWidget(setup)
        root.addLayout(buttons)
        fit_minimum_height(self)

    @staticmethod
    def _issue_row(issue):
        row = QWidget()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        head = QLabel(t(f"gpu_startup.{issue.id}.title", **issue.params))
        head.setWordWrap(True)
        head.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;")
        fix = QLabel(t(f"gpu_startup.{issue.id}.fix", **issue.params))
        fix.setWordWrap(True)
        fix.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fix.setStyleSheet(f"font-size: 13px; color: {styles.WARNING}; background: transparent; border: none;")
        lay.addWidget(head)
        lay.addWidget(fix)
        return row

    def _open_setup(self):
        self.open_setup = True
        self.accept()

    def done(self, result):
        if self.dont_remind.isChecked():
            try:
                gpu_startup.dismiss(self.issues)
            except Exception:
                logger.exception("Could not save the choice not to be reminded")
        super().done(result)


def _show(window, issues):
    """Not modal: the notice must never lock the window. A modal dialog that the window manager put behind the main
    window (or on another screen) left the whole app unresponsive right after the launch."""
    dialog = GpuStartupDialog(issues, window)
    dialog.setModal(False)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    window._gpu_startup_dialog = dialog

    def closed(_result):
        window._gpu_startup_dialog = None
        if dialog.open_setup:
            from .ai_setup_dialog import AiSetupDialog
            from .model_download_dialog import download_models
            setup = AiSetupDialog(window, first_run=False)
            setup.exec()
            if setup.saved and setup.download_requested:
                download_models(window)

    dialog.finished.connect(closed)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def check_on_launch(window):
    """Start the check in the background; the dialog shows up over `window` only if something is missing."""
    worker = _CheckWorker(window)
    worker.done.connect(lambda issues: _show(window, issues) if issues else None)
    worker.finished.connect(worker.deleteLater)
    window._gpu_startup_worker = worker
    worker.start()
