import sys
import os
import logging

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    SRC_DIR = os.path.join(BASE_DIR, "src")
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    SRC_DIR = os.path.join(BASE_DIR, "src")

UI_DIR = os.path.join(SRC_DIR, "ui")
APP_DIR = os.path.join(SRC_DIR, "app")
COMMON_DIR = os.path.join(SRC_DIR, "common")

for path in [SRC_DIR, UI_DIR, APP_DIR, COMMON_DIR, BASE_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

from common.logging_setup import configure_logging

# Configured once, before the Qt/main window imports below.
log_file = configure_logging()
logger = logging.getLogger(__name__)

from PySide6.QtWidgets import QApplication
from ui.main_window import PDFReader
from setup import check_and_download_requirements


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        check = check_and_download_requirements()
    except Exception:
        logger.exception("Failed while checking/downloading requirements")
        raise
    if not check:
        logger.warning("Requirement check failed, exiting before window creation")
        sys.exit()
    window = PDFReader()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Unhandled exception, application terminating")
        raise
