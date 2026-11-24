"""Before the selected text is searched on the internet: what will happen, what the result means, and the phrases
that will be searched for (see word_selection.search_phrases)."""

import webbrowser
from urllib.parse import quote_plus

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import styles
from .i18n import t
from .message_box import fit_minimum_height
from .word_selection import GOOGLE_MAX_WORDS, MIN_WORDS, search_phrases

_SKIP_KEY = "plagiarism/skip_info"
SEARCH_URL = "https://www.google.com/search?q={}"


def _settings():
    return QSettings("DiplomaChecker", "DiplomaChecker")


def search_urls(phrases):
    """One Google search for every phrase, as an exact phrase (in quotation marks)."""
    return [SEARCH_URL.format(quote_plus(f'"{phrase}"')) for phrase in phrases]


class PlagiarismDialog(QDialog):
    def __init__(self, phrases, too_short, parent=None):
        super().__init__(parent)
        self.setObjectName("PlagiarismDialog")
        self.setWindowTitle(t("plagiarism.title"))
        self.setStyleSheet(f"QDialog#PlagiarismDialog {{ background-color: {styles.SURFACE}; }}")
        self.setMinimumWidth(520)
        self.setMaximumWidth(640)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)

        title = QLabel(t("plagiarism.title"))
        title.setStyleSheet(f"font-size: 20px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;")
        root.addWidget(title)

        for key in ("plagiarism.how", "plagiarism.meaning", "plagiarism.privacy"):
            label = QLabel(t(key, words=GOOGLE_MAX_WORDS))
            label.setWordWrap(True)
            label.setStyleSheet(f"font-size: 14px; color: {styles.TEXT_2}; background: transparent; border: none;")
            root.addWidget(label)

        if too_short:
            warn = QLabel(t("plagiarism.too_short", words=MIN_WORDS))
            warn.setWordWrap(True)
            warn.setStyleSheet(f"font-size: 13px; color: {styles.WARNING}; background: transparent; border: none;")
            root.addWidget(warn)

        heading = QLabel(t("plagiarism.phrases", count=len(phrases)))
        heading.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;")
        root.addWidget(heading)
        for phrase in phrases:
            quote = QLabel(f"„{phrase}”")
            quote.setWordWrap(True)
            quote.setTextInteractionFlags(Qt.TextSelectableByMouse)
            quote.setStyleSheet(f"font-size: 13px; color: {styles.TEXT}; background-color: {styles.PRIMARY_50}; "
                                f"border: none; border-radius: 6px; padding: 8px 10px;")
            root.addWidget(quote)

        self.dont_show = QCheckBox(t("plagiarism.dont_show"))
        self.dont_show.setStyleSheet(styles.checkbox_style())
        root.addWidget(self.dont_show)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        cancel = QPushButton(t("plagiarism.cancel"))
        cancel.setFixedHeight(42)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(styles.GRAY_BUTTON_STYLE)
        cancel.clicked.connect(self.reject)
        search = QPushButton(t("plagiarism.search"))
        search.setFixedHeight(42)
        search.setCursor(Qt.PointingHandCursor)
        search.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        search.setDefault(True)
        search.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(search)
        root.addLayout(buttons)
        fit_minimum_height(self)

    def accept(self):
        if self.dont_show.isChecked():
            _settings().setValue(_SKIP_KEY, True)
        super().accept()


def check_plagiarism(text, parent=None, open_url=webbrowser.open):
    """Search the selected `text` on Google as exact phrases. Explains it first, unless the user asked not to.
    Returns the URLs that were opened."""
    phrases = search_phrases(text)
    if not phrases:
        return []
    too_short = len(phrases[0].split()) < MIN_WORDS
    if too_short or not _settings().value(_SKIP_KEY, False, type=bool):
        if PlagiarismDialog(phrases, too_short, parent).exec() != QDialog.Accepted:
            return []
    urls = search_urls(phrases)
    for url in urls:
        open_url(url)
    return urls
