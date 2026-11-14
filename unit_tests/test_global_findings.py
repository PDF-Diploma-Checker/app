"""Global findings survive persistence and exports without becoming PDF markers."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")

import fitz
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from common.findings import NUMBERING_CATEGORIES, finding_kind
from ui.i18n import set_locale
from ui.report_panel import build_report_panel
from ui.report_pdf import build_report_pdf
from ui.select_text import SelectablePdfView
from ui.saving_files import SavingFiles


class GlobalFindingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_locale("en")
        self.errors = [
            {"page": 2, "category": "bibliography_summary", "found_text": "[1] Example <Book>", "comment": "Recognized entries"},
            {"page": 1, "category": "config_file", "comment": "The font used (Arial) does not match the required font."},
            {"page": 3, "category": "Wrong_page_number", "comment": "Invalid page number. Detected: 9, expected: 4."},
            {"page": 0, "category": "SPELLING", "comment": "A spelling error", "coords": {"x": 20, "y": 30, "w": 40, "h": 12}},
        ]

    def tearDown(self):
        set_locale("pl")

    def test_legacy_categories_and_page_specific_config(self):
        self.assertEqual([finding_kind(e) for e in self.errors], ["bibliography", "global", "global", "page"])
        self.assertEqual(finding_kind({"category": "config_file", "comment": "Page orientation is incorrect"}), "page")
        self.assertEqual(finding_kind({"category": "config_file", "comment": "Używany rozmiar czcionki (10)"}), "global")

    def test_all_numbering_categories_are_global(self):
        for category in NUMBERING_CATEGORIES:
            with self.subTest(category=category):
                self.assertEqual(finding_kind({"category": category}), "global")

    def test_collapsible_summary_and_only_local_page_buttons(self):
        original = copy.deepcopy(self.errors)
        panel, _ = build_report_panel({}, lambda: None, self.errors)
        details = next(label for label in panel.findChildren(QLabel) if "Example <Book>" in label.text())
        toggle = next(button for button in panel.findChildren(QPushButton) if button.isCheckable())
        self.assertTrue(details.isHidden())
        toggle.click()
        self.assertFalse(details.isHidden())
        toggle.click()
        self.assertTrue(details.isHidden())
        texts = [button.text() for button in panel.findChildren(QPushButton)]
        self.assertTrue(any("1 (1)" in text for text in texts))
        self.assertFalse(any("4 (1)" in text for text in texts))
        self.assertEqual(self.errors, original)

    def test_reader_excludes_global_markers_after_json_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder) / "index.json"
            manager = SavingFiles(index)
            manager.add_document("Thesis", "thesis.pdf")
            manager.save_errors("thesis.pdf", self.errors)
            saved = SavingFiles(index).get_errors("thesis.pdf")
        self.assertEqual(saved, self.errors)
        view = SelectablePdfView()
        view.add_errors(saved, lang="en")
        self.assertEqual(len(view.markers), 1)
        self.assertEqual(len(view.highlight_boxes), 1)
        view.close()

    def test_detailed_report_retains_global_and_bibliography_text(self):
        with tempfile.TemporaryDirectory() as folder:
            target = str(Path(folder) / "report.pdf")
            errors = copy.deepcopy(self.errors)
            errors[0]["found_text"] += "\n" + "\n".join(f"Entry {i}: A recognized bibliography item" for i in range(150))
            build_report_pdf({}, "Thesis", "en", target, findings=errors)
            with fitz.open(target) as pdf:
                text = "\n".join(page.get_text() for page in pdf)
            for phrase in ("Global findings", "Bibliography", "Example <Book>", "Arial", "Invalid page number", "Entry 149"):
                self.assertIn(phrase, text)
