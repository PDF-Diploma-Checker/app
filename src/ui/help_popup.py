"""The "?" of the reader's toolbar: a small card under the button with what can be done in the document and how
(selecting text, the right-click menu with the plagiarism search, the keyboard shortcuts). Closes on any click
outside or Esc."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from . import motion, styles
from .i18n import t


def _label(text, style, rich=False):
    label = QLabel(text)
    label.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    label.setWordWrap(True)
    label.setStyleSheet(style + " background: transparent; border: none;")
    return label


class HelpPopup(QFrame):
    WIDTH = 380

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("HelpPopup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet(f"QFrame#HelpPopup {{ background-color: {styles.SURFACE}; "
                           f"border: 1px solid {styles.BORDER}; border-radius: 10px; }}")
        self.setFixedWidth(self.WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(6)
        heading = f"font-size: 14px; font-weight: 700; color: {styles.TEXT};"
        body = f"font-size: 13px; color: {styles.TEXT_2};"

        root.addWidget(_label(t("help.select_title"), heading))
        root.addWidget(_label(t("help.select_text"), body))
        root.addSpacing(8)
        root.addWidget(_label(t("help.menu_title"), heading))
        items = "".join(f"<li style='margin-bottom:3px;'>{t(key)}</li>"
                        for key in ("help.menu_copy", "help.menu_plagiarism", "help.menu_comment"))
        root.addWidget(_label(f"<ul style='margin-left:-24px;'>{items}</ul>", body, rich=True))
        root.addWidget(_label(t("help.comment_anywhere"), body))
        root.addSpacing(8)
        root.addWidget(_label(t("help.keys_title"), heading))
        rows = "".join(
            f"<tr><td style='padding:2px 14px 2px 0; color:{styles.TEXT}; white-space:nowrap;'>"
            f"{motion.shortcut_text(key)}</td><td style='padding:2px 0;'>{t(label)}</td></tr>"
            for key, label in (("Ctrl+F", "help.key_find"), ("Ctrl+C", "help.key_copy"),
                               ("Ctrl+K", "help.key_commands"), ("Ctrl+G", "help.key_page"),
                               ("Ctrl+=", "help.key_zoom_in"), ("Ctrl+-", "help.key_zoom_out"),
                               ("Alt+Left", "help.key_back")))
        root.addWidget(_label(f"<table>{rows}</table>", body, rich=True))

    def show_under(self, button):
        """Open below `button`, right-aligned with it, kept on the screen."""
        self.adjustSize()
        point = button.mapToGlobal(QPoint(button.width() - self.width(), button.height() + 6))
        screen = button.screen().availableGeometry()
        point.setX(max(screen.left() + 8, min(point.x(), screen.right() - self.width() - 8)))
        self.move(point)
        self.show()
