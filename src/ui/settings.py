import os
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QComboBox, QFileDialog, QMessageBox, QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt

class SettingsDialog(QDialog):
    """Okno dialogowe do zarządzania plikiem app_config.json"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ustawienia aplikacji")
        self.setFixedSize(500, 380)
        
        self.config_dir = Path.home() / ".pdf_diploma_checker"
        self.config_path = self.config_dir / "app_config.json"
        
        self.setup_ui()
        self.load_config()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        title_label = QLabel("Konfiguracja środowiska AI")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        main_layout.addWidget(title_label)

        form_group = QGroupBox("Parametry (app_config.json)")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(12)

        dir_layout = QHBoxLayout()
        self.input_model_dir = QLineEdit()
        self.input_model_dir.setPlaceholderText("np. C:/Users/imie/models")
        btn_browse = QPushButton("Wybierz...")
        btn_browse.setFixedWidth(80)
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.input_model_dir)
        dir_layout.addWidget(btn_browse)
        form_layout.addRow(QLabel("Katalog modeli (model_dir):"), dir_layout)

        self.combo_device = QComboBox()
        self.combo_device.addItems(["cuda", "cpu"])
        form_layout.addRow(QLabel("Urządzenie (device):"), self.combo_device)

        self.input_gpu_layers = QLineEdit()
        self.input_gpu_layers.setPlaceholderText("np. 25")
        form_layout.addRow(QLabel("Warstwy GPU (n_gpu_layers):"), self.input_gpu_layers)

        self.combo_language = QComboBox()
        self.combo_language.addItems(["pl", "en"])
        form_layout.addRow(QLabel("Domyślny język (language):"), self.combo_language)

        main_layout.addWidget(form_group)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Zapisz ustawienia")
        btn_save.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 8px 15px; border-radius: 4px;")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.clicked.connect(self.save_config)

        btn_cancel = QPushButton("Anuluj")
        btn_cancel.setStyleSheet("padding: 8px 15px; border: 1px solid #C4C4C4; border-radius: 4px; background: white;")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        main_layout.addLayout(btn_layout)

    def browse_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Wybierz katalog z modelami AI")
        if dir_path:
            self.input_model_dir.setText(os.path.normpath(dir_path))

    def load_config(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
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
                print(f"Błąd wczytywania konfiguracji: {e}")

    def save_config(self):
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                gpu_layers = int(self.input_gpu_layers.text().strip())
            except ValueError:
                gpu_layers = 25

            config_data = {
                "device": self.combo_device.currentText(),
                "n_gpu_layers": gpu_layers,
                "model_dir": self.input_model_dir.text().strip(),
                "language": self.combo_language.currentText()
            }

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)

            QMessageBox.information(self, "Sukces", f"Zapisano ustawienia w:\n{self.config_path}")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Błąd", f"Nie udało się zapisać pliku: {str(e)}")