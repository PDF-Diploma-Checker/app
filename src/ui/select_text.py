from PySide6.QtWidgets import QMenu, QApplication, QPushButton, QToolTip, QInputDialog, QFrame, QWidget
from PySide6.QtCore import Qt, QPoint, QRect, QRectF, Signal, QPointF, QSize
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter
from PySide6.QtPdfWidgets import QPdfView
import os
import sys

from common.findings import assign_finding_ids, finding_kind, finding_label

from . import styles
from .i18n import t
from .word_selection import (bounds_of, hit_index, line_rects, ordered_words, search_phrases, selection_between,
                             selection_text)

TOOLTIP_LANG = {
    "pl": {
        "cat": "Kategoria:", "desc": "Opis:", "refers": "Dotyczy tekstu:", 
        "no_text": "[Brak tekstu]", "my_comment": "Twój komentarz:", "fragment": "Fragment:",
        "def_err": "Brak szczegółowego opisu błędu", "def_cat": "Błąd"
    },
    "en": {
        "cat": "Category:", "desc": "Description:", "refers": "Applies to text:", 
        "no_text": "[No text]", "my_comment": "Your comment:", "fragment": "Fragment:",
        "def_err": "No detailed error description", "def_cat": "Error"
    }
}

def page_index(data):
    """Page of a finding or a comment, counted from 0. Findings carry "page" (from 0). Comments carry "strona", the
    page number counted from 1 (newer ones also "page"); it used to be read as an index, so a comment was drawn
    and exported on the page after the one it was made on."""
    if "page" in data:
        return int(data["page"])
    strona = int(data.get("strona", 1))
    return strona - 1 if "tekst_komentarza" in data else strona


_VISIBLE_MARGIN = 200      # pixels around the view where markers are already placed (no pop-in while scrolling)


class ErrorMarker(QPushButton):
    """represents an error marker on PDF"""
    def __init__(self, error_data, parent=None, lang="pl"):
        super().__init__(parent)
        self.data = error_data
        self.lang = lang
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(styles.ERROR_MARKER_STYLE)
        number = error_data.get("finding_id") if isinstance(error_data, dict) else None
        # the number of the finding sits right next to the "!", on the marker that is clicked
        text = f"! {number}" if number else "!"
        self.setText(text)
        self.setFixedSize(max(16, self.fontMetrics().horizontalAdvance(text) + 12), 16)
        label = finding_label(error_data)
        self.setToolTip(f"{label} · {error_data.get('category', '')}".strip(" ·") if label else "")
        if self.data.get("category") == "TYPOS":
            self.setStyleSheet(styles.SPELLING_MARKER_STYLE)
            hint = "Right-click: propose a correct word" if lang == "en" else "Prawy przycisk: zaproponuj poprawne słowo"
            self.setToolTip(f"{label} · {hint}" if label else hint)
        self.clicked.connect(self.show_details)
        if self.data.get("category") == "TYPOS":
            self.setContextMenuPolicy(Qt.CustomContextMenu)
            self.customContextMenuRequested.connect(self.proposal_menu)

    def open_proposal(self):
        from .dictionary_proposal import ProposalDialog
        ProposalDialog(self, self.lang).exec()

    def proposal_menu(self, position):
        if self.data.get("category") != "TYPOS":
            return
        from .dictionary_proposal import TEXT
        menu = QMenu(self)
        action = menu.addAction(TEXT.get(self.lang, TEXT['pl'])[0])
        action.triggered.connect(self.open_proposal)
        menu.exec(self.mapToGlobal(position))

    def show_details(self):
        """Displays a formatted tooltip with details about the error"""
        t = TOOLTIP_LANG.get(self.lang, TOOLTIP_LANG["pl"])
        
        opis = self.data.get('comment', t["def_err"])
        kat = self.data.get('category', t["def_cat"])
        tekst = self.data.get('found_text', '')

        label = finding_label(self.data)
        info = (f"<b>{label}</b><br>" if label else "") + (f"<b>{t['cat']}</b> {kat}<br>"
                                                         f"<b>{t['desc']}</b> {opis}<br>")
        
        if tekst and str(tekst).strip() not in ["[Brak tekstu]", "[No text]", ""]:
            info += f"<b>{t['refers']}</b> <i>{tekst}</i>"

        if self.data.get("category") == "TYPOS":
            info += "<br><b>" + ("Right-click this marker to propose a correct word." if self.lang == "en" else "Kliknij znacznik prawym przyciskiem, aby zaproponować poprawne słowo.") + "</b>"
        QToolTip.showText(self.mapToGlobal(QPoint(20, 0)), info)

class CommentMarker(QPushButton):
    """represents a custom comment marker added by the user; a right click offers to delete it"""
    deleteRequested = Signal(object)

    def __init__(self, comment_data, parent=None, lang="pl"):
        super().__init__(parent)
        self.data = comment_data
        self.lang = lang
        self.setFixedSize(16, 16)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(styles.COMMENT_MARKER_STYLE)
        self.setText("C")
        self.clicked.connect(self.show_details)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def show_details(self):
        """displays the user's comment text"""
        labels = TOOLTIP_LANG.get(self.lang, TOOLTIP_LANG["pl"])
        info = (f"<b>{labels['my_comment']}</b> {self.data.get('tekst_komentarza', '')}<br>"
                f"<b>{labels['fragment']}</b> {self.data.get('znaleziony_tekst', '')}<br>"
                f"<i>{t('pdf_menu.delete_comment_hint')}</i>")
        QToolTip.showText(self.mapToGlobal(QPoint(20, 0)), info)

    def show_menu(self, position):
        menu = QMenu(self)
        delete_action = menu.addAction(t("pdf_menu.delete_comment"))
        delete_action.triggered.connect(lambda: self.deleteRequested.emit(self))
        menu.exec(self.mapToGlobal(position))

class HighlightBox(QFrame):
    """A transparent frame overlay used to visually highlight a specific text on PDF"""
    def __init__(self, rect_data, parent=None):
        super().__init__(parent)
        self.data = rect_data
        self.setStyleSheet(styles.HIGHLIGHT_BOX_DEFAULT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

class SpellingHighlightBox(QPushButton):
    """A word-sized application overlay, never a stored PDF annotation."""
    def __init__(self, rect_data, marker, parent=None):
        super().__init__(parent)
        self.data = rect_data
        self.setObjectName('SpellingHighlight')
        self.setStyleSheet(styles.SPELLING_HIGHLIGHT_STYLE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoDefault(False)
        label = finding_label(getattr(marker, 'data', None))
        self.setToolTip(f"{label} · {t('main.spelling_click_hint')}" if label else t('main.spelling_click_hint'))
        self.setAccessibleName(t('main.spelling_proposal_action'))
        self.setAccessibleDescription(t('main.spelling_click_hint'))
        self.clicked.connect(marker.open_proposal)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda position: marker.proposal_menu(marker.mapFromGlobal(self.mapToGlobal(position))))

    def mousePressEvent(self, event):
        if event.modifiers() & Qt.ShiftModifier:
            event.ignore()  # Preserve Shift-drag text selection in the PDF view.
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.modifiers() & Qt.ShiftModifier:
            event.ignore()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.modifiers() & Qt.ShiftModifier:
            event.ignore()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class SelectionHighlight(QWidget):
    """The selected text, highlighted line by line over the page; it lets the mouse through to the view."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.rects = []
        self.hide()

    def set_rects(self, rects):
        self.rects = list(rects)
        if not self.rects:
            self.hide()
            return
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.update()

    COLOR = (37, 99, 235, 70)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*self.COLOR))
        for rect in self.rects:
            p.drawRect(rect)


class SourceHighlight(SelectionHighlight):
    """The fragment of the thesis an answer of the assistant comes from (amber, so it is not taken for a selection)."""
    COLOR = (245, 158, 11, 75)


class SelectablePdfView(QPdfView):
    """An extended PDF view that enables area-based text selection, adding custom user comments, and overlaying error markers."""
    textCopied = Signal(str)
    commentAdded = Signal(dict)
    commentDeleted = Signal(dict)
    backRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.markers = []
        self.comment_markers = []
        self.highlight_boxes = []
        self.selection_box = SelectionHighlight(self.viewport())
        self.source_box = SourceHighlight(self.viewport())
        self._source_rects = []         # [[page, x0, y0, x1, y1]] of the fragment shown by the assistant
        self.selection_pdf_rect = None
        self.selection_page_idx = -1
        self.selected_text = ""
        self._sel_words, self._sel_anchor, self._sel_focus, self._sel_rects = [], None, None, []
        self._press_pos = None
        self._press_page, self._press_pdf, self._press_anchor, self._dragging = -1, (0.0, 0.0), None, False
        self._source_path = None
        self._words_cache = {}
        self._ordered_cache = {}
        self.viewport().setCursor(Qt.IBeamCursor)

        self.verticalScrollBar().valueChanged.connect(self.update_selection_box_pos)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self.update_source_box_pos())
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.update_source_box_pos())
        self.horizontalScrollBar().valueChanged.connect(self.update_selection_box_pos)
        self.verticalScrollBar().valueChanged.connect(self.update_markers_pos)
        self.horizontalScrollBar().valueChanged.connect(self.update_markers_pos)

    def set_source_path(self, path):
        """The PDF file shown: its words (with their exact positions) are read from it for the selection."""
        self._source_path = path
        self._words_cache = {}
        self._ordered_cache = {}
        self.clear_selection()

    def _page_words(self, index):
        """Words of a page as PyMuPDF tuples (x0, y0, x1, y1, text, block, line, word); None when unreadable."""
        if index not in self._words_cache:
            words = None
            if self._source_path:
                try:
                    import fitz
                    with fitz.open(self._source_path) as pdf:
                        words = pdf[index].get_text("words")
                except Exception:
                    words = None
            self._words_cache[index] = words
        return self._words_cache[index]

    def clear_markers(self):
        """Removes all error marker"""
        for m in self.markers:
            m.deleteLater()
        self.markers = []

    def add_errors(self, errors_list, lang="pl"):
        """Clears existing errors and overlays a new list of error markers and highlight boxes"""
        self.clear_markers()
        errors_list = assign_finding_ids(errors_list)

        new_boxes = []
        for box in self.highlight_boxes:
            if getattr(box, 'is_error', False):
                box.deleteLater()
            else:
                new_boxes.append(box)
        self.highlight_boxes = new_boxes

        for err in errors_list:
            if finding_kind(err) != "page":
                continue
            marker = ErrorMarker(err, self.viewport(), lang=lang)
            self.markers.append(marker)
            coords = err.get("coords", err.get("wspolrzedne", {}))
            w = coords.get("w", 0)
            
            if w > 0:
                box = self._error_box(err, marker, err)
                box.is_error = True
                self.highlight_boxes.append(box)

            for extra in err.get("extra_rects", []):
                ebox = self._error_box(extra, marker, err)
                ebox.is_error = True
                self.highlight_boxes.append(ebox)

        self.update_markers_pos()

    def _error_box(self, rect_data, marker, error):
        if error.get('category') == 'TYPOS':
            return SpellingHighlightBox(rect_data, marker, self.viewport())
        box = HighlightBox(rect_data, self.viewport())
        box.setStyleSheet(styles.HIGHLIGHT_BOX_ERROR)
        return box

    def _page_layout(self):
        """(top, width) in pixels of every page for the current zoom; cached, because it only changes with the zoom,
        the window size or the document, not while scrolling."""
        doc = self.document()
        dpi_x, dpi_y = self.logicalDpiX(), self.logicalDpiY()
        zoom = self.zoomFactor()
        key = (id(doc), doc.pageCount(), zoom, dpi_x, dpi_y, self.pageSpacing(), self.documentMargins().top())
        if getattr(self, "_layout_key", None) != key:
            tops, widths = [], []
            y = self.documentMargins().top()
            for i in range(doc.pageCount()):
                size_pt = doc.pagePointSize(i)
                tops.append(y)
                widths.append(int((size_pt.width() * zoom * (dpi_x / 72.0)) + 0.5))
                y += int((size_pt.height() * zoom * (dpi_y / 72.0)) + 0.5) + self.pageSpacing()
            self._layout_key, self._layout = key, (tops, widths)
        return self._layout

    def update_markers_pos(self):
        """Recalculates the pixel positions of the markers and highlight boxes.

        Runs on every scroll step, so it stays cheap: page offsets come from a cache and only the widgets that are
        (nearly) in view are moved; the hundreds of the others stay hidden until they scroll in."""
        doc = self.document()
        if not doc or doc.pageCount() == 0 or self.viewport().width() < 50:
            return          # not laid out yet: the markers would land at the edge of the view

        dpi_x, dpi_y = self.logicalDpiX(), self.logicalDpiY()
        zoom = self.zoomFactor()
        kx, ky = zoom * (dpi_x / 72.0), zoom * (dpi_y / 72.0)

        scroll_x = self.horizontalScrollBar().value()
        scroll_y = self.verticalScrollBar().value()
        viewport = self.viewport()
        viewport_w = viewport.width()
        has_hscroll = self.horizontalScrollBar().maximum() > 0
        tops, widths = self._page_layout()
        view = QRect(0, 0, viewport_w, viewport.height()).adjusted(-_VISIBLE_MARGIN, -_VISIBLE_MARGIN,
                                                                   _VISIBLE_MARGIN, _VISIBLE_MARGIN)

        def origin(data):
            """Pixel position of the page's coordinate (0, 0) in the viewport, or None for a missing page."""
            page_idx = page_index(data)
            if page_idx < 0 or page_idx >= len(tops):
                return None
            x_start = self.documentMargins().left() if has_hscroll else (viewport_w - widths[page_idx]) // 2
            return x_start - scroll_x, tops[page_idx] - scroll_y

        viewport.setUpdatesEnabled(False)
        try:
            all_markers = self.markers + self.comment_markers
            for marker in all_markers:
                data = marker.data
                base = origin(data)
                if base is None:
                    continue
                coords = data.get("coords", data.get("wspolrzedne", {"x": 0, "y": 0, "w": 0, "h": 0}))
                px_x = base[0] + int((coords.get("x", 0) * kx) + 0.5)
                px_y = base[1] + int((coords.get("y", 0) * ky) + 0.5)
                px_w = int((coords.get("w", 0) * kx) + 0.5)
                half = marker.width() // 2
                marker_x = px_x + (px_w // 2) - half if px_w > 0 else px_x - half
                marker_y = px_y - 12
                if view.intersects(QRect(int(marker_x), int(marker_y), marker.width(), 16)):
                    marker.move(int(marker_x), int(marker_y))
                    marker.show()
                elif marker.isVisible():
                    marker.hide()

            for box in self.highlight_boxes:
                data = box.data
                base = origin(data)
                if base is None:
                    continue
                coords = data.get("coords", data.get("wspolrzedne", {"x": 0, "y": 0, "w": 0, "h": 0}))
                px_w, px_h = coords.get("w", 0) * kx, coords.get("h", 0) * ky
                if not (px_w > 0 and px_h > 0):
                    continue
                rect = QRect(int(base[0] + coords.get("x", 0) * kx), int(base[1] + coords.get("y", 0) * ky),
                             int(px_w), int(px_h))
                if view.intersects(rect):
                    if box.geometry() != rect:
                        box.setGeometry(rect)
                    box.show()
                elif box.isVisible():
                    box.hide()

            for marker in all_markers:
                if marker.isVisible():
                    marker.raise_()
        finally:
            viewport.setUpdatesEnabled(True)
            viewport.update()
        self.update_source_box_pos()        # the zoom moves it too

    def clear_comments(self):
        """Removes all comments"""
        for m in self.comment_markers:
            m.deleteLater()
        self.comment_markers = []

        new_boxes = []
        for b in self.highlight_boxes:
            if not getattr(b, 'is_error', False):
                b.deleteLater()
            else:
                new_boxes.append(b)
        self.highlight_boxes = new_boxes

    def resizeEvent(self, event):
        """Handles the widget resize event by triggering a recalculation"""
        super().resizeEvent(event)
        self.update_selection_box_pos()
        self.update_markers_pos()
        self.update_source_box_pos()

    # ------------------------------------------------------------------ text selection
    # Like in a PDF reader: press on the text and drag; the words from the one under the press to the one under the
    # mouse are selected in reading order, across lines, and highlighted line by line. Shift+click extends the
    # selection, a double click selects a word, Ctrl+C copies. The selection stays on the page where it started.

    def _page_origin(self, index):
        """Top-left corner of page `index` in viewport pixels, and the pixels per PDF point (x, y)."""
        tops, widths = self._page_layout()
        zoom = self.zoomFactor()
        kx, ky = zoom * self.logicalDpiX() / 72.0, zoom * self.logicalDpiY() / 72.0
        if self.horizontalScrollBar().maximum() > 0:
            x = self.documentMargins().left()
        else:
            x = (self.viewport().width() - widths[index]) / 2
        return x - self.horizontalScrollBar().value(), tops[index] - self.verticalScrollBar().value(), kx, ky

    def _page_at(self, pos):
        """Index of the page under (or nearest to) the viewport point `pos`, or -1 without a document."""
        doc = self.document()
        if not doc or doc.pageCount() == 0:
            return -1
        tops, _ = self._page_layout()
        y = pos.y() + self.verticalScrollBar().value()
        index = 0
        for i, top in enumerate(tops):
            if top <= y:
                index = i
        return index

    def _to_pdf(self, index, pos):
        x0, y0, kx, ky = self._page_origin(index)
        return (pos.x() - x0) / kx, (pos.y() - y0) / ky

    def _to_view(self, index, rect):
        x0, y0, kx, ky = self._page_origin(index)
        return QRectF(x0 + rect[0] * kx, y0 + rect[1] * ky, (rect[2] - rect[0]) * kx, (rect[3] - rect[1]) * ky)

    def show_source(self, page, rects):
        """Scrolls to a fragment of the thesis (page counted from 0) and highlights its lines."""
        doc = self.document()
        if not doc or not (0 <= page < doc.pageCount()):
            return
        self._source_rects = [list(r) for r in rects if len(r) >= 5 and 0 <= int(r[0]) < doc.pageCount()]
        tops, _ = self._page_layout()
        ky = self.zoomFactor() * self.logicalDpiY() / 72.0
        first_y = min((r[2] for r in self._source_rects if int(r[0]) == page), default=0)
        self.verticalScrollBar().setValue(int(tops[page] + first_y * ky - 80))
        self.update_source_box_pos()

    def clear_source(self):
        self._source_rects = []
        self.source_box.set_rects([])

    def update_source_box_pos(self):
        if not self._source_rects:
            return
        self.source_box.set_rects([self._to_view(int(r[0]), r[1:5]) for r in self._source_rects])

    def clear_selection(self):
        self.selected_text = ""
        self.selection_pdf_rect = None
        self.selection_page_idx = -1
        self._sel_words, self._sel_anchor, self._sel_focus, self._sel_rects = [], None, None, []
        self.selection_box.set_rects([])

    def _select(self, index, anchor, focus):
        """Select the words `anchor`..`focus` (indexes into the ordered words of page `index`)."""
        ordered = self._ordered_words(index)
        chosen = selection_between(ordered, anchor, focus)
        self.selection_page_idx = index
        self._sel_words, self._sel_anchor, self._sel_focus = ordered, anchor, focus
        self.selected_text = selection_text(chosen)
        bounds = bounds_of(chosen)
        pad = 1.0
        self.selection_pdf_rect = (QRectF(bounds[0] - pad, bounds[1] - pad, bounds[2] - bounds[0] + 2 * pad,
                                          bounds[3] - bounds[1] + 2 * pad) if bounds else None)
        self._sel_rects = line_rects(chosen)
        self.update_selection_box_pos()

    def _ordered_words(self, index):
        if index not in self._ordered_cache:
            self._ordered_cache[index] = ordered_words(self._page_words(index))
        return self._ordered_cache[index]

    def _select_with_qt(self, index, start, end):
        """When the words cannot be read from the file: Qt's own selection between the two points."""
        selection = self.document().getSelection(index, QPointF(*start), QPointF(*end))
        text = selection.text().strip() if selection else ""
        self.selection_page_idx = index
        self.selected_text = " ".join(text.split())
        box = selection.boundingRectangle() if text else QRectF()
        self.selection_pdf_rect = box if text else None
        self._sel_rects = [(box.left(), box.top(), box.right(), box.bottom())] if text else []
        self.update_selection_box_pos()

    def _drag_to(self, pos):
        index = self._press_page
        x, y = self._to_pdf(index, pos)
        ordered = self._ordered_words(index)
        if not ordered:
            if self._page_words(index) is None:            # file not readable: fall back to Qt
                self._select_with_qt(index, self._press_pdf, (x, y))
            return
        focus = hit_index(ordered, x, y)
        anchor = self._press_anchor if self._press_anchor is not None else hit_index(ordered, *self._press_pdf)
        self._select(index, anchor, focus)

    def has_selection_at(self, pos, margin=4):
        """True when the viewport point `pos` is on the highlighted text."""
        return any(r.adjusted(-margin, -margin, margin, margin).contains(QPointF(pos)) for r in self.selection_box.rects)

    def update_selection_box_pos(self):
        """Places the highlight of the selection for the current zoom and scroll."""
        if self.selection_page_idx == -1 or not self._sel_rects:
            self.selection_box.set_rects([])
            return
        doc = self.document()
        if not doc or doc.pageCount() <= self.selection_page_idx:
            return
        self.selection_box.set_rects([self._to_view(self.selection_page_idx, r) for r in self._sel_rects])

    def mousePressEvent(self, event):
        """Handles mouse press events."""
        if event.button() == Qt.LeftButton:
            self.clear_source()
        if event.button() == Qt.BackButton:
            self.backRequested.emit()
            return
        pos = event.position()
        if event.button() == Qt.RightButton:
            if self.selected_text and self.has_selection_at(pos):
                self.show_context_menu(event.globalPosition().toPoint())
            return
        if event.button() == Qt.LeftButton:
            index = self._page_at(pos)
            if index < 0:
                return
            extend = bool(event.modifiers() & Qt.ShiftModifier) and index == self.selection_page_idx \
                and self._sel_anchor is not None
            self._press_pos, self._press_page, self._dragging = pos, index, extend
            self._press_pdf = self._to_pdf(index, pos)
            if extend:                                      # Shift+click: move the end of the current selection
                self._press_anchor = self._sel_anchor
                self._drag_to(pos)
            else:
                self._press_anchor = None
                self.clear_selection()
            self.setFocus(Qt.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handles mouse move events"""
        if self._press_pos is not None and event.buttons() & Qt.LeftButton:
            pos = event.position()
            if not self._dragging and (pos - self._press_pos).manhattanLength() < 4:
                return                                      # a click, not a drag (yet)
            self._dragging = True
            self._autoscroll(pos)
            self._drag_to(pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _autoscroll(self, pos):
        """Dragging near the top or bottom edge scrolls the page, so a selection can be longer than the view."""
        edge, height = 24, self.viewport().height()
        bar = self.verticalScrollBar()
        if pos.y() < edge:
            bar.setValue(bar.value() - int((edge - pos.y()) * 0.8) - 2)
        elif pos.y() > height - edge:
            bar.setValue(bar.value() + int((pos.y() - height + edge) * 0.8) + 2)

    def mouseReleaseEvent(self, event):
        """Handles mouse release events."""
        if self._press_pos is not None and event.button() == Qt.LeftButton:
            self._press_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """A double click selects the word under the mouse."""
        if event.button() != Qt.LeftButton:
            return super().mouseDoubleClickEvent(event)
        pos = event.position()
        index = self._page_at(pos)
        ordered = self._ordered_words(index) if index >= 0 else []
        if ordered:
            x, y = self._to_pdf(index, pos)
            hit = hit_index(ordered, x, y)
            w = ordered[hit]
            if w[0] - 3 <= x <= w[2] + 3 and w[1] - 3 <= y <= w[3] + 3:
                self._select(index, hit, hit)
        self._press_pos = None
        event.accept()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy) and self.selected_text:
            self.copy_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def show_context_menu(self, global_pos):
        """Displays a pop-up context menu."""
        menu = QMenu(self)
        copy_action = QAction(t("pdf_menu.copy_text"), self)
        copy_action.triggered.connect(self.copy_to_clipboard)
        
        plagiat_action = QAction(t("pdf_menu.check_plagiarism"), self)
        plagiat_action.triggered.connect(self.check_plagiarism) 
        
        comment_action = QAction(t("pdf_menu.add_comment"), self)
        comment_action.triggered.connect(self.add_custom_comment)
        comment_action.setEnabled(bool(self.selected_text)) 

        menu.addAction(copy_action)
        menu.addAction(plagiat_action)
        menu.addAction(comment_action)
        menu.exec(global_pos)

    def add_custom_comment(self):
        """Opens an input dialog prompting the user for comment text."""
        if not self.selection_pdf_rect or self.selection_page_idx == -1:
            return
            
        text, ok = QInputDialog.getText(self, t("pdf_menu.add_comment"), t("pdf_menu.comment_prompt"))
        if ok and text:
            comment_data = {
                "page": self.selection_page_idx,
                "strona": self.selection_page_idx + 1,
                "wspolrzedne": {
                    "x": self.selection_pdf_rect.x(), 
                    "y": self.selection_pdf_rect.y(),
                    "w": self.selection_pdf_rect.width(),
                    "h": self.selection_pdf_rect.height() 
                },
                "tekst_komentarza": text,
                "znaleziony_tekst": self.selected_text
            }
            
            self.add_comment_marker(comment_data, styles.HIGHLIGHT_BOX_COMMENT)
            self.update_markers_pos()
            self.selection_box.hide()
            self.commentAdded.emit(comment_data)

    def add_comment_marker(self, comment_data, box_style=None):
        """Shows a comment: its marker and, for a comment on selected text, the box around that text."""
        coords = comment_data.get("wspolrzedne", {})
        if box_style and coords.get("w", 0) > 0:
            box = HighlightBox(comment_data, self.viewport())
            box.is_error = False
            box.setStyleSheet(box_style)
            self.highlight_boxes.append(box)
        marker = CommentMarker(comment_data, self.viewport())
        marker.deleteRequested.connect(self.delete_comment)
        self.comment_markers.append(marker)
        return marker

    def delete_comment(self, marker, confirm=True):
        """Removes a comment the user added (after asking), with its box, and tells the window to forget it."""
        if marker not in self.comment_markers:
            return False
        if confirm:
            from .message_box import MessageBox
            reply = MessageBox.question(self, t("pdf_menu.delete_comment"), t("pdf_menu.delete_comment_confirm"))
            if reply != MessageBox.Yes:
                return False
        data = marker.data
        self.comment_markers.remove(marker)
        marker.deleteLater()
        kept = []
        for box in self.highlight_boxes:
            if not getattr(box, "is_error", False) and getattr(box, "data", None) is data:
                box.deleteLater()
            else:
                kept.append(box)
        self.highlight_boxes = kept
        self.commentDeleted.emit(data)
        return True

    def copy_to_clipboard(self):
        """Copies the currently selected text fragment to the system clipboard."""
        QApplication.clipboard().setText(self.selected_text)

    def check_plagiarism(self):
        """Searches the selected text on Google as exact phrases, after explaining what that does and means."""
        if not self.selected_text:
            return
        from .plagiarism_dialog import check_plagiarism
        check_plagiarism(self.selected_text, self)
