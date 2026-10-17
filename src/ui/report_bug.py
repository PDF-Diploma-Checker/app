"""Send logs, system info and the opened thesis to the developers through the report relay.

The app never holds mail credentials: it POSTs the report to a small relay (a Cloudflare Worker)
that checks size and rate limits and forwards it by e-mail. See relay/README.md.
"""

import io
import logging
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from . import styles
from .i18n import t
from .message_box import MessageBox, fit_minimum_height
from common.logging_setup import APP_NAME, get_log_dir, get_log_file_path
from common.system_info import build_system_report

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = (10, 120)        # connect, read
MAX_THESIS_BYTES = 10_000_000        # keep in sync with MAX_THESIS_BYTES in relay/src/index.js
MAX_USER_MESSAGE_CHARS = 3000

# relay error code -> translation key
_ERROR_KEYS = {
    "ip_limit": "report.err_ip_limit",
    "daily_limit": "report.err_daily_limit",
    "too_large": "report.err_too_large",
    "thesis_too_large": "report.err_too_large",
}


class ReportConfigError(Exception):
    """The relay address is missing or invalid; the message is shown to the user."""


class ReportError(Exception):
    """Sending failed; the message is shown to the user."""


def _load_report_url():
    """Return the relay URL from common/report_config.py; raise ReportConfigError if unusable."""

    try:
        from common import report_config
        url = (report_config.REPORT_URL or "").strip()
    except (ImportError, AttributeError) as e:
        logger.error("Invalid or missing common/report_config.py: %r", e)
        raise ReportConfigError(t("report.not_configured")) from e

    local = url.lower().startswith(("http://127.0.0.1", "http://localhost"))   # for testing only
    if not (url.lower().startswith("https://") or local):
        logger.error("report_config.REPORT_URL is empty or not https")
        raise ReportConfigError(t("report.not_configured"))

    # the relay answers only on /report: add it when the address was given without a path
    parts = urlparse(url)
    if parts.path in ("", "/"):
        url = urlunparse(parts._replace(path="/report"))

    return url


def _build_system_info():
    """Return app and system details for the report."""

    return (
        f"App: {APP_NAME}\n"
        f"Czas raportu: {datetime.now().isoformat(timespec='seconds')}\n"
        f"PySide6: {pyside_version}\n"
        f"Spakowana (frozen): {getattr(sys, 'frozen', False)}\n"
        f"{build_system_report()}"
    )


def build_diagnostic_zip(system_info):
    """Return zip bytes with the log files and info.txt."""

    log_dir = get_log_dir()
    log_file = get_log_file_path()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("info.txt", system_info)
        for f in sorted(log_dir.glob(f"{log_file.name}*")):
            if f.is_file():
                zf.write(f, arcname=f.name)

    return buffer.getvalue()


def _error_text(status, response):
    """User-facing text for a non-200 answer of the relay."""

    try:
        code = response.json().get("error", "")
    except (ValueError, AttributeError):
        code = ""
    key = _ERROR_KEYS.get(code)
    if key:
        return t(key)
    return t("report.err_server", code=status)


