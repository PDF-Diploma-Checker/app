"""Message boxes drawn by the app itself, so they look the same on every system.

QMessageBox takes its icons, button captions ("Yes"/"No" in English) and parts of its colours from the operating
system. MessageBox is a drop-in replacement with the same static calls:

    MessageBox.information(parent, title, text)      # also .warning(...) and .critical(...)
    reply = MessageBox.question(parent, title, text, MessageBox.Yes | MessageBox.No, MessageBox.No)
    if reply == MessageBox.Yes: ...
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from . import icons, styles
from .i18n import t

LONG_TEXT_CHARS = 600      # longer messages (e.g. error details) get a scrollable text area


def fit_minimum_height(dialog):
    """Stop a dialog from being resized so small that its widgets overlap.

    Qt works out a dialog's minimum height as if word-wrapped text needed only one line, so a narrow dialog
    can get shorter than its content. Use the height the layout really needs at the minimum width instead.
    Call it once the dialog is fully built."""
    layout = dialog.layout()
    if layout is None or not layout.hasHeightForWidth():
        return
    needed = layout.heightForWidth(dialog.minimumWidth())
    dialog.setMinimumHeight(max(dialog.minimumSizeHint().height(), needed))


class MessageBox(QDialog):
    Ok = 1
    Yes = 2
    No = 4

    # kind -> (icon name, icon colour, circle background)
    _KINDS = {
        "information": ("check", styles.SUCCESS, styles.SUCCESS_BG),
        "question": ("alert", styles.PRIMARY_PRESSED, styles.PRIMARY_100),
        "warning": ("alert", styles.WARNING, styles.WARNING_BG),
        "critical": ("close", styles.DANGER, styles.DANGER_BG),
    }

    def __init__(self, parent, kind, title, text, buttons, default):
        super().__init__(parent)
        self.setObjectName("MessageBox")
        self.setWindowTitle(str(title))
        self.setModal(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QDialog#MessageBox {{ background-color: {styles.SURFACE}; }}")
        self.setMinimumWidth(400)
        self.setMaximumWidth(620)
        self.result_button = default

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(20)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._icon_badge(kind), 0, Qt.AlignTop)

        text = str(text)
        if len(text) > LONG_TEXT_CHARS:
            view = QPlainTextEdit(text)
            view.setReadOnly(True)
            view.setMinimumSize(360, 160)
            view.setMaximumHeight(260)
            body.addWidget(view, 1)
        else:
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setMinimumWidth(300)
            label.setStyleSheet(
                f"font-size: 14px; color: {styles.TEXT}; background: transparent; border: none;"
            )
            body.addWidget(label, 1)
        root.addLayout(body)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self._buttons = {}
        for flag, caption, primary in (
            (self.No, t("common.no"), False),
            (self.Yes, t("common.yes"), True),
            (self.Ok, t("common.ok"), True),
        ):
            if not buttons & flag:
                continue
            button = QPushButton(caption)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(96)
            button.setStyleSheet(styles.BLUE_BUTTON_STYLE if primary else styles.GRAY_BUTTON_STYLE)
            button.clicked.connect(lambda _checked=False, f=flag: self._finish(f))
            row.addWidget(button)
            self._buttons[flag] = button
        root.addLayout(row)

        chosen = self._buttons.get(default) or next(iter(self._buttons.values()))
        chosen.setDefault(True)
        chosen.setFocus()
        self._escape = self.No if self.No in self._buttons else default
        self.setSizeGripEnabled(False)
        fit_minimum_height(self)

    @staticmethod
    def _icon_badge(kind):
        name, color, background = MessageBox._KINDS[kind]
        badge = QLabel()
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"background-color: {background}; border-radius: 22px; border: none;")
        badge.setPixmap(icons.pixmap(name, color, 22, 2.4))
        return badge

    def _finish(self, flag):
        self.result_button = flag
        self.accept()

    def reject(self):
        """Esc or the window's close button: counts as "No" for questions, otherwise as the only button."""
        self.result_button = self._escape
        super().reject()

    # ------------------------------------------------------------- static API
    @classmethod
    def _show(cls, kind, parent, title, text, buttons, default):
        box = cls(parent, kind, title, text, buttons, default)
        box.exec()
        return box.result_button

    @classmethod
    def information(cls, parent, title, text, *_):
        return cls._show("information", parent, title, text, cls.Ok, cls.Ok)

    @classmethod
    def warning(cls, parent, title, text, *_):
        return cls._show("warning", parent, title, text, cls.Ok, cls.Ok)

    @classmethod
    def critical(cls, parent, title, text, *_):
        return cls._show("critical", parent, title, text, cls.Ok, cls.Ok)

    @classmethod
    def question(cls, parent, title, text, buttons=None, defaultButton=None):
        buttons = buttons or (cls.Yes | cls.No)
        default = defaultButton or cls.No
        return cls._show("question", parent, title, text, buttons, default)
