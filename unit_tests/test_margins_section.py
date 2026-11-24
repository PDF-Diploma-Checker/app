"""Inconsistent margins are one finding for the thesis: shown as their own section, for all the pages or as ranges."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.findings import MARGINS_WHOLE_SHARE, finding_kind, margin_summary, page_ranges


def _finding(pages, evaluated):
    return {"category": "inconsistent_margins", "page": 1, "comment": "c",
            "found_text": json.dumps({"pages": pages, "evaluated": evaluated})}


class MarginSummaryTest(unittest.TestCase):
    def test_kind_is_its_own_section_not_a_marker(self):
        self.assertEqual(finding_kind(_finding([2], 10)), "margins")
        legacy = {"category": "config_file", "comment": "Niespójne marginesy lustrzane: lewy=50.0, prawy=30.0.", "page": 4}
        self.assertEqual(finding_kind(legacy), "margins")
        self.assertEqual(finding_kind({"category": "config_file", "comment": "Page orientation is incorrect"}), "page")

    def test_most_of_the_thesis_marks_the_whole_thesis(self):
        summary = margin_summary([_finding(list(range(1, 36)), 50)])         # 70%
        self.assertTrue(summary["whole"])
        self.assertEqual(MARGINS_WHOLE_SHARE, 0.7)

    def test_a_few_pages_are_listed(self):
        summary = margin_summary([_finding([2, 3, 4, 9], 50)])
        self.assertFalse(summary["whole"])
        self.assertEqual((summary["pages"], summary["evaluated"]), ([2, 3, 4, 9], 50))

    def test_just_below_the_limit_is_not_the_whole_thesis(self):
        self.assertFalse(margin_summary([_finding(list(range(1, 35)), 50)])["whole"])    # 68%

    def test_findings_of_an_older_version_give_pages_but_never_the_whole_thesis(self):
        legacy = [{"category": "config_file", "comment": "Inconsistent mirror margins: left=1.0, right=2.0.", "page": p}
                  for p in (5, 6, 8)]
        summary = margin_summary(legacy)
        self.assertEqual((summary["pages"], summary["evaluated"], summary["whole"]), ([5, 6, 8], None, False))

    def test_no_margin_findings(self):
        self.assertIsNone(margin_summary([{"category": "TYPOS", "comment": "x", "page": 1}]))
        self.assertIsNone(margin_summary(None))

    def test_ranges(self):
        self.assertEqual(page_ranges([10, 2, 3, 4, 7, 9, 3]), [(2, 4), (7, 7), (9, 10)])
        self.assertEqual(page_ranges([]), [])


try:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
except Exception as error:      # pragma: no cover
    raise unittest.SkipTest(f"Qt is not available: {error}")


class MarginsPanelTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def panel(self, errors, shown=None):
        from ui.report_panel import build_report_panel
        content, _ = build_report_panel({}, lambda: None, errors, (shown if shown is not None else []).append)
        return content

    def texts(self, content):
        return " | ".join(label.text() for label in content.findChildren(QLabel))

    def test_pages_as_ranges_that_open_their_first_page(self):
        shown = []
        content = self.panel([_finding([1, 2, 3, 4, 8], 50)], shown)
        texts = self.texts(content)
        self.assertIn("Niespójne marginesy", texts)
        self.assertIn("Błędne marginesy: 5 z 50 stron", texts)
        buttons = {b.text(): b for b in content.findChildren(QPushButton)}
        self.assertIn("str. 2–5", buttons)             # pages are counted from 0 in the findings
        self.assertIn("str. 9", buttons)
        buttons["str. 2–5"].click()
        self.assertEqual(shown, [1])

    def test_whole_thesis_says_so_without_page_buttons(self):
        content = self.panel([_finding(list(range(1, 41)), 50)])
        self.assertIn("Cała praca", self.texts(content))
        self.assertIn("80%", self.texts(content))
        self.assertFalse([b for b in content.findChildren(QPushButton) if b.text().startswith("str. ")])

    def test_no_margin_findings_no_section(self):
        content = self.panel([{"category": "TYPOS", "comment": "x", "page": 1}])
        self.assertNotIn("Niespójne marginesy", self.texts(content))

    def test_margins_are_not_markers_on_the_pages(self):
        from ui.select_text import SelectablePdfView
        view = SelectablePdfView()
        view.add_errors([_finding([1, 2], 10)], lang="pl")
        self.assertEqual(len(view.markers), 0)
        view.close()


if __name__ == "__main__":
    unittest.main()