def _post_report(url, thesis_path, user_message):
    """Collect the report and POST it to the relay. Raises ReportError on failure."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    system_info = _build_system_info()
    logger.info("System info for bug report:\n%s", system_info)

    files = {}
    thesis_note = ""
    if thesis_path is not None:
        thesis_path = Path(thesis_path)
        size = thesis_path.stat().st_size
        if size > MAX_THESIS_BYTES:
            logger.warning("Thesis too large to attach (%d bytes): %s", size, thesis_path)
            thesis_note = f"\nPraca NIE zostala dolaczona - plik za duzy ({size / 1e6:.1f} MB).\n"
        else:
            files["thesis"] = (thesis_path.name, thesis_path.read_bytes(), "application/pdf")

    files["logs"] = (
        f"diploma_checker_logi_{timestamp}.zip",
        build_diagnostic_zip(system_info),
        "application/zip",
    )
    data = {
        "consent": "1",   # the dialog only sends after the user ticked the consent box
        "message": (user_message or "").strip(),
        "system_info": system_info + thesis_note,
    }

    try:
        response = requests.post(
            url, data=data, files=files, timeout=REQUEST_TIMEOUT_S,
            headers={"User-Agent": f"{APP_NAME}-report"},
        )
    except requests.Timeout as e:
        raise ReportError(t("report.err_timeout")) from e
    except requests.RequestException as e:
        logger.warning("Report request failed: %r", e)
        raise ReportError(t("report.err_network")) from e

    if response.status_code != 200:
        logger.warning("Relay %s answered %s: %s", url, response.status_code, response.text[:200])
        raise ReportError(_error_text(response.status_code, response))


class ReportSender(QObject):
    """Sends the report off the GUI thread."""

    finished = Signal(bool, str)

    def __init__(self, url, thesis_path, user_message=""):
        super().__init__()
        self.url = url
        self.thesis_path = thesis_path
        self.user_message = user_message

    def run(self):
        try:
            _post_report(self.url, self.thesis_path, self.user_message)
        except ReportError as e:
            self.finished.emit(False, str(e))
            return
        except Exception as e:
            logger.exception("Failed to send bug report")
            self.finished.emit(False, str(e))
            return

        logger.info("Bug report sent (thesis attached: %s)", self.thesis_path is not None)
        self.finished.emit(True, "")


class ReportDialog(QDialog):
    """Asks for consent, then sends the report.

    The consent text is a separate QLabel because QCheckBox text can't word-wrap.
    """

    def __init__(self, url, thesis_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("report.window_title"))
        self.setMinimumWidth(480)

        self.url = url
        self.thesis_path = thesis_path
        self._thread = None
        self._sender = None

        layout = QVBoxLayout(self)

        info = QLabel(t("report.info"))
        info.setWordWrap(True)
        layout.addWidget(info)

        message_label = QLabel(t("report.message_label"))
        layout.addWidget(message_label)

        self.message_edit = QPlainTextEdit()
        self.message_edit.setPlaceholderText(t("report.message_placeholder"))
        self.message_edit.setMinimumHeight(110)
        self.message_edit.textChanged.connect(self._limit_message)
        layout.addWidget(self.message_edit)

        self.consent = QCheckBox()
        consent_row = QHBoxLayout()
        consent_row.addWidget(self.consent, 0, Qt.AlignTop)
        consent_label = QLabel(t("report.consent"))
        consent_label.setWordWrap(True)
        consent_label.mousePressEvent = lambda _event: self.consent.toggle()
        consent_row.addWidget(consent_label, 1)
        layout.addLayout(consent_row)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.cancel_btn = QPushButton(t("common.cancel"))
        self.cancel_btn.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)

        self.send_btn = QPushButton(t("report.send"))
        self.send_btn.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self._send)
        self.send_btn.setEnabled(False)
        self.consent.toggled.connect(self.send_btn.setEnabled)
        buttons.addWidget(self.send_btn)

        layout.addLayout(buttons)

        fit_minimum_height(self)     # keeps the dialog from shrinking until the texts overlap

    def _limit_message(self):
        """Keep the description within MAX_USER_MESSAGE_CHARS."""
        text = self.message_edit.toPlainText()
        if len(text) > MAX_USER_MESSAGE_CHARS:
            self.message_edit.blockSignals(True)
            self.message_edit.setPlainText(text[:MAX_USER_MESSAGE_CHARS])
            cursor = self.message_edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.message_edit.setTextCursor(cursor)
            self.message_edit.blockSignals(False)

    def _send(self):
        """Lock the form and start the worker thread."""
        self.message_edit.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.consent.setEnabled(False)
        self.send_btn.setText(t("report.sending"))

        self._thread = QThread(self)
        self._sender = ReportSender(self.url, self.thesis_path, self.message_edit.toPlainText())
        self._sender.moveToThread(self._thread)
        self._thread.started.connect(self._sender.run)
        self._sender.finished.connect(self._on_finished)
        self._thread.finished.connect(self._sender.deleteLater)
        self._thread.start()

    def _on_finished(self, ok, error):
        """Stop the worker thread and show the result.

        quit() is called here because a queued quit() would only run after this slot,
        so wait() would deadlock the GUI.
        """
        self._thread.quit()
        if not self._thread.wait(5000):
            logger.warning("Bug report worker thread did not stop in time")

        try:
            self._show_result(ok, error)
        except Exception:
            logger.exception("Failed to show bug report result")
            self._reset_buttons()

    def _show_result(self, ok, error):
        if ok:
            MessageBox.information(self, t("report.sent_title"), t("report.sent_text"))
            self.accept()
            return

        MessageBox.warning(self, t("report.failed_title"), t("report.failed_text", error=error))
        self._reset_buttons()

    def _reset_buttons(self):
        self.send_btn.setText(t("report.send"))
        self.send_btn.setEnabled(self.consent.isChecked())
        self.cancel_btn.setEnabled(True)
        self.consent.setEnabled(True)
        self.message_edit.setEnabled(True)

    def reject(self):
        """Ignore close requests while sending."""
        if self._thread is not None and self._thread.isRunning():
            return
        super().reject()


def send_report(parent=None, thesis_path=None):
    """Show the report dialog for the currently opened PDF, if any."""

    try:
        url = _load_report_url()
    except ReportConfigError as e:
        MessageBox.warning(parent, t("report.unavailable_title"), str(e))
        return

    if thesis_path and not Path(thesis_path).is_file():
        thesis_path = None

    ReportDialog(url, thesis_path or None, parent).exec()
