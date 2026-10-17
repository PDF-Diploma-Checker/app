import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLayout, QFrame, QListView, QStyledItemDelegate,
    QPushButton, QLineEdit, QComboBox, QFileDialog,
)
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from analysis.modules.llm import config as app_config

from . import icons, styles
from .i18n import t
from .message_box import MessageBox

CONTROL_WIDTH = 150
CONTROL_HEIGHT = 40


def _plain_label(text):
    """The phrase tables keep a trailing colon ("Katalog modeli (model_dir):"); rows here don't need it."""
    return text.rstrip(": ")


def _field_style():
    """Local additions to the global style: a visible chevron on combo boxes and a fixed field height."""
    chevron = icons.png_path("chevron-down", styles.TEXT_2, 12, 2.5)
    return (
        f"QLineEdit, QComboBox {{ min-height: {CONTROL_HEIGHT - 20}px; }}"
        "QComboBox { padding-right: 30px; }"
        "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right;"
        " width: 30px; border: none; }"
        f"QComboBox::down-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}"
        f"QComboBox QAbstractItemView {{ background-color: {styles.SURFACE}; border: 1px solid {styles.BORDER_STRONG};"
        f" border-radius: 10px; padding: 4px; outline: none; }}"
        f"QComboBox QAbstractItemView::item {{ min-height: 32px; padding: 0 10px; border-radius: 6px;"
        f" color: {styles.TEXT}; }}"
        f"QComboBox QAbstractItemView::item:hover {{ background-color: {styles.NEUTRAL_BG}; }}"
        f"QComboBox QAbstractItemView::item:selected {{ background-color: {styles.PRIMARY_50};"
        f" color: {styles.TEXT}; }}"
    )


def _separator():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background-color: {styles.BORDER}; border: none;")
    return line


class DropdownCombo(QComboBox):
    """QComboBox whose list opens neatly below the field.

    Fusion opens the list on top of the field and draws a square frame behind our rounded list.
    This opens it just under the field (or above it when there is no room) with a transparent frame."""

    GAP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView())
        # the default combo delegate ignores the ::item rules (row heights/padding), a styled one honours them
        self.setItemDelegate(QStyledItemDelegate(self))
        container = self.view().window()
        container.setWindowFlags(
            container.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )
        container.setAttribute(Qt.WA_TranslucentBackground, True)
        container.setStyleSheet(
            "QComboBoxPrivateContainer { background: transparent; border: none; margin: 0; padding: 0; }"
        )

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        view = self.view()
        view.doItemsLayout()  # recompute row heights now that the ::item rules apply
        view.scrollToTop()
        # size the list to its rows (+ the view's padding and border) so no row is cut off
        rows = min(self.count(), self.maxVisibleItems())
        view.setFixedHeight(rows * view.sizeHintForRow(0) + 2 * 5 + 2)
        popup.adjustSize()
        # the transparent frame around the view has its own margin: compensate so the visible gap is GAP
        top_margin = view.geometry().y()
        bottom_margin = popup.height() - view.geometry().bottom() - 1
        pos = self.mapToGlobal(QPoint(0, self.height() + self.GAP - top_margin))
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if pos.y() + popup.height() > screen.availableGeometry().bottom():
            pos = self.mapToGlobal(QPoint(0, -popup.height() - self.GAP + bottom_margin))
        popup.move(pos)
        popup.setFixedWidth(self.width())


