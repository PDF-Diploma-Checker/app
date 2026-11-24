"""Text selection in the reader (like in a PDF reader: from word to word in reading order) and the plagiarism search."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
PDF = REPO_ROOT / "unit_tests" / "extraction" / "math_accents" / "tp_math_accents_pdflatex.pdf"

from ui.word_selection import (  # noqa: E402
    clean_for_search, hit_index, line_rects, ordered_words, search_phrases, select_words, selection_between,
    selection_text,
)


def word(x0, y0, x1, y1, text, block=0, line=0, number=0):
    return (x0, y0, x1, y1, text, block, line, number)


# two lines:  "Ala ma"  /  "kota i psa"
WORDS = [word(10, 10, 40, 22, "Ala", 0, 0, 0), word(45, 10, 70, 22, "ma", 0, 0, 1),
         word(10, 30, 50, 42, "kota", 0, 1, 0), word(55, 30, 60, 42, "i", 0, 1, 1), word(65, 30, 90, 42, "psa", 0, 1, 2)]


class RectangleSelectionTest(unittest.TestCase):
    def test_a_word_is_selected_when_its_centre_is_inside(self):
        text, bounds = select_words(WORDS, (0, 0, 56, 25))
        self.assertEqual(text, "Ala")
        self.assertEqual(bounds, (10, 10, 40, 22))

    def test_nothing_selected_gives_no_bounds(self):
        self.assertEqual(select_words(WORDS, (200, 200, 300, 300)), ("", None))


class FlowSelectionTest(unittest.TestCase):
    def setUp(self):
        self.ordered = ordered_words(list(reversed(WORDS)))

    def test_words_are_in_reading_order(self):
        self.assertEqual([w[4] for w in self.ordered], ["Ala", "ma", "kota", "i", "psa"])

    def test_from_a_word_to_a_word_on_the_next_line(self):
        anchor = hit_index(self.ordered, 50, 15)         # on "ma"
        focus = hit_index(self.ordered, 57, 35)          # on "i"
        chosen = selection_between(self.ordered, anchor, focus)
        self.assertEqual(selection_text(chosen), "ma kota i")

    def test_dragging_backwards_gives_the_same_text(self):
        forward = selection_between(self.ordered, hit_index(self.ordered, 50, 15), hit_index(self.ordered, 57, 35))
        backward = selection_between(self.ordered, hit_index(self.ordered, 57, 35), hit_index(self.ordered, 50, 15))
        self.assertEqual(forward, backward)

    def test_margins_snap_to_the_line_start_and_end(self):
        self.assertEqual(self.ordered[hit_index(self.ordered, -40, 16)][4], "Ala")      # left margin of line 1
        self.assertEqual(self.ordered[hit_index(self.ordered, 400, 16)][4], "ma")       # right margin of line 1
        self.assertEqual(self.ordered[hit_index(self.ordered, 30, 26)][4], "Ala")       # between lines: nearest line

    def test_highlight_is_one_rectangle_per_line(self):
        chosen = selection_between(self.ordered, 1, 3)
        rects = line_rects(chosen, pad=0)
        self.assertEqual(rects, [(45, 10, 70, 22), (10, 30, 60, 42)])

    def test_a_hyphenated_word_at_a_line_end_is_joined(self):
        words = [word(0, 0, 40, 10, "przy-", 0, 0, 0), word(0, 20, 30, 30, "kład", 0, 1, 0),
                 word(35, 20, 60, 30, "PL-", 0, 1, 1), word(0, 40, 30, 50, "Ukraina", 0, 2, 0)]
        self.assertEqual(selection_text(words), "przykład PL- Ukraina")

    def test_pieces_of_a_justified_line_are_one_highlight(self):
        words = [word(10, 10, 30, 22, "aby", 2, 17, 0), word(60, 10, 80, 22, "nie", 2, 18, 0),
                 word(10, 30, 40, 42, "na", 2, 20, 0)]
        self.assertEqual(line_rects(words, pad=0), [(10, 10, 80, 22), (10, 30, 40, 42)])

    def test_paragraphs_are_separated_by_a_line_break(self):
        words = [word(0, 0, 40, 10, "koniec.", 2, 0, 0), word(0, 20, 30, 30, "Nagłówek", 3, 0, 0)]
        self.assertEqual(selection_text(words), "koniec.\nNagłówek")


class SearchPhrasesTest(unittest.TestCase):
    def test_citations_and_quotes_are_removed(self):
        self.assertEqual(clean_for_search('Jak podaje „autor” [12] oraz [3, 4] i [5-7] tak'), "Jak podaje autor oraz i tak")

    def test_short_text_is_one_phrase(self):
        self.assertEqual(search_phrases("Ala ma kota."), ["Ala ma kota."])

    def test_long_text_is_split_into_whole_sentences_of_at_most_32_words(self):
        sentence = " ".join(f"s{i}" for i in range(20)) + "."
        phrases = search_phrases(" ".join([sentence] * 4))
        self.assertEqual(len(phrases), 3)                      # at most three searches
        for phrase in phrases:
            self.assertLessEqual(len(phrase.split()), 32)
            self.assertTrue(phrase.endswith("."))               # no sentence is cut in the middle

    def test_a_heading_is_not_glued_to_the_next_sentence(self):
        text = "3.2 Stanowisko badawcze\nWszystkie pomiary wykonano na tym samym komputerze."
        self.assertEqual(search_phrases(text), ["Wszystkie pomiary wykonano na tym samym komputerze."])

    def test_a_sentence_longer_than_32_words_is_cut(self):
        phrases = search_phrases(" ".join(f"w{i}" for i in range(40)))
        self.assertEqual(len(phrases[0].split()), 32)


class ViewSelectionTest(unittest.TestCase):
    def test_dragging_selects_the_text_between_the_words(self):
        import time
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtTest import QTest
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
        # page 3: "Przez ˆxk|j oznaczono oszacowanie stanu w chwili k uzyskane na podstawie" / "notowań."
        page = 2
        tops, _ = view._page_layout()
        view.verticalScrollBar().setValue(tops[page])
        app.processEvents()

        def at(x, y):
            x0, y0, kx, ky = view._page_origin(page)
            return QPoint(int(x0 + x * kx), int(y0 + y * ky))

        viewport = view.viewport()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, at(250, 137))          # in "oszacowanie"
        QTest.mouseMove(viewport, at(200, 140))
        QTest.mouseMove(viewport, at(130, 151))                                          # in "notowań."
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, at(130, 151))
        self.assertEqual(view.selected_text, "oszacowanie stanu w chwili k uzyskane na podstawie notowań.")
        self.assertEqual(view.selection_page_idx, page)
        self.assertEqual(len(view.selection_box.rects), 2)                                # highlighted line by line
        self.assertTrue(view.has_selection_at(at(300, 137)))
        self.assertFalse(view.has_selection_at(at(150, 137)))                             # "Przez" is not selected

        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, at(300, 400))            # a click clears it
        self.assertEqual(view.selected_text, "")
        self.assertFalse(view.selection_box.isVisible())

        QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, at(300, 137))           # a double click: one word
        self.assertEqual(view.selected_text, "stanu")


class PlagiarismDialogTest(unittest.TestCase):
    def test_urls_search_exact_phrases(self):
        from ui.plagiarism_dialog import search_urls
        self.assertEqual(search_urls(["Ala ma kota"]), ["https://www.google.com/search?q=%22Ala+ma+kota%22"])


if __name__ == "__main__":
    unittest.main()
