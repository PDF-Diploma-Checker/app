import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtWidgets import QApplication, QToolButton
from PySide6.QtCore import Qt
from common.figure_findings import figure_details
from ui.report_panel import build_report_panel
from ui import styles

class UncheckedFiguresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_saved_unknown_results_are_separate_and_deduplicated(self):
        line = 'Rysunek 2.1: Nie przeanalizowano - Szczegóły: Brak wyniku'
        bad = 'Rysunek 3: Wykryto rozbieżności - Szczegóły: 20 zamiast 40'
        self.assertEqual(figure_details({'problem_details': [line, line, bad]}), ([bad], [line]))
        self.assertEqual(figure_details({'details': ['Figure 1: Not analysed - Details: No result']}),
                         ([], ['Figure 1: Not analysed - Details: No result']))

    def test_unknown_list_is_yellow_collapsed_and_expandable_without_grade(self):
        panel, _ = build_report_panel({'image_analysis': {'total': 1, 'problem_details': [
            'Rysunek 2.1: Nie przeanalizowano - Szczegóły: Brak wyniku']}}, lambda: None)
        toggle = panel.findChild(QToolButton, 'UncheckedFiguresToggle')
        details = panel.findChild(type(panel), 'UncheckedFiguresDetails')
        self.assertIsNotNone(toggle)
        self.assertIn(styles.WARNING, toggle.styleSheet())
        self.assertTrue(details.isHidden())
        toggle.click()
        self.assertFalse(details.isHidden())
        self.assertEqual(toggle.arrowType(), Qt.DownArrow)
