"""Page findings in the right panel are grouped into subsections by category."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")

from common.findings import (
    CATEGORY_ORDER,
    assign_finding_ids,
    finding_category_key,
    group_findings_by_category,
)
from ui.translations import PHRASES


def _err(page, y, category, **extra):
    return dict(
        {"category": category, "comment": f"comment {category}", "page": page,
         "coords": {"x": 10, "y": y, "w": 20, "h": 10}},
        **extra,
    )


class FindingsCategoryGroupingTest(unittest.TestCase):
    def test_groups_by_category_and_keeps_reading_order_ids(self):
        errors = assign_finding_ids([
            _err(0, 100, "widow"),          # #1
            _err(1, 50, "TYPOS"),           # #2
            _err(2, 20, "widow"),           # #3
            _err(3, 10, "TYPOS"),           # #4
            {"category": "No_footer", "comment": "global", "scope": "global"},
        ])
        groups = group_findings_by_category(errors)
        self.assertEqual([(key, [e["finding_id"] for e in items]) for key, _raw, items in groups], [
            ("typos", [2, 4]),
            ("widow", [1, 3]),
        ])

    def test_order_known_then_unknown_alphabetical_then_uncategorized(self):
        errors = assign_finding_ids([
            {"page": 0, "comment": "no cat"},
            _err(1, 10, "Zebra_rule"),
            _err(1, 20, "widow"),
            _err(1, 30, "Alpha_rule"),
            _err(1, 40, "PUNCTUATION"),
            _err(1, 50, "TYPOS"),
        ])
        keys = [key for key, _raw, _items in group_findings_by_category(errors)]
        self.assertEqual(keys, ["typos", "punctuation", "widow", "alpha_rule", "zebra_rule", ""])

    def test_case_insensitive_legacy_key_and_alias(self):
        self.assertEqual(finding_category_key({"category": "incorrect bibiography refference"}),
                         "incorrect_bibliography_reference")
        self.assertEqual(finding_category_key({"kategoria": "Widow"}), "widow")
        errors = assign_finding_ids([
            _err(0, 10, "widow"),
            {"kategoria": "Widow", "page": 1, "coords": {"x": 0, "y": 5}},
        ])
        groups = group_findings_by_category(errors)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0], "widow")
        self.assertEqual(len(groups[0][2]), 2)

    def test_all_ordered_categories_have_pl_and_en_labels(self):
        for lang in ("pl", "en"):
            labels = PHRASES[lang]["finding_categories"]
            self.assertIn("other", labels)
            for key in CATEGORY_ORDER:
                self.assertIn(key, labels, f"Missing {lang} label for category {key!r}")


try:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
except ImportError as error:    # pragma: no cover
    raise unittest.SkipTest(f"Qt is not available: {error}")


class FindingsCategoryPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        from ui.i18n import set_locale
        set_locale("pl")

    def _groups(self, panel):
        return [
            (
                group.findChild(QLabel, "FindingCategoryHeader").text(),
                [btn.text() for btn in group.findChildren(QPushButton)],
            )
            for group in panel.findChildren(QWidget, "FindingCategoryGroup")
        ]

    def test_typos_and_widows_are_separate_subsections_in_pl_and_en(self):
        from ui.i18n import set_locale
        from ui.report_panel import build_report_panel

        errors = [
            _err(0, 100, "widow"),   # #1 on p. 1
            _err(1, 50, "TYPOS"),    # #2 on p. 2
            _err(2, 20, "widow"),    # #3 on p. 3
            _err(4, 10, "TYPOS"),    # #4 on p. 5
        ]
        visited = []
        set_locale("pl")
        panel_pl, _ = build_report_panel({}, lambda: None, errors, visited.append)
        self.assertEqual(self._groups(panel_pl), [
            ("Literówki (2)", ["#2  str. 2", "#4  str. 5"]),
            ("Wdowy (2)", ["#1  str. 1", "#3  str. 3"]),
        ])
        widow_group = next(
            g for g in panel_pl.findChildren(QWidget, "FindingCategoryGroup")
            if g.property("findingCategory") == "widow"
        )
        next(b for b in widow_group.findChildren(QPushButton) if b.text() == "#3  str. 3").click()
        self.assertEqual(visited, [2])

        set_locale("en")
        panel_en, _ = build_report_panel({}, lambda: None, errors)
        self.assertEqual(self._groups(panel_en), [
            ("Typos (2)", ["#2  p. 2", "#4  p. 5"]),
            ("Widows (2)", ["#1  p. 1", "#3  p. 3"]),
        ])

    def test_unknown_and_missing_categories_and_layout_height(self):
        from ui.i18n import set_locale
        from ui.report_panel import build_report_panel

        set_locale("pl")
        errors = [
            _err(0, 10, "incorrect bibiography refference"),
            _err(1, 10, "CustomCategory"),
            {"page": 2, "comment": "plain"},
        ] + [_err(p, 20, "TYPOS") for p in range(10)]
        panel, _ = build_report_panel({}, lambda: None, errors)
        self.assertEqual(
            [header for header, _buttons in self._groups(panel)],
            [
                "Literówki (10)",
                "Błędne odwołania do bibliografii (1)",
                "CustomCategory (1)",
                "Inne uwagi (1)",
            ],
        )
        panel.resize(340, 800)
        panel.show()
        self.app.processEvents()
        for group in panel.findChildren(QWidget, "FindingCategoryGroup"):
            self.assertGreater(group.height(), 20)
        panel.close()


if __name__ == "__main__":
    unittest.main()
