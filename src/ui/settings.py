import os
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QComboBox, QFileDialog, QMessageBox, QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt
from analysis.modules.llm import config as app_config

from . import styles
from .i18n import t


def _t(key, default):
    """Translate `key`; use the Polish default while the key is missing from i18n."""
    try:
        text = t(key)
    except Exception:
        return default
    return default if not text or text == key else text


class SettingsDialog(QDialog):
    """Okno dialogowe do zarządzania plikiem app_config.json"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("settings.window_title"))
        self.setFixedSize(540, 420)
        
        self.config_path = app_config.APP_CONFIG_PATH
        
        self.setup_ui()
        self.load_config()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        title_label = QLabel(t("settings.header"))
        title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;"
        )
        main_layout.addWidget(title_label)

        form_group = QGroupBox(t("settings.group"))
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(12)

        dir_layout = QHBoxLayout()
        self.input_model_dir = QLineEdit()
        self.input_model_dir.setPlaceholderText(t("settings.model_dir_placeholder"))
        btn_browse = QPushButton(t("settings.browse"))
        btn_browse.setFixedWidth(120)
        btn_browse.setFixedHeight(40)
        btn_browse.setStyleSheet(styles.GRAY_BUTTON_STYLE + "QPushButton { padding: 0 12px; }")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.input_model_dir)
        dir_layout.addWidget(btn_browse)
        form_layout.addRow(QLabel(t("settings.model_dir")), dir_layout)

        self.combo_device = QComboBox()
        self.combo_device.addItems(["cuda", "cpu"])
        form_layout.addRow(QLabel(t("settings.device")), self.combo_device)

        self.input_gpu_layers = QLineEdit()
        self.input_gpu_layers.setPlaceholderText(t("settings.gpu_layers_placeholder"))
        form_layout.addRow(QLabel(t("settings.gpu_layers")), self.input_gpu_layers)

        self.combo_language = QComboBox()
        self.combo_language.addItems(["pl", "en"])
        form_layout.addRow(QLabel(t("settings.default_language")), self.combo_language)

        main_layout.addWidget(form_group)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton(t("settings.save"))
        btn_save.setFixedHeight(42)
        btn_save.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.clicked.connect(self.save_config)

        btn_cancel = QPushButton(t("common.cancel"))
        btn_cancel.setFixedHeight(42)
        btn_cancel.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        main_layout.addLayout(btn_layout)

    def browse_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, t("settings.choose_model_dir"))
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
            QMessageBox.critical(self, t("common.error"), t("settings.save_failed", error=str(e)))
            return

        QMessageBox.information(
            self, t("common.success"),
            t("settings.saved", path=self.config_path) + "\n\n"
            + _t("settings.restart_note",
                 "Zmiana urządzenia lub liczby warstw GPU zadziała po ponownym uruchomieniu aplikacji."),
        )
        self.accept()