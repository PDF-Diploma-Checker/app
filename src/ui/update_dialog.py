"""Update window: download the new version, then restart into it. Models, settings and history stay untouched."""

import logging
import threading
import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from common import updater
from common.updater import UpdateCancelled, UpdateError

from . import styles
from .i18n import t
from .message_box import MessageBox

logger = logging.getLogger(__name__)


def format_bytes(value):
    value = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
        value /= 1024


def format_eta(seconds):
    seconds = int(max(seconds, 0))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60:02d} s"
    return f"{seconds // 3600} h {(seconds % 3600) // 60:02d} min"


def error_text(code, params):
    """User-facing text for an UpdateError code."""
    params = dict(params)
    if code == "space":
        params = {"free": format_bytes(params["free"]), "needed": format_bytes(params["needed"])}
    if code == "cannot":
        params = {"reason": t(f"updater.cannot_{params.get('reason')}")}
    key = f"updater.err_{code}"
    text = t(key, **params)
    return text if text != key else t("updater.err_generic", error=params.get("error", code))


class _PlanWorker(QThread):
    """Finds the files of this release for this system (loads llama.cpp to tell the variant) and compares the
    installed files with the release to see what has to be downloaded: off the UI thread."""
    done = Signal(object)
    failed = Signal(str, dict)
    progress = Signal(object, object)           # compared bytes, total bytes
    cancelled = Signal()

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self._info = info
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            plan = updater.plan_update(self._info)
            updater.prepare_delta(plan, lambda d, total: self.progress.emit(d, total), self._cancel.is_set)
            self.done.emit(plan)
        except UpdateCancelled:
            self.cancelled.emit()
        except UpdateError as e:
            self.failed.emit(e.code, e.params)
        except Exception as e:
            logger.exception("Update plan failed")
            self.failed.emit("generic", {"error": str(e)})


class _StageWorker(QThread):
    progress = Signal(str, object, object)      # stage, done, total
    done = Signal(object)
    failed = Signal(str, dict)
    cancelled = Signal()

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self._plan = plan
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            staged = updater.stage_update(
                self._plan, lambda stage, d, total: self.progress.emit(stage, d, total), self._cancel.is_set,
            )
            self.done.emit(staged)
        except UpdateCancelled:
            self.cancelled.emit()
        except UpdateError as e:
            self.failed.emit(e.code, e.params)
        except Exception as e:
            logger.exception("Update failed")
            self.failed.emit("generic", {"error": str(e)})


