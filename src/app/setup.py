import sys
import os
import subprocess
import threading
import json
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QLabel, 
                             QProgressBar, QPushButton, QCheckBox, QMessageBox)
from PySide6.QtCore import Qt, Signal, Slot
from huggingface_hub import hf_hub_download

class SetupWizard(QDialog):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Konfiguracja Diploma Checker")
        self.setFixedSize(500, 300)
    
        self.progress_signal.connect(self.update_ui)
        self.finished_signal.connect(self.on_finished)
        
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.label = QLabel("Inicjalizacja środowiska...")
        layout.addWidget(self.label)

        self.cb_models = QCheckBox("Pobierz ciężkie modele AI (Gemma/LLaVA - ok. 8GB)")
        layout.addWidget(self.cb_models)

        self.pbar = QProgressBar()
        layout.addWidget(self.pbar)

        self.btn_run = QPushButton("Rozpocznij instalację")
        self.btn_run.clicked.connect(self.start_logic)
        layout.addWidget(self.btn_run)

    def start_logic(self):
        self.btn_run.setEnabled(False)
        self.cb_models.setEnabled(False)
        threading.Thread(target=self.run_install, daemon=True).start()

    def run_install(self):
        try:
            self.progress_signal.emit(10, "Sprawdzanie Javy...")
            if subprocess.run(["which", "java"], capture_output=True).returncode != 0:
                self.progress_signal.emit(20, "Instalowanie Javy (może prosić o hasło sudo)...")
                subprocess.run(["sudo", "apt", "update"], check=True)
                subprocess.run(["sudo", "apt", "install", "-y", "openjdk-17-jre"], check=True)

            self.progress_signal.emit(50, "Pobieranie modeli językowych SpaCy...")
            subprocess.run([sys.executable, "-m", "spacy", "download", "pl_core_news_lg"], check=True)
            subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_lg"], check=True)

            if self.cb_models.isChecked():
                self.progress_signal.emit(70, "Pobieranie modelu Gemma 3 (ok. 8GB)...")
                target_dir = Path.home() / "models"
                
                # Pobieranie modelu Gemma 3
                hf_hub_download(
                    repo_id="nocturne23/gemma-3-12b-it-Q4_K_M-GGUF",
                    filename="gemma-3-12b-it-q4_k_m.gguf",
                    local_dir=str(target_dir / "gemma3_12b")
                )
                hf_hub_download(
                    repo_id="cjpais/llava-1.6-mistral-7b-gguf",
                    filename="llava-v1.6-mistral-7b.Q4_K_M.gguf",
                    local_dir=str(target_dir)
                )
                hf_hub_download(
                    repo_id="cjpais/llava-1.6-mistral-7b-gguf",
                    filename="mmproj-model-f16.gguf",
                    local_dir=str(target_dir)
                )
                
                self.progress_signal.emit(90, "Model został pobrany pomyślnie.")

            config_dir = Path.home() / ".pdf_diploma_checker"
            config_dir.mkdir(exist_ok=True)
            with open(config_dir / "app_config.json", "w") as f:
                json.dump({"status": "installed", "path": os.getcwd()}, f)

            self.finished_signal.emit(True, "Środowisko gotowe!")

        except Exception as e:
            self.finished_signal.emit(False, f"Błąd instalacji: {str(e)}")

    @Slot(int, str)
    def update_ui(self, val, msg):
        self.pbar.setValue(val)
        self.label.setText(msg)

    @Slot(bool, str)
    def on_finished(self, success, msg):
        if success:
            QMessageBox.information(self, "Sukces", msg)
            self.close()
        else:
            QMessageBox.critical(self, "Błąd", msg)
            self.btn_run.setEnabled(True)
            self.cb_models.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    wizard = SetupWizard()
    wizard.show()
    sys.exit(app.exec())