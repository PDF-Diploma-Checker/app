"""The reader opens a document behind a skeleton, and the application-wide event filters survive odd objects."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
PDF = REPO_ROOT / "unit_tests" / "extraction" / "math_accents" / "tp_math_accents_pdflatex.pdf"

_HOME = tempfile.mkdtemp(prefix="dc_test_home_")
os.environ["DIPLOMACHECKER_HOME"] = _HOME

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402


def _wait(app, ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


class ReaderOpenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from ui.main_window import PDFReader
        cls.window = PDFReader()
        cls.window.resize(1100, 700)
        cls.window.show()

    def test_mouse_back_button_returns_from_the_reader(self):
        # handled by the window itself: an application-wide event filter would slow every event of the UI down
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.stack.setCurrentIndex(1)
        QTest.mouseClick(self.window, Qt.BackButton)
        _wait(self.app, 50)
        self.assertEqual(self.window.stack.currentIndex(), 0)

    def test_tabular_on_a_visible_widget_does_not_raise(self):
        from ui import motion
        label = QLabel("123")
        label.show()
        motion.tabular(label)
        self.assertTrue(label.property("tabular"))

    def test_opening_shows_the_skeleton_first_and_then_the_document(self):
        window = self.window
        window.manager.add_document(PDF.name, str(PDF), "PDF")
        window.open_existing_file(str(PDF))
        self.assertEqual(window.stack.currentIndex(), 1)
        self.assertTrue(window.doc_skeleton.isVisible())          # before the document is parsed
        self.assertEqual(window.document.pageCount(), 0)
        _wait(self.app, 700)
        self.assertGreater(window.document.pageCount(), 0)
        self.assertFalse(window.doc_skeleton.isVisible())
        self.assertEqual(len(window.thumb_buttons), window.document.pageCount())


if __name__ == "__main__":
    unittest.main()