class UpdateDialog(QDialog):
    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.setObjectName("UpdateDialog")
        self.setWindowTitle(t("updater.title"))
        self.setFixedWidth(560)
        self.setStyleSheet(f"QDialog#UpdateDialog {{ background-color: {styles.SURFACE}; }}")
        self.info = info
        self.plan = None
        self.staged = None
        self._worker = None
        self._started = 0.0
        self._build()

        self._plan_worker = _PlanWorker(info, self)
        self._plan_worker.done.connect(self._on_plan)
        self._plan_worker.failed.connect(self._on_failed)
        self._plan_worker.progress.connect(lambda d, total: self._on_progress("compare", d, total))
        self._plan_worker.cancelled.connect(lambda: QDialog.reject(self))
        self._delta = False                         # the download is a differential one (see _on_plan)
        self._plan_worker.start()

    # ------------------------------------------------------------ building
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(14)

        self.title = QLabel(t("updater.header", new=self.info["version"]))
        self.title.setStyleSheet(
            f"font-size: 21px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;"
        )
        lay.addWidget(self.title)

        self.text = QLabel(t("updater.looking"))
        self.text.setWordWrap(True)
        self.text.setStyleSheet(styles.SUBTITLE_STYLE)
        lay.addWidget(self.text)

        self.bar = QProgressBar()
        self.bar.setStyleSheet(styles.PROGRESS_BAR_STYLE)
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(styles.HINT_STYLE)
        self.status.setVisible(False)
        lay.addWidget(self.status)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self.cancel_btn = QPushButton(t("common.cancel"))
        self.cancel_btn.setFixedHeight(42)
        self.cancel_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        self.main_btn = QPushButton(t("updater.start"))
        self.main_btn.setFixedHeight(42)
        self.main_btn.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        self.main_btn.setCursor(Qt.PointingHandCursor)
        self.main_btn.setEnabled(False)
        self.main_btn.setDefault(True)
        self.main_btn.clicked.connect(self._start)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.main_btn)
        lay.addSpacing(6)
        lay.addLayout(row)

    # ------------------------------------------------------------ plan
    def _on_plan(self, plan):
        self.plan = plan
        self.bar.setVisible(False)
        self.status.setVisible(False)
        self._delta = bool(plan.delta) and plan.total_size < plan.full_size * 0.9
        if self._delta:
            self.text.setText(t("updater.intro_delta", current=self.info["current"], size=format_bytes(plan.total_size),
                                full=format_bytes(plan.full_size)))
        else:
            self.text.setText(t("updater.intro", current=self.info["current"], size=format_bytes(plan.total_size)))
        self.main_btn.setEnabled(True)

    def _on_failed(self, code, params):
        self._set_busy(False)
        self.bar.setVisible(False)
        self.status.setVisible(False)
        self.text.setText(error_text(code, params))
        self.text.setStyleSheet(f"font-size: 15px; color: {styles.DANGER}; background: transparent; border: none;")
        self.main_btn.setText(t("common.close"))
        self.main_btn.setEnabled(True)
        self.main_btn.clicked.disconnect()
        self.main_btn.clicked.connect(self.reject)
        self.cancel_btn.setVisible(False)

    # ------------------------------------------------------------ download
    def _set_busy(self, busy):
        self.main_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(True)

    def _start(self):
        self.text.setText(t("updater.working"))
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.status.setVisible(True)
        self.status.setText(t("updater.preparing"))
        self.main_btn.setEnabled(False)
        self._started = time.monotonic()
        self._worker = _StageWorker(self.plan, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(lambda: QDialog.reject(self))
        self._worker.start()

    def _on_progress(self, stage, done, total):
        total = max(int(total), 1)
        fraction = min(max(done / total, 0.0), 1.0)
        if stage == "compare":                      # comparing the installed files with the release
            self.bar.setVisible(True)
            self.status.setVisible(True)
            self.bar.setValue(int(fraction * 1000))
            self.status.setText(t("updater.comparing", percent=int(fraction * 100)))
        elif stage == "link":
            self.bar.setValue(int(fraction * 50))
            self.status.setText(t("updater.linking"))
        elif stage == "download":
            elapsed = max(time.monotonic() - self._started, 0.001)
            speed = done / elapsed
            left = (total - done) / speed if speed > 0 else 0
            self.bar.setValue(int(fraction * 700) if not self._delta else 50 + int(fraction * 900))
            self.status.setText(t("updater.downloading", done=format_bytes(done), total=format_bytes(total),
                                  speed=format_bytes(speed), eta=format_eta(left)))
        elif stage == "verify":
            self._delta = False                     # the differential update fell back to the full archive
            self.bar.setValue(710)
            self.status.setText(t("updater.verifying"))
        else:
            self._delta = False
            self.bar.setValue(720 + int(fraction * 280))
            self.status.setText(t("updater.unpacking", percent=int(fraction * 100)))

    def _on_done(self, staged):
        self.staged = staged
        self.bar.setValue(1000)
        self.status.setVisible(False)
        self.text.setText(t("updater.ready"))
        self.cancel_btn.setText(t("updater.later"))
        self.main_btn.setText(t("updater.restart"))
        self.main_btn.setMinimumWidth(self.main_btn.sizeHint().width())
        self.main_btn.updateGeometry()
        self.layout().activate()
        self.main_btn.setEnabled(True)
        self.main_btn.clicked.disconnect()
        self.main_btn.clicked.connect(self._restart)

    def _restart(self):
        """Hand over to the helper script and quit; it swaps the files and starts the new version."""
        try:
            updater.apply_update_and_restart(self.staged)
        except UpdateError as e:
            self._on_failed(e.code, e.params)
            return
        except Exception as e:
            logger.exception("Could not start the update helper")
            self._on_failed("generic", {"error": str(e)})
            return
        QApplication.instance().quit()

    # ------------------------------------------------------------ closing
    def reject(self):
        for worker in (self._plan_worker, self._worker):
            if worker is not None and worker.isRunning():
                worker.cancel()                     # the next chunk notices it; the partial download is kept
                self.cancel_btn.setEnabled(False)
                self.status.setVisible(True)
                self.status.setText(t("updater.cancelling"))
                return                              # closes itself from the `cancelled` signal
        super().reject()

    def done(self, result):
        for worker in (self._plan_worker, self._worker):
            if worker is not None and worker.isRunning():
                worker.cancel()
                worker.wait(10000)
        super().done(result)


def install_staged(parent=None):
    """Install an update that was downloaded earlier ("Later"). Returns True when the app is about to quit."""
    staged = updater.staged_update()
    if staged is None:
        return False
    try:
        updater.apply_update_and_restart(staged)
    except UpdateError as e:
        MessageBox.critical(parent, t("common.error"), error_text(e.code, e.params))
        return False
    QApplication.instance().quit()
    return True