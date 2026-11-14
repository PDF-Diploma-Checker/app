"""The annotated PDF written by the export."""

import os
import sys
import tempfile
import types
import unittest
from unittest import mock

import fitz

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError as error:    # e.g. a CI runner without the system libraries Qt needs (libEGL)
    raise unittest.SkipTest(f"Qt is not available: {error}")


def rect_coords(x, y, w=200, h=14):
    return {"x": x, "y": y, "w": w, "h": h}


class ExtraRectsExportTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = os.path.join(tmp.name, "thesis.pdf")
        self.target = os.path.join(tmp.name, "annotated.pdf")
        doc = fitz.open()
        for _ in range(2):
            doc.new_page()
        doc.save(self.source)
        doc.close()

    def export(self, errors):
        from ui import main_window
        reader = types.SimpleNamespace(
            current_pdf_path=self.source,
            manager=mock.Mock(**{"get_errors.return_value": errors, "get_comments.return_value": []}),
        )
        with mock.patch.object(main_window.QFileDialog, "getSaveFileName", return_value=(self.target, "")), \
                mock.patch.object(main_window, "MessageBox"):
            main_window.PDFReader.export_pdf_with_annotations(reader)

    def test_global_findings_and_summary_are_not_pdf_annotations(self):
        self.export([
            {"page": 0, "category": "bibliography_summary", "found_text": "[1] Book"},
            {"page": 0, "category": "config_file", "comment": "The font used (Arial) is incorrect"},
            {"page": 1, "category": "No_footer", "coords": rect_coords(50, 100)},
            {"page": 0, "category": "SPELLING", "coords": rect_coords(50, 100)},
        ])
        with fitz.open(self.target) as doc:
            self.assertEqual([len(list(page.annots() or [])) for page in doc], [1, 0])

    def highlights(self):
        """Per page, the vertical middle and the stroke colour of each highlight in the saved PDF."""
        doc = fitz.open(self.target)
        self.addCleanup(doc.close)
        return [
            sorted(
                (round((a.rect.y0 + a.rect.y1) / 2), a.colors["stroke"])
                for a in page.annots(types=[fitz.PDF_ANNOT_HIGHLIGHT])
            )
            for page in doc
        ]

    def test_every_rectangle_of_a_multiline_finding_is_highlighted(self):
        errors = [{
            "page": 0,
            "coords": rect_coords(72, 100),
            "category": "Styl",
            "comment": "Uwaga",
            "found_text": "tekst",
            "extra_rects": [
                {"page": 0, "coords": rect_coords(72, 120)},
                {"page": 0, "coords": rect_coords(72, 140)},
                {"page": 1, "coords": rect_coords(72, 60)},
            ],
        }]

        with self.assertNoLogs("ui.main_window", level="ERROR"):
            self.export(errors)

        pages = self.highlights()
        self.assertEqual([middle for middle, _ in pages[0]], [107, 127, 147])
        self.assertEqual([middle for middle, _ in pages[1]], [67])
        for _, stroke in pages[0] + pages[1]:
            self.assertAlmostEqual(stroke[0], 0.95, places=2)
            self.assertAlmostEqual(stroke[1], 0.35, places=2)
            self.assertAlmostEqual(stroke[2], 0.35, places=2)
