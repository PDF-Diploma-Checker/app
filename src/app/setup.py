import sys
import os
import subprocess
import threading
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QProgressBar, QLineEdit, QComboBox, QFileDialog, QMessageBox, QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt, Signal, Slot

from analysis.modules.llm.config import (
    APP_CONFIG_PATH, are_ai_models_downloaded, 
    download_specific_language, download_ai_models_with_progress, check_and_download_requirements
)

class SetupWizard(QDialog):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Konfiguracja Diploma Checker - Instalator i Ustawienia")
        self.setFixedSize(600, 520)
    
        self.progress_signal.connect(self.update_ui)
        self.finished_signal.connect(self.on_finished)
        
        self.setup_ui()
        self.load_existing_config()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        title_label = QLabel("Ustawienia środowiska i pobieranie modeli AI")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        main_layout.addWidget(title_label)

        # Grupa ustawień parametrów
        form_group = QGroupBox("Parametry konfiguracji (app_config.json)")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(10)

        dir_layout = QHBoxLayout()
        self.input_model_dir = QLineEdit()
        self.input_model_dir.setPlaceholderText("np. C:/Users/Wiktor/models lub /home/natalia/models")
        btn_browse_dir = QPushButton("Wybierz...")
        btn_browse_dir.setFixedWidth(80)
        btn_browse_dir.clicked.connect(self.browse_model_dir)
        dir_layout.addWidget(self.input_model_dir)
        dir_layout.addWidget(btn_browse_dir)
        form_layout.addRow(QLabel("Katalog modeli (model_dir):"), dir_layout)

        self.combo_device = QComboBox()
        self.combo_device.addItems(["cuda", "cpu"])
        form_layout.addRow(QLabel("Urządzenie obliczeniowe (device):"), self.combo_device)

        self.input_gpu_layers = QLineEdit()
        self.input_gpu_layers.setPlaceholderText("np. 25")
        form_layout.addRow(QLabel("Warstwy GPU (n_gpu_layers):"), self.input_gpu_layers)

        self.combo_language = QComboBox()
        self.combo_language.addItems(["pl", "en"])
        form_layout.addRow(QLabel("Język domyślny (language):"), self.combo_language)

        main_layout.addWidget(form_group)

        self.pbar = QProgressBar()
        self.pbar.setValue(0)
        main_layout.addWidget(self.pbar)

        self.label_status = QLabel("Status: Gotowy do konfiguracji.")
        main_layout.addWidget(self.label_status)

        btn_layout = QHBoxLayout()
        self.btn_run = QPushButton("Zapisz ustawienia")
        self.btn_run.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 10px; border-radius: 4px;")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self.start_logic)

        btn_cancel = QPushButton("Zamknij")
        btn_cancel.setStyleSheet("padding: 10px 15px; border: 1px solid #C4C4C4; border-radius: 4px; background: white;")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_run)
        main_layout.addLayout(btn_layout)

    def browse_model_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Wybierz katalog z modelami AI")
        if dir_path:
            self.input_model_dir.setText(os.path.normpath(dir_path))

    def load_existing_config(self):
        if APP_CONFIG_PATH.exists():
            try:
                with open(APP_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.input_model_dir.setText(data.get("model_dir", ""))
                    
                    device = data.get("device", "cuda")
                    idx = self.combo_device.findText(device)
                    if idx >= 0: self.combo_device.setCurrentIndex(idx)
                    
                    self.input_gpu_layers.setText(str(data.get("n_gpu_layers", 25)))
                    
                    lang = data.get("language", "pl")
                    idx_lang = self.combo_language.findText(lang)
                    if idx_lang >= 0: self.combo_language.setCurrentIndex(idx_lang)
            except Exception as e:
                print(f"[SETUP] Błąd wczytywania konfiguracji: {e}")

    def start_logic(self):
        self.btn_run.setEnabled(False)
        
        try:
            APP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            try:
                gpu_layers = int(self.input_gpu_layers.text().strip())
            except ValueError:
                gpu_layers = 25

            config_data = {
                "device": self.combo_device.currentText(),
                "n_gpu_layers": gpu_layers,
                "model_dir": self.input_model_dir.text().strip(),
                "language": self.combo_language.currentText(),
                "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2"
            }

            with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            QMessageBox.critical(self, "Błąd", f"Nie udało się zapisać konfiguracji: {str(e)}")
            self.btn_run.setEnabled(True)
            return

        should_download = False
        if not are_ai_models_downloaded():
            reply = QMessageBox.question(
                self,
                "Brak modeli AI",
                "W wybranym katalogu nie znaleziono wymaganych modeli AI (Gemma i LLaVA - ok. 8GB).\n"
                "Czy chcesz pobrać je teraz?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                should_download = True

        threading.Thread(target=self.run_install_process, args=(should_download,), daemon=True).start()

    def run_install_process(self, should_download):
        try:
            self.progress_signal.emit(10, "Sprawdzanie środowiska Java...")
            try:
                subprocess.run(["java", "-version"], check=True, capture_output=True)
            except Exception:
                self.progress_signal.emit(15, "Ostrzeżenie: Java nie została wykryta.")

            self.progress_signal.emit(30, "Sprawdzanie pakietów językowych SpaCy (PL/EN)...")
            download_specific_language()

            if should_download:
                self.progress_signal.emit(50, "Pobieranie brakujących modeli AI... Może to potrwać.")
                download_ai_models_with_progress(lambda p, msg: self.progress_signal.emit(p, msg))
            else:
                self.progress_signal.emit(85, "Pobieranie modeli AI zostało pominięte przez użytkownika.")

            self.progress_signal.emit(100, "Konfiguracja zakończona pomyślnie!")
            self.finished_signal.emit(True, "Ustawienia zostały zapisane pomyślnie.")

        except Exception as e:
            self.finished_signal.emit(False, f"Wystąpił błąd:\n{str(e)}")

    @Slot(int, str)
    def update_ui(self, val, msg):
        self.pbar.setValue(val)
        self.label_status.setText(msg)

    @Slot(bool, str)
    def on_finished(self, success, msg):
        if success:
            QMessageBox.information(self, "Sukces", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "Błąd", msg)
            self.btn_run.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    wizard = SetupWizard()
    wizard.show()
    sys.exit(app.exec())