"""Shows the license and terms of use, to read them from the settings or to accept them at the first start."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout

from common import license_terms

from . import styles
from .i18n import t


class LicenseDialog(QDialog):
    def __init__(self, parent=None, ask_to_accept=False):
        super().__init__(parent)
        self.setWindowTitle(t("license.title"))
        self.resize(680, 600)
        layout = QVBoxLayout(self)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(license_terms.read_terms())
        layout.addWidget(text)

        buttons = QHBoxLayout()
        buttons.addStretch()
        reject = QPushButton(t("license.decline") if ask_to_accept else t("license.close"))
        reject.setFixedHeight(42)
        reject.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        reject.setCursor(Qt.PointingHandCursor)
        reject.clicked.connect(self.reject)
        buttons.addWidget(reject)
        if ask_to_accept:
            accept = QPushButton(t("license.accept"))
            accept.setFixedHeight(42)
            accept.setStyleSheet(styles.BLUE_BUTTON_STYLE)
            accept.setCursor(Qt.PointingHandCursor)
            accept.clicked.connect(self.accept)
            buttons.addWidget(accept)
        layout.addLayout(buttons)


def ensure_accepted():
    """False when the user does not accept the terms: the app does not start then."""
    if license_terms.is_accepted():
        return True
    if LicenseDialog(ask_to_accept=True).exec() != QDialog.Accepted:
        return False
    license_terms.accept()
    return True
