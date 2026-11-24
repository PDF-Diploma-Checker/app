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
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton, QToolButton, QWidget
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

    def test_page_count_is_a_global_document_finding(self):
        shown = "The document has 42 pages, less than the minimum number of 50."
        for comment in ("Dokument ma 42 stron, mniej niż minimalna liczba 50",
                        "The document has 42 pages, less than the minimum number of 50"):
            with self.subTest(comment=comment):
                error = {"category": "config_file", "comment": comment}
                self.assertEqual(finding_kind(error), "global")
                panel, _ = build_report_panel({}, lambda: None, [error])
                self.assertTrue(any(shown in label.text() for label in panel.findChildren(QLabel)))
                view = SelectablePdfView()
                view.add_errors([error], lang="en")
                self.assertEqual(len(view.markers), 0)
                view.close()

    def test_raster_information_has_navigation_without_pdf_markers(self):
        error = {"category": "raster_image", "page": 3,
                 "found_text": "Figure 6.1", "comment": "Raster image detected",
                 "coords": {"x": 20, "y": 30, "w": 40, "h": 20}}
        self.assertEqual(finding_kind(error), "raster")
        visited = []
        panel, _ = build_report_panel(None, lambda: None, [error], visited.append)
        button = next(b for b in panel.findChildren(QPushButton) if "4 (1)" in b.text())
        button.click()
        self.assertEqual(visited, [3])
        self.assertTrue(any("Figure 6.1" in l.text() for l in panel.findChildren(QLabel)))
        view = SelectablePdfView()
        view.add_errors([error], lang="en")
        self.assertEqual(len(view.markers), 0)
        self.assertEqual(len(view.highlight_boxes), 0)
        view.close()
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "report.pdf")
            build_report_pdf({}, "Thesis", "en", path, findings=[error] + self.errors)
            with fitz.open(path) as pdf:
                text = " ".join(page.get_text() for page in pdf)
            for phrase in ("Raster images", "PDF page 4", "Figure 6.1", "Arial", "Bibliography"):
                self.assertIn(phrase, text)

    def test_long_bibliography_scrolls_in_its_own_box(self):
        errors = copy.deepcopy(self.errors)
        errors[0]["found_text"] += "\n" + "\n".join(f"Entry {i}: A recognized bibliography item" for i in range(150))
        panel, _ = build_report_panel({}, lambda: None, errors)
        details = panel.findChild(QPlainTextEdit, "BibliographyDetails")
        self.assertIn("Entry 149", details.toPlainText())
        self.assertLessEqual(details.height(), 300)

    def test_figures_without_a_source_are_a_collapsed_list_not_page_findings(self):
        error = {"category": "missing_caption_source", "page": 5, "found_text": "Rys. 2.1 Schemat",
                 "comment": "The caption does not contain a reference", "coords": {"x": 1, "y": 1, "w": 1, "h": 1}}
        self.assertEqual(finding_kind(error), "caption_source")
        visited = []
        panel, _ = build_report_panel({}, lambda: None, [error], visited.append)
        toggle = panel.findChild(QToolButton, "CaptionSourceToggle")
        details = panel.findChild(QWidget, "CaptionSourceDetails")
        self.assertIn("(1)", toggle.text())
        self.assertTrue(details.isHidden())
        toggle.click()
        self.assertFalse(details.isHidden())
        next(b for b in details.findChildren(QPushButton) if "6 (1)" in b.text()).click()
        self.assertEqual(visited, [5])
        self.assertFalse(any(label.text().startswith("Findings:") for label in panel.findChildren(QLabel)))
        view = SelectablePdfView()
        view.add_errors([error], lang="en")
        self.assertEqual(len(view.markers), 0)
        view.close()

    def test_word_level_config_findings_mentioning_fonts_stay_on_page(self):
        for comment in ("Incorrect font for this word", "Niepoprawna czcionka w tym słowie"):
            with self.subTest(comment=comment):
                self.assertEqual(finding_kind({"category": "config_file", "comment": comment}), "page")

    def test_all_numbering_categories_are_global(self):
        for category in NUMBERING_CATEGORIES:
            with self.subTest(category=category):
                self.assertEqual(finding_kind({"category": category}), "global")

    def test_collapsible_summary_and_only_local_page_buttons(self):
        original = copy.deepcopy(self.errors)
        panel, _ = build_report_panel({}, lambda: None, self.errors)
        details = panel.findChild(QPlainTextEdit, "BibliographyDetails")
        self.assertIn("Example <Book>", details.toPlainText())
        toggle = next(button for button in panel.findChildren(QToolButton) if button.isCheckable() and button.objectName() != "FindingsListToggle")
        self.assertTrue(details.isHidden())
        self.assertEqual(toggle.toolButtonStyle(), Qt.ToolButtonTextBesideIcon)
        self.assertEqual(toggle.arrowType(), Qt.RightArrow)
        toggle.click()
        self.assertFalse(details.isHidden())
        self.assertEqual(toggle.arrowType(), Qt.DownArrow)
        toggle.click()
        self.assertTrue(details.isHidden())
        self.assertEqual(toggle.arrowType(), Qt.RightArrow)
        texts = [button.text() for button in panel.findChildren(QPushButton)]
        self.assertTrue(any("1 (1)" in text for text in texts))
        self.assertFalse(any("4 (1)" in text for text in texts))
        self.assertEqual(self.errors, original)

    def test_word_proposal_hint_is_visible_without_ai_results(self):
        panel, _ = build_report_panel(None, lambda: None, [{"category": "TYPOS", "page": 0}])
        self.assertTrue(any("Right-click" in label.text() for label in panel.findChildren(QLabel)))

    def test_global_and_bibliography_sections_follow_analysis_results(self):
        data = {"content_grade": {"grade": 80}, "statystyki_zdan": {"active_ratio": 70}}
        errors = self.errors + [{"category": "TYPOS", "page": 0}]
        panel, download = build_report_panel(data, lambda: None, errors)
        titles = []
        for i in range(panel.layout().count()):
            widget = panel.layout().itemAt(i).widget()
            if widget is not None:
                titles.extend(label.text() for label in widget.findChildren(QLabel)
                              if label.text() in {"Global findings", "Bibliography", "Sentence statistics"})
        self.assertEqual(titles[-2:], ["Global findings", "Bibliography"])
        self.assertTrue(any("Right-click" in label.text() for label in panel.findChildren(QLabel)))
        # the button is last, followed only by the stretch that keeps spare height out of the cards
        self.assertIsNotNone(panel.layout().itemAt(panel.layout().count() - 1).spacerItem())
        self.assertIs(panel.layout().itemAt(panel.layout().count() - 2).widget(), download)
        self.assertIsNotNone(panel.layout().itemAt(panel.layout().count() - 3).widget())
        self.assertTrue(panel.layout().alignment() & Qt.AlignTop)

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
