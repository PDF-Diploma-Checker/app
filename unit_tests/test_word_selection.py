"""Shift-drag selection: the words whose centre is in the rectangle are selected, and the box is drawn around them."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
PDF = REPO_ROOT / "unit_tests" / "extraction" / "math_accents" / "tp_math_accents_pdflatex.pdf"

from ui.word_selection import select_words  # noqa: E402


def word(x0, y0, x1, y1, text, block=0, line=0, number=0):
    return (x0, y0, x1, y1, text, block, line, number)


class SelectWordsTest(unittest.TestCase):
    WORDS = [word(10, 10, 40, 22, "Ala", 0, 0, 0), word(45, 10, 70, 22, "ma", 0, 0, 1),
             word(10, 30, 50, 42, "kota", 0, 1, 0)]

    def test_a_word_is_selected_when_its_centre_is_inside(self):
        text, bounds = select_words(self.WORDS, (0, 0, 56, 25))      # the edge cuts through "ma", centre 57.5 is out
        self.assertEqual(text, "Ala")
        self.assertEqual(bounds, (10, 10, 40, 22))

    def test_edges_in_the_margin_or_between_words_give_the_same_result(self):
        for rect in ((0, 0, 100, 25), (-50, 5, 80, 28), (9, 9, 71, 23)):
            self.assertEqual(select_words(self.WORDS, rect)[0], "Ala ma")

    def test_reading_order_follows_lines_not_the_order_of_the_list(self):
        words = list(reversed(self.WORDS))
        self.assertEqual(select_words(words, (0, 0, 100, 50))[0], "Ala ma kota")

    def test_nothing_selected_gives_no_bounds(self):
        self.assertEqual(select_words(self.WORDS, (200, 200, 300, 300)), ("", None))

    def test_bounds_hold_exactly_the_selected_words(self):
        _, bounds = select_words(self.WORDS, (0, 0, 100, 50))
        self.assertEqual(bounds, (10, 10, 70, 42))


class ViewSelectionTest(unittest.TestCase):
    def test_the_box_is_snapped_to_the_selected_words(self):
        import time
        from PySide6.QtCore import QRect
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtWidgets import QApplication
        from ui.select_text import SelectablePdfView
        app = QApplication.instance() or QApplication([])
        document = QPdfDocument()
        document.load(str(PDF))
        view = SelectablePdfView()
        view.setDocument(document)
        view.set_source_path(str(PDF))
        view.resize(1000, 800)
        view.show()
        end = time.time() + 0.4
        while time.time() < end:
            app.processEvents()
        size = document.pagePointSize(0)
        k = view.zoomFactor() * view.logicalDpiX() / 72.0
        x_start = (view.viewport().width() - size.width() * k) / 2
        top = view.documentMargins().top()
        # a loose rectangle around the first line ("Praca dyplomowa", words at x 252-343, y 131-143)
        rect = QRect(int(x_start + 230 * k), int(top + 125 * k), int(130 * k), int(24 * k))
        view.extract_text(rect)
        self.assertEqual(view.selected_text, "Praca dyplomowa")
        box = view.selection_pdf_rect
        self.assertLess(abs(box.left() - 251), 3)           # the box starts at the word, not where the mouse was
        self.assertLess(abs(box.right() - 344), 3)


if __name__ == "__main__":
    unittest.main()