class SettingsDialog(QDialog):
    """Okno dialogowe do zarządzania plikiem app_config.json"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setWindowTitle(t("settings.window_title"))
        self.setFixedWidth(640)
        self.setStyleSheet(
            f"QDialog#SettingsDialog {{ background-color: {styles.SURFACE}; }}" + _field_style()
        )

        self.config_path = app_config.APP_CONFIG_PATH

        self.setup_ui()
        self.load_config()
        # height follows the content (wrapped descriptions differ per language)
        self.setFixedHeight(self.layout().totalHeightForWidth(self.width()))

    # ------------------------------------------------------------ building
    def _row(self, title, description, control, stacked=False):
        """One setting: title + description on the left, the control on the right (or underneath)."""
        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        title_label = QLabel(_plain_label(title))
        title_label.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;"
        )
        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(styles.HINT_STYLE)
        text_col.addWidget(title_label)
        text_col.addWidget(desc_label)

        if stacked:
            box = QVBoxLayout()
            box.setSpacing(12)
            box.addLayout(text_col)
            if isinstance(control, QLayout):
                box.addLayout(control)
            else:
                box.addWidget(control)
            return box

        box = QHBoxLayout()
        box.setSpacing(24)
        box.addLayout(text_col, 1)
        if isinstance(control, QLayout):
            box.addLayout(control)
        else:
            box.addWidget(control, 0, Qt.AlignVCenter)
        return box

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(32, 28, 32, 24)
        main_layout.setSpacing(0)

        title_label = QLabel(t("settings.header"))
        title_label.setStyleSheet(
            f"font-size: 22px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;"
        )
        subtitle_label = QLabel(t("settings.subtitle"))
        subtitle_label.setWordWrap(True)
        subtitle_label.setStyleSheet(styles.SUBTITLE_STYLE)
        main_layout.addWidget(title_label)
        main_layout.addSpacing(6)
        main_layout.addWidget(subtitle_label)
        main_layout.addSpacing(24)

        section_label = QLabel(t("settings.group"))
        section_label.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {styles.TEXT_3}; background: transparent; border: none;"
        )
        main_layout.addWidget(section_label)
        main_layout.addSpacing(10)
        main_layout.addWidget(_separator())
        main_layout.addSpacing(20)

        # model directory: a path needs the full width, so it sits under its description
        self.input_model_dir = QLineEdit()
        self.input_model_dir.setPlaceholderText(t("settings.model_dir_placeholder"))
        self.input_model_dir.setFixedHeight(CONTROL_HEIGHT)
        btn_browse = QPushButton("  " + t("settings.browse"))
        btn_browse.setIcon(icons.icon("folder", styles.TEXT_3, 16, 2.0))
        btn_browse.setFixedHeight(CONTROL_HEIGHT)
        btn_browse.setMinimumWidth(CONTROL_WIDTH)
        btn_browse.setStyleSheet(styles.GRAY_BUTTON_STYLE + "QPushButton { padding: 0 14px; }")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self.browse_directory)
        dir_layout = QHBoxLayout()
        dir_layout.setSpacing(10)
        dir_layout.addWidget(self.input_model_dir, 1)
        dir_layout.addWidget(btn_browse)
        main_layout.addLayout(
            self._row(t("settings.model_dir"), t("settings.model_dir_desc"), dir_layout, stacked=True)
        )
        main_layout.addSpacing(24)

        self.combo_device = DropdownCombo()
        self.combo_device.addItems(["cuda", "cpu"])
        self.combo_device.setFixedSize(CONTROL_WIDTH, CONTROL_HEIGHT)
        main_layout.addLayout(self._row(t("settings.device"), t("settings.device_desc"), self.combo_device))
        main_layout.addSpacing(24)

        self.input_gpu_layers = QLineEdit()
        self.input_gpu_layers.setPlaceholderText(t("settings.gpu_layers_placeholder"))
        self.input_gpu_layers.setFixedSize(CONTROL_WIDTH, CONTROL_HEIGHT)
        main_layout.addLayout(
            self._row(t("settings.gpu_layers"), t("settings.gpu_layers_desc"), self.input_gpu_layers)
        )
        main_layout.addSpacing(24)

        self.combo_language = DropdownCombo()
        self.combo_language.addItems(["pl", "en"])
        self.combo_language.setFixedSize(CONTROL_WIDTH, CONTROL_HEIGHT)
        main_layout.addLayout(
            self._row(t("settings.default_language"), t("settings.default_language_desc"), self.combo_language)
        )

        main_layout.addSpacing(28)
        main_layout.addWidget(_separator())
        main_layout.addSpacing(20)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_save = QPushButton(t("settings.save"))
        btn_save.setFixedHeight(42)
        btn_save.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setDefault(True)
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
            MessageBox.critical(self, t("common.error"), t("settings.save_failed", error=str(e)))
            return

        MessageBox.information(
            self, t("common.success"),
            t("settings.saved", path=self.config_path) + "\n\n"
            + t("settings.restart_note"),
        )
        self.accept()