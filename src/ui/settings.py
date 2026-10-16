import os
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QComboBox, QFileDialog, QMessageBox, QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt
from analysis.modules.llm import config as app_config

class SettingsDialog(QDialog):
    """Okno dialogowe do zarządzania plikiem app_config.json"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ustawienia aplikacji")
        self.setFixedSize(500, 380)
        
        self.config_path = app_config.APP_CONFIG_PATH
        
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
        data = app_config.load_config()
        self.input_model_dir.setText(data.get("model_dir", ""))
        idx = self.combo_device.findText(data.get("device", "cpu"))
        if idx >= 0:
            self.combo_device.setCurrentIndex(idx)
        self.input_gpu_layers.setText(str(data.get("n_gpu_layers", 0)))
        idx = self.combo_language.findText(data.get("language", "pl"))
        if idx >= 0:
            self.combo_language.setCurrentIndex(idx)


    def save_config(self):
        try:
            gpu_layers = int(self.input_gpu_layers.text().strip())
        except ValueError:
            gpu_layers = 25

        data = app_config.load_config()
        data.update({
            "device": self.combo_device.currentText(),
            "n_gpu_layers": gpu_layers,
            "model_dir": self.input_model_dir.text().strip(),
            "language": self.combo_language.currentText(),
        })
        try:
            app_config.save_config(data)
            app_config.reload_config()
        except Exception as e:
            QMessageBox.critical(self, "Błąd", f"Nie udało się zapisać pliku: {e}")
            return

        QMessageBox.information(
            self, "Sukces",
            f"Zapisano ustawienia w:\n{self.config_path}\n\n"
            "Zmiana urządzenia lub liczby warstw GPU zadziała po ponownym uruchomieniu aplikacji.",
        )
        self.accept()