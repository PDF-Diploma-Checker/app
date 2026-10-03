"""Let users get the app's logs back to the developer for troubleshooting.
Zips the logs locally and prefills an email, since mailto: can't attach files itself."""

import logging
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import platformdirs
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from common.logging_setup import APP_NAME, get_log_dir, get_log_file_path

logger = logging.getLogger(__name__)

REPORT_EMAIL = "pdfdiplomachecker@gmail.com"
LOG_TAIL_LINES = 40
LOG_TAIL_MAX_CHARS = 1200


def read_log_tail(log_path, max_lines=LOG_TAIL_LINES, max_chars=LOG_TAIL_MAX_CHARS):
    """Return a short tail of the log file for inline preview in the email body."""

    if not log_path.exists():
        return "(Brak pliku logow - aplikacja nie zapisala jeszcze zadnych wpisow.)"

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.exception("Failed to read log file for report: %s", log_path)
        return "(Nie udalo sie odczytac pliku logow - zalacz go recznie do maila.)"

    tail = "\n".join(text.splitlines()[-max_lines:])

    if len(tail) > max_chars:
        tail = "...(skrocono)...\n" + tail[-max_chars:]

    return tail


def _build_system_info():
    """Build a short text summary of versions useful for diagnosing a report."""

    return (
        f"App: {APP_NAME}\n"
        f"Czas raportu: {datetime.now().isoformat(timespec='seconds')}\n"
        f"System: {platform.platform()}\n"
        f"Python: {platform.python_version()}\n"
        f"PySide6: {pyside_version}\n"
        f"Spakowana (frozen): {getattr(sys, 'frozen', False)}\n"
    )


def _default_export_path():
    """Suggest a Desktop location for the exported diagnostic zip."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    desktop_dir = Path(platformdirs.user_desktop_dir())
    return desktop_dir / f"diploma_checker_logi_{timestamp}.zip"


def build_diagnostic_zip(destination):
    """Collect the log file, its rotated backups, and a system-info file
    into a single zip at `destination`. Returns True if any log file was found."""

    log_dir = get_log_dir()
    log_file = get_log_file_path()

    log_files = sorted(log_dir.glob(f"{log_file.name}*"))

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("info.txt", _build_system_info())
        for f in log_files:
            if f.is_file():
                zf.write(f, arcname=f.name)

    return bool(log_files)


def send_report(parent=None):
    """Save a diagnostic zip (logs + system info) locally, then open the
    user's default email client pre-filled with instructions to attach it."""

    log_path = get_log_file_path()
    log_tail = read_log_tail(log_path)

    suggested_path = _default_export_path()
    zip_path_str, _ = QFileDialog.getSaveFileName(
        parent,
        "Zapisz raport diagnostyczny",
        str(suggested_path),
        "Archiwum ZIP (*.zip)",
    )

    if not zip_path_str:
        return

    zip_path = Path(zip_path_str)

    try:
        build_diagnostic_zip(zip_path)
    except OSError:
        logger.exception("Failed to build diagnostic zip at %s", zip_path)
        if parent is not None:
            QMessageBox.warning(
                parent,
                "Nie udalo sie zapisac raportu",
                f"Nie udalo sie zapisac pliku z logami:\n{zip_path}",
            )
        return

    logger.info("Diagnostic report saved to %s", zip_path)

    subject = "Zgloszenie problemu - Diploma Checker"
    body = (
        "Opisz krotko co sie stalo:\n\n\n"
        "----------------------------------------\n"
        "Prosze zalacz do tego maila plik z logami, ktory zapisany zostal tutaj:\n"
        f"{zip_path}\n"
        "(mailto: nie potrafi dolaczac zalacznikow automatycznie - dolacz go recznie)\n"
        "----------------------------------------\n\n"
        "Ostatnie wpisy z logu (podglad):\n\n"
        f"{log_tail}\n"
    )

    mailto_url = QUrl(f"mailto:{REPORT_EMAIL}?subject={quote(subject)}&body={quote(body)}")
    opened = QDesktopServices.openUrl(mailto_url)

    QDesktopServices.openUrl(QUrl.fromLocalFile(str(zip_path.parent)))

    if not opened:
        logger.warning("Failed to open default email client for bug report")

    # QDesktopServices.openUrl() on Linux can report success even when no
    # mailto: handler is registered (the failure happens later, in a
    # detached process) - always show the manual fallback instructions.
    if parent is not None:
        QMessageBox.information(
            parent,
            "Raport zapisany",
            f"Plik z raportem zostal zapisany tutaj:\n{zip_path}\n\n"
            "Jesli program pocztowy sie nie otworzyl, wyslij ten plik "
            f"recznie na adres: {REPORT_EMAIL}",
        )
