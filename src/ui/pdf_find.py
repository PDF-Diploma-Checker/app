"""In-document text search (Ctrl+F) for the PDF reader.

search_pdf_matches   finds every occurrence of a query across the pages of a PDF (case-insensitive, dehyphenated)
PdfFindBar           compact floating search bar placed in the top-right corner of the PDF view
"""

import fitz
from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from . import icons, motion, styles
from .i18n import t

MARGIN = 16
BAR_WIDTH = 368
BAR_HEIGHT = 48


def search_pdf_matches(path, query):
    """Return [(page_index, (x0, y0, x1, y1)), ...] for every match of `query` in the PDF at `path`."""
    needle = (query or "").strip()
    if not path or not needle:
        return []
    flags = getattr(fitz, "TEXT_DEHYPHENATE", 0)
    matches = []
    try:
        with fitz.open(path) as pdf:
            for page_idx, page in enumerate(pdf):
                rects = page.search_for(needle, flags=flags)
                if not rects:
                    continue
                rects.sort(key=lambda r: (round(r.y0, 1), round(r.x0, 1)))
                for rect in rects:
                    matches.append((page_idx, (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))))
    except (OSError, RuntimeError, ValueError):
        return []
    return matches


class _FindInput(QLineEdit):
    """Search field that routes Enter / Shift+Enter to next / previous match and Esc to closing the bar."""

    nextRequested = Signal()
    prevRequested = Signal()
    closeRequested = Signal()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                self.prevRequested.emit()
            else:
                self.nextRequested.emit()
            event.accept()
            return
        if key == Qt.Key_Escape:
            self.closeRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PdfFindBar(QFrame):
    """Floating Ctrl+F search bar anchored to the top-right corner of the PDF view."""

    matchesChanged = Signal(list, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PdfFindBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#PdfFindBar {{ background-color: {styles.SURFACE};"
            f" border: 1px solid {styles.BORDER}; border-radius: 10px; }}"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(15, 23, 42, 48))
        self.setGraphicsEffect(shadow)

        self._view = None
        self._pdf_path = None
        self._matches = []
        self._current = -1
        self._last_query = None

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 8, 6)
        row.setSpacing(4)

        self.input = _FindInput(self)
        self.input.setClearButtonEnabled(True)
        self.input.addAction(icons.icon("search", "#9CA3AF", 15), QLineEdit.LeadingPosition)
        self.input.setFixedHeight(34)
        self.input.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {styles.BORDER}; border-radius: 7px;"
            f" padding: 4px 8px; font-size: 13px; background: {styles.SURFACE}; color: {styles.TEXT}; }}"
            f"QLineEdit:focus {{ border-color: {styles.PRIMARY}; }}"
        )
        self.input.textChanged.connect(self._queue_search)
        self.input.nextRequested.connect(self.next_match)
        self.input.prevRequested.connect(self.prev_match)
        self.input.closeRequested.connect(self.close_bar)
        row.addWidget(self.input, 1)

        self.count_label = QLabel("")
        self.count_label.setAlignment(Qt.AlignCenter)
        self.count_label.setMinimumWidth(48)
        self.count_label.setStyleSheet(
            f"font-size: 12px; font-weight: 500; color: {styles.TEXT_2}; background: transparent; border: none;"
        )
        motion.tabular(self.count_label)
        row.addWidget(self.count_label)

        self.prev_btn = self._icon_button("chevron-up")
        self.prev_btn.clicked.connect(self.prev_match)
        row.addWidget(self.prev_btn)

        self.next_btn = self._icon_button("chevron-down")
        self.next_btn.clicked.connect(self.next_match)
        row.addWidget(self.next_btn)

        self.close_btn = self._icon_button("close")
        self.close_btn.clicked.connect(self.close_bar)
        row.addWidget(self.close_btn)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._run_search)

        self.setFixedHeight(BAR_HEIGHT)
        self.retranslate_ui()
        self._update_nav_state()
        self.hide()

    @staticmethod
    def _icon_button(icon_name):
        btn = QPushButton()
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setStyleSheet(styles.ICON_BUTTON_STYLE)
        btn.setIcon(icons.icon(icon_name, styles.TEXT_3, 15, 2.0))
        btn.setIconSize(QSize(15, 15))
        return btn

    # ------------------------------------------------------------------ placement
    def follow(self, view):
        """Anchor the bar to the top-right corner of the visible part of `view`."""
        self._view = view
        view.installEventFilter(self)
        self._place()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Show):
            self._place()
        return False

    def _place(self):
        view = self._view
        width = BAR_WIDTH
        if view is not None:
            viewport = view.viewport().geometry()
            width = max(240, min(BAR_WIDTH, viewport.width() - 2 * MARGIN))
            self.resize(width, BAR_HEIGHT)
            self.move(viewport.right() - width - MARGIN + 1, viewport.top() + MARGIN)
        else:
            self.resize(width, BAR_HEIGHT)
        self.raise_()

    # ------------------------------------------------------------------ lifecycle
    def set_document_path(self, path):
        """Reset search state when switching to another PDF document."""
        self._pdf_path = path
        self._search_timer.stop()
        self._matches = []
        self._current = -1
        self._last_query = None
        self._update_nav_state()
        self.matchesChanged.emit([], -1)
        if self.isVisible():
            self.hide()

    def open_bar(self, initial_text=""):
        """Show the bar, focus the input, and optionally pre-fill it with selected text."""
        self._place()
        self.show()
        self.raise_()
        clean = (initial_text or "").strip()
        if clean:
            self.input.blockSignals(True)
            self.input.setText(clean)
            self.input.blockSignals(False)
            self._run_search()
        elif self.input.text().strip():
            self._run_search()
        self.input.setFocus(Qt.ShortcutFocusReason)
        self.input.selectAll()

    def close_bar(self):
        """Hide the bar and remove all search highlights."""
        self._search_timer.stop()
        was_visible = self.isVisible()
        self._matches = []
        self._current = -1
        self._last_query = None
        self._update_nav_state()
        self.matchesChanged.emit([], -1)
        if was_visible:
            self.hide()
            if self._view is not None:
                self._view.setFocus(Qt.OtherFocusReason)

    # ------------------------------------------------------------------ searching
    def _queue_search(self, _text=None):
        self._search_timer.start()

    def _run_search(self):
        self._search_timer.stop()
        query = self.input.text().strip()
        self._last_query = query
        if not query or not self._pdf_path:
            self._matches = []
            self._current = -1
            self._update_nav_state()
            self.matchesChanged.emit([], -1)
            return
        self._matches = search_pdf_matches(self._pdf_path, query)
        self._current = 0 if self._matches else -1
        self._update_nav_state()
        self.matchesChanged.emit(self._matches, self._current)

    def _ensure_up_to_date(self):
        query = self.input.text().strip()
        if self._search_timer.isActive() or query != self._last_query:
            self._run_search()
            return True
        return False

    def next_match(self):
        """Jump to the next occurrence, wrapping around to the first."""
        if self._ensure_up_to_date():
            return
        if not self._matches:
            return
        self._current = (self._current + 1) % len(self._matches)
        self._update_nav_state()
        self.matchesChanged.emit(self._matches, self._current)

    def prev_match(self):
        """Jump to the previous occurrence, wrapping around to the last."""
        if self._ensure_up_to_date():
            return
        if not self._matches:
            return
        self._current = (self._current - 1) % len(self._matches)
        self._update_nav_state()
        self.matchesChanged.emit(self._matches, self._current)

    def _update_nav_state(self):
        total = len(self._matches)
        has_matches = total > 0
        self.prev_btn.setEnabled(has_matches)
        self.next_btn.setEnabled(has_matches)
        query = self.input.text().strip()
        if not query:
            self.count_label.setText("")
            self.count_label.setStyleSheet(
                f"font-size: 12px; font-weight: 500; color: {styles.TEXT_2}; background: transparent; border: none;"
            )
        elif has_matches:
            self.count_label.setText(t("find.counter", current=self._current + 1, total=total))
            self.count_label.setStyleSheet(
                f"font-size: 12px; font-weight: 500; color: {styles.TEXT_2}; background: transparent; border: none;"
            )
        else:
            self.count_label.setText(t("find.no_matches"))
            self.count_label.setStyleSheet(
                f"font-size: 12px; font-weight: 600; color: {styles.DANGER}; background: transparent; border: none;"
            )

    def retranslate_ui(self, *_):
        self.input.setPlaceholderText(t("find.placeholder"))
        self.input.setAccessibleName(t("find.placeholder"))
        self.prev_btn.setToolTip(motion.with_hint(t("find.previous"), "Shift+Enter"))
        self.prev_btn.setAccessibleName(t("find.previous"))
        self.next_btn.setToolTip(motion.with_hint(t("find.next"), "Enter"))
        self.next_btn.setAccessibleName(t("find.next"))
        self.close_btn.setToolTip(motion.with_hint(t("find.close"), "Esc"))
        self.close_btn.setAccessibleName(t("find.close"))
        self._update_nav_state()
