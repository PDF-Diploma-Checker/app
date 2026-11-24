"""Ctrl+F focuses the document history search on the start page and opens the in-document find bar in the PDF reader."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

_HOME = tempfile.mkdtemp(prefix="dc_test_ctrl_f_")
os.environ["DIPLOMACHECKER_HOME"] = _HOME

import fitz
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.pdf_find import search_pdf_matches


def _wait(app, ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _make_two_page_pdf(path):
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 100), "Diploma thesis introduction about neural networks.")
    page1.insert_text((72, 160), "Neural architecture and evaluation results.")
    page2 = doc.new_page()
    page2.insert_text((72, 100), "Chapter two repeats neural evaluation metrics.")
    doc.save(str(path))
    doc.close()


class SearchMatchesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pdf_path = Path(cls.tmp.name) / "sample.pdf"
        _make_two_page_pdf(cls.pdf_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_finds_case_insensitive_matches_across_pages(self):
        matches = search_pdf_matches(str(self.pdf_path), "neural")
        self.assertEqual(len(matches), 3)
        self.assertEqual([page for page, _ in matches], [0, 0, 1])

    def test_empty_or_missing_query_returns_empty(self):
        self.assertEqual(search_pdf_matches(str(self.pdf_path), "   "), [])
        self.assertEqual(search_pdf_matches(str(self.pdf_path), "nonexistentphrase"), [])
        self.assertEqual(search_pdf_matches(None, "neural"), [])


class CtrlFIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pdf_path = Path(cls.tmp.name) / "sample.pdf"
        _make_two_page_pdf(cls.pdf_path)
        from ui.main_window import PDFReader
        cls.window = PDFReader()
        cls.window.resize(1100, 700)
        cls.window.show()
        _wait(cls.app, 50)

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        cls.tmp.cleanup()

    def test_ctrl_f_on_start_page_focuses_history_search(self):
        self.window.stack.setCurrentIndex(0)
        self.window.start_page.search_input.setText("praca")
        self.window.start_page.search_input.clearFocus()
        self.window._handle_find()
        _wait(self.app, 30)
        self.assertEqual(self.window.start_page.search_input.selectedText(), "praca")
        self.assertIn("Ctrl+F", self.window.start_page.search_input.toolTip())

    def test_ctrl_f_in_reader_searches_navigates_and_closes_on_escape(self):
        self.window.load_pdf(str(self.pdf_path))
        self.window.stack.setCurrentIndex(1)
        _wait(self.app, 80)

        self.window._handle_find()
        self.assertTrue(self.window.pdf_find_bar.isVisible())

        bar = self.window.pdf_find_bar
        bar.input.setText("neural")
        bar._run_search()
        _wait(self.app, 40)

        self.assertEqual(bar.count_label.text(), "1 / 3")
        self.assertEqual(len(self.window.pdf_view._search_matches), 3)
        self.assertEqual(self.window.pdf_view._search_current, 0)

        # Enter advances to next match and wraps around
        QTest.keyClick(bar.input, Qt.Key_Return)
        self.assertEqual(bar.count_label.text(), "2 / 3")
        QTest.keyClick(bar.input, Qt.Key_Return)
        self.assertEqual(bar.count_label.text(), "3 / 3")
        QTest.keyClick(bar.input, Qt.Key_Return)
        self.assertEqual(bar.count_label.text(), "1 / 3")

        # Shift+Enter moves backwards and wraps to last match
        QTest.keyClick(bar.input, Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(bar.count_label.text(), "3 / 3")

        # Non-matching query displays 0 / 0 and clears highlights
        bar.input.setText("zzzznotfound")
        bar._run_search()
        self.assertEqual(bar.count_label.text(), "0 / 0")
        self.assertEqual(self.window.pdf_view._search_matches, [])

        # Escape closes the find bar without leaving the PDF reader
        self.window._escape_back()
        self.assertFalse(bar.isVisible())
        self.assertEqual(self.window.stack.currentIndex(), 1)
        self.assertEqual(self.window.pdf_view._search_matches, [])

    def test_ctrl_f_prefills_selected_pdf_text(self):
        self.window.load_pdf(str(self.pdf_path))
        self.window.stack.setCurrentIndex(1)
        self.window.pdf_view.selected_text = "neural"
        self.window._handle_find()
        _wait(self.app, 40)
        self.assertEqual(self.window.pdf_find_bar.input.text(), "neural")
        self.assertEqual(self.window.pdf_find_bar.count_label.text(), "1 / 3")
        self.window.pdf_find_bar.close_bar()


if __name__ == "__main__":
    unittest.main()
