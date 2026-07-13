import sys
import os
import subprocess

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

from PySide6.QtWidgets import QApplication
from ui.main_window import PDFReader

def check_installation():
    config_path = os.path.join(os.path.expanduser("~"), ".pdf_diploma_checker", "app_config.json")
    
    if not os.path.exists(config_path):
        print("Uruchamianie instalatora...")
        subprocess.run([sys.executable, os.path.join(APP_DIR, "setup.py")])
        if not os.path.exists(config_path):
            return False
    return True

def main():
    if not check_installation():
        sys.exit()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = PDFReader()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()