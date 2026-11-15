"""Clickable spelling affordances remain transient viewport widgets."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ui.select_text import ErrorMarker, SelectablePdfView, SpellingHighlightBox
except ImportError as error:
    raise unittest.SkipTest(str(error))


class SpellingHighlightsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = SelectablePdfView()
        self.view.resize(600, 400)
        self.view.show()
        self.error = {'page': 0, 'category': 'TYPOS', 'found_text': 'wyraz',
                      'comment': 'Spelling finding', 'coords': {'x': 50, 'y': 100, 'w': 80, 'h': 16},
                      'extra_rects': [{'page': 1, 'coords': {'x': 60, 'y': 100, 'w': 40, 'h': 16}}]}

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    def test_only_spelling_errors_become_clickable_without_mutating_saved_findings(self):
        grammar = dict(self.error, category='PUNCTUATION', extra_rects=[])
        findings = [self.error, grammar]
        original = copy.deepcopy(findings)
        self.view.add_errors(findings)
        spelling = [box for box in self.view.highlight_boxes if isinstance(box, SpellingHighlightBox)]
        self.assertEqual(len(spelling), 2)
        self.assertEqual(findings, original)
        for box in spelling:
            self.assertFalse(box.testAttribute(Qt.WA_TransparentForMouseEvents))
            self.assertEqual(box.cursor().shape(), Qt.PointingHandCursor)
            self.assertTrue(box.accessibleName())
        grammar_box = self.view.highlight_boxes[-1]
        self.assertTrue(grammar_box.testAttribute(Qt.WA_TransparentForMouseEvents))

    def test_word_click_and_keyboard_open_the_proposal_form(self):
        with patch.object(ErrorMarker, 'open_proposal') as propose:
            self.view.add_errors([self.error])
            box = self.view.highlight_boxes[0]
            box.setGeometry(40, 60, 100, 24)
            box.show()
            QTest.mouseClick(box, Qt.LeftButton)
            self.assertEqual(propose.call_count, 1)
            QTest.keyClick(box, Qt.Key_Return)
            QTest.keyClick(box, Qt.Key_Space)
            self.assertEqual(propose.call_count, 3)
            QTest.mouseClick(box, Qt.LeftButton, Qt.ShiftModifier)
            self.assertEqual(propose.call_count, 3)

    def test_extra_rectangle_uses_the_same_finding_context_menu(self):
        self.view.add_errors([self.error])
        with patch.object(self.view.markers[0], 'proposal_menu') as menu:
            self.view.highlight_boxes[1].customContextMenuRequested.emit(QPoint(2, 3))
            menu.assert_called_once()


if __name__ == '__main__':
    unittest.main()
