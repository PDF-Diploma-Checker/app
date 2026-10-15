"""Email logs, system info and the opened thesis to the developers over SMTP."""

import base64
import binascii
import io
import logging
import smtplib
import ssl
import sys
import zipfile
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout
)

import styles
from common.logging_setup import APP_NAME, get_log_dir, get_log_file_path
from common.system_info import build_system_report
from .i18n import t

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_S = 30
MAX_THESIS_BYTES = 18_000_000


class MailConfigError(Exception):
    """Mail config is missing or invalid; the message is shown to the user."""


def _load_mail_config():
    """Return the config module and decoded password; raise MailConfigError if unusable."""

    try:
        from common import report_mail_config
        password = base64.b64decode(
            report_mail_config.SENDER_PASSWORD_B64, validate=True
        ).decode("utf-8")
    except (ImportError, AttributeError, binascii.Error, UnicodeDecodeError) as e:
        logger.error("Invalid or missing common/report_mail_config.py: %r", e)
        raise MailConfigError(t("report.not_configured")) from e

    if not password:
        logger.error("report_mail_config.SENDER_PASSWORD_B64 is empty")
        raise MailConfigError(t("report.not_configured"))

    return report_mail_config, password


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


def _build_message(config, thesis_path):
    """Build the report email.

    System info is collected once (it spawns subprocesses). The body is set before
    attachments, and a thesis over MAX_THESIS_BYTES is skipped to stay under Gmail's 25 MB limit.
    """

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    msg = EmailMessage()
    msg["Subject"] = f"Zgloszenie problemu - {APP_NAME} - {timestamp}"
    msg["From"] = config.SENDER_EMAIL
    msg["To"] = config.RECIPIENT_EMAIL

    system_info = _build_system_info()
    logger.info("System info for bug report:\n%s", system_info)
    body = system_info
    thesis_bytes = None

    if thesis_path is not None:
        thesis_path = Path(thesis_path)
        size = thesis_path.stat().st_size
        if size > MAX_THESIS_BYTES:
            logger.warning("Thesis too large to attach (%d bytes): %s", size, thesis_path)
            body += f"\nPraca NIE zostala dolaczona - plik za duzy ({size / 1e6:.1f} MB).\n"
        else:
            thesis_bytes = thesis_path.read_bytes()
            body += f"\nDolaczono prace: {thesis_path.name}\n"

    msg.set_content(body)
    msg.add_attachment(
        build_diagnostic_zip(system_info),
        maintype="application",
        subtype="zip",
        filename=f"diploma_checker_logi_{timestamp}.zip",
    )
    if thesis_bytes is not None:
        msg.add_attachment(
            thesis_bytes,
            maintype="application",
            subtype="pdf",
            filename=thesis_path.name,
        )

    return msg


class ReportSender(QObject):
    """Sends the report email off the GUI thread."""

    finished = Signal(bool, str)

    def __init__(self, config, password, thesis_path):
        super().__init__()
        self.config = config
        self.password = password
        self.thesis_path = thesis_path

    def run(self):
        try:
            msg = _build_message(self.config, self.thesis_path)
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                self.config.SMTP_HOST, self.config.SMTP_PORT,
                context=context, timeout=SMTP_TIMEOUT_S,
            ) as server:
                server.login(self.config.SENDER_EMAIL, self.password)
                server.send_message(msg)
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

    def __init__(self, config, password, thesis_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("report.window_title"))
        self.setMinimumWidth(420)

        self.config = config
        self.password = password
        self.thesis_path = thesis_path
        self._thread = None
        self._sender = None

        layout = QVBoxLayout(self)

        info = QLabel(t("report.info"))
        info.setWordWrap(True)
        layout.addWidget(info)

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

    def _send(self):
        """Lock the form and start the worker thread."""
        self.send_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.consent.setEnabled(False)
        self.send_btn.setText(t("report.sending"))

        self._thread = QThread(self)
        self._sender = ReportSender(self.config, self.password, self.thesis_path)
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
            QMessageBox.information(self, t("report.sent_title"), t("report.sent_text"))
            self.accept()
            return

        QMessageBox.warning(
            self,
            t("report.failed_title"),
            t("report.failed_text", error=error),
        )
        self._reset_buttons()

    def _reset_buttons(self):
        self.send_btn.setText(t("report.send"))
        self.send_btn.setEnabled(self.consent.isChecked())
        self.cancel_btn.setEnabled(True)
        self.consent.setEnabled(True)

    def reject(self):
        """Ignore close requests while sending."""
        if self._thread is not None and self._thread.isRunning():
            return
        super().reject()


def send_report(parent=None, thesis_path=None):
    """Show the report dialog for the currently opened PDF, if any."""

    try:
        config, password = _load_mail_config()
    except MailConfigError as e:
        QMessageBox.warning(parent, t("report.unavailable_title"), str(e))
        return

    if thesis_path and not Path(thesis_path).is_file():
        thesis_path = None

    ReportDialog(config, password, thesis_path or None, parent).exec()
