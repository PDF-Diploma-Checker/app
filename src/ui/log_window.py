"""Read-only window streaming live log output.
A QTimer on the GUI thread drains the shared log queue so widgets are never touched from other threads."""

import logging
import queue

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, QLabel

from common.logging_setup import get_log_queue, get_log_file_path

POLL_INTERVAL_MS = 200
MAX_BLOCK_COUNT = 5000


class LogWindow(QDialog):
    """Non-modal window that streams the live log queue into a text view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Logi aplikacji")
        self.resize(800, 500)

        self._queue = get_log_queue()

        layout = QVBoxLayout(self)

        self.text_view = QPlainTextEdit(self)
        self.text_view.setReadOnly(True)
        self.text_view.setMaximumBlockCount(MAX_BLOCK_COUNT)
        self.text_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.text_view)

        self.path_label = QLabel(f"Plik logu: {get_log_file_path()}", self)
        self.path_label.setStyleSheet("color: #666;")
        layout.addWidget(self.path_label)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._drain_queue)
        self._timer.start()

    def _drain_queue(self):
        """Pull every record currently waiting in the queue and append it."""

        appended = False

        while True:
            try:
                record = self._queue.get_nowait()
            except queue.Empty:
                break

            if isinstance(record, logging.LogRecord):
                # QueueHandler.prepare() already baked the formatted text into record.msg.
                text = record.getMessage()
            else:
                text = str(record)

            self.text_view.appendPlainText(text)
            appended = True

        if appended:
            scrollbar = self.text_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
