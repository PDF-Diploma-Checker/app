"""Shows the license agreement, to read it from the settings or to accept it at the first start."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout

from common import eula

from . import styles
from .i18n import t


class EulaDialog(QDialog):
    def __init__(self, parent=None, ask_to_accept=False):
        super().__init__(parent)
        self.setWindowTitle(t("eula.title"))
        self.resize(680, 600)
        layout = QVBoxLayout(self)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(eula.read_eula())
        layout.addWidget(text)

        buttons = QHBoxLayout()
        buttons.addStretch()
        reject = QPushButton(t("eula.decline") if ask_to_accept else t("eula.close"))
        reject.setFixedHeight(42)
        reject.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        reject.setCursor(Qt.PointingHandCursor)
        reject.clicked.connect(self.reject)
        buttons.addWidget(reject)
        if ask_to_accept:
            accept = QPushButton(t("eula.accept"))
            accept.setFixedHeight(42)
            accept.setStyleSheet(styles.BLUE_BUTTON_STYLE)
            accept.setCursor(Qt.PointingHandCursor)
            accept.clicked.connect(self.accept)
            buttons.addWidget(accept)
        layout.addLayout(buttons)


def ensure_accepted():
    """False when the user does not accept the agreement: the app does not start then."""
    if eula.is_accepted():
        return True
    if EulaDialog(ask_to_accept=True).exec() != QDialog.Accepted:
        return False
    eula.accept()
    return True
