"""Tells the user about an error nothing else caught, instead of leaving only a line in the log."""

import logging
import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from common.cancellation import AnalysisCancelled
from .i18n import t
from .message_box import MessageBox

logger = logging.getLogger(__name__)


class _Bridge(QObject):
    """Exceptions can come from any thread, a dialog can only be opened on the GUI thread."""

    raised = Signal(str)

    def __init__(self):
        super().__init__()
        self._showing = False
        self.raised.connect(self._show, Qt.QueuedConnection)

    def _show(self, error):
        if self._showing:           # one dialog at a time: errors in a loop must not flood the screen
            return
        self._showing = True
        try:
            MessageBox.critical(QApplication.activeWindow(), t("analysis.unexpected_title"),
                                t("analysis.unexpected_text", error=error))
        except Exception:
            logger.exception("Could not show the error dialog")
        finally:
            self._showing = False


_bridge = None


def _describe(exc_type, exc_value):
    return f"{exc_type.__name__}: {exc_value}"


def install():
    """Wrap the logging exception hooks of common.logging_setup. Call once, after QApplication exists."""
    global _bridge
    if _bridge is not None:
        return
    _bridge = _Bridge()
    log_exception, log_thread_exception = sys.excepthook, threading.excepthook

    def on_exception(exc_type, exc_value, exc_traceback):
        log_exception(exc_type, exc_value, exc_traceback)
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit, AnalysisCancelled)):
            _bridge.raised.emit(_describe(exc_type, exc_value))

    def on_thread_exception(args):
        log_thread_exception(args)
        if not issubclass(args.exc_type, (SystemExit, AnalysisCancelled)):
            _bridge.raised.emit(_describe(args.exc_type, args.exc_value))

    sys.excepthook = on_exception
    threading.excepthook = on_thread_exception
