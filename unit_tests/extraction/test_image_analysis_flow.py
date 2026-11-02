'''
Testy części analizy rysunków, która nie wymaga modeli ani GPU.

Uruchomienie (z katalogu głównego repozytorium):
    .venv/bin/python -m unittest unit_tests.extraction.test_image_analysis_flow -v
'''
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

import fitz  # noqa: E402

from analysis.extraction.helper_llm.extraction_json_llm import extractPDF_llm  # noqa: E402
from analysis.extraction.main_extractor import extractPDF  # noqa: E402
from analysis.modules.llm.image_analysis.figures import (  # noqa: E402
    collect_figures,
    figure_sort_key,
    is_caption,
    reference_pattern,
)
from analysis.modules.llm.image_analysis.reference_matcher import ReferenceMatcher  # noqa: E402


def make_pdf(path, captions):
    doc = fitz.open()
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 200), False)
    pixmap.clear_with(255)
    for x in range(300):
        for y in range(0, 200, 7):
            pixmap.set_pixel(x, y, (x % 255, 10, 200))
    for caption in captions:
        page = doc.new_page()
        page.insert_image(fitz.Rect(150, 100, 450, 300), pixmap=pixmap)
        page.insert_text((150, 320), caption)
    doc.save(path)
    doc.close()


class ExtractedPdfCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_captions_in_every_supported_form_are_found(self):
        make_pdf("t.pdf", ["Rysunek 1. A", "Rys. 2.1. B", "Figure 3. C", "Wykres 1. D"])
        figures = collect_figures(extractPDF("t.pdf"))
        self.assertEqual([f["id"] for f in figures], ["Rysunek 1", "Rys. 2.1", "Figure 3", "Wykres 1"])
        self.assertTrue(all(f["bytes"] for f in figures))

    def test_images_survive_the_llm_extraction(self):
        '''The LLM stage extracts the PDF again, before the figures are read.'''
        make_pdf("t.pdf", ["Rysunek 1. A", "Rysunek 2. B"])
        doc = extractPDF("t.pdf")
        before = {i.path: Path(i.path).read_bytes() for p in doc.pages for i in p.images}
        extractPDF_llm("t.pdf")
        self.assertEqual({path: Path(path).read_bytes() for path in before}, before)
        self.assertEqual(len(collect_figures(doc)), 2)


class CollectFiguresTest(unittest.TestCase):
    def _doc(self, *images):
        return SimpleNamespace(pages=[SimpleNamespace(images=list(images))])

    def test_uncaptioned_image_is_skipped_and_largest_piece_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            small, big = Path(tmp, "small.png"), Path(tmp, "big.png")
            small.write_bytes(b"small")
            big.write_bytes(b"big")
            doc = self._doc(
                SimpleNamespace(path=str(small), bbox=(0, 0, 10, 10), description="Rys. 1. X", image_type="raster"),
                SimpleNamespace(path=str(big), bbox=(0, 0, 90, 90), description="Rys. 1. X", image_type="raster"),
                SimpleNamespace(path=str(big), bbox=(0, 0, 90, 90), description="", image_type="vector"),
            )
            figures = collect_figures(doc)
        self.assertEqual([f["bytes"] for f in figures], [b"big"])

    def test_missing_file_does_not_stop_the_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp, "good.png")
            good.write_bytes(b"ok")
            doc = self._doc(
                SimpleNamespace(path=str(Path(tmp, "gone.png")), bbox=(0, 0, 9, 9), description="Rys. 1", image_type="raster"),
                SimpleNamespace(path=str(good), bbox=(0, 0, 9, 9), description="Rys. 2", image_type="raster"),
            )
            self.assertEqual([f["number"] for f in collect_figures(doc)], ["2"])


class ReferencesTest(unittest.TestCase):
    def test_polish_cases_are_recognised(self):
        for text in ("Na rysunku 2 widać", "rysunek 2 pokazuje", "zob. rys. 2", "(rys.2)", "Na rysunkach 2"):
            self.assertTrue(reference_pattern("2").search(text), text)
        self.assertTrue(reference_pattern("3", "wykres").search("na wykresie 3 widać"))
        self.assertTrue(reference_pattern("1").search("as shown in Figure 1, values"))

    def test_other_numbers_and_series_do_not_match(self):
        pattern = reference_pattern("2")
        for text in ("rysunku 21", "rysunku 2.1", "wykresie 2", "morys 2"):
            self.assertIsNone(pattern.search(text), text)

    def test_sentence_ending_right_after_the_number_matches(self):
        self.assertTrue(reference_pattern("2").search("widać to na rysunku 2."))

    def test_matcher_keeps_only_paragraphs_about_the_figure(self):
        paragraphs = ["Na rysunku 2 widać wzrost.", "Na wykresie 2 widać spadek.", "Bez odwołań."]
        self.assertEqual(ReferenceMatcher().find_references(paragraphs, "2"), paragraphs[:1])

    def test_caption_is_not_a_discussion_of_the_figure(self):
        self.assertTrue(is_caption("Rysunek 1. Architektura systemu", "1"))
        self.assertTrue(is_caption("Rys. 1 Architektura", "1"))
        self.assertFalse(is_caption("Rysunek 1 przedstawia architekturę systemu oraz wszystkie jej moduły w szczegółach.", "1"))
        self.assertFalse(is_caption("Jak pokazano na rysunku 1, system działa.", "1"))

    def test_natural_sort(self):
        labels = ["Rys. 2.10", "Rys. 2.9", "Rys. 1"]
        self.assertEqual(sorted(labels, key=figure_sort_key), ["Rys. 1", "Rys. 2.9", "Rys. 2.10"])


class SummaryTest(unittest.TestCase):
    def test_summary_counts_figures_not_paragraphs(self):
        from app.llm_task import build_image_summary

        summary = build_image_summary([
            {"obrazek": "Rys. 1", "poprawnosc_danych": "True", "bledy": "None"},
            {"obrazek": "Rys. 1", "poprawnosc_danych": "False", "bledy": "x"},
            {"obrazek": "Rys. 1", "poprawnosc_danych": "True", "bledy": "None"},
            {"obrazek": "Rys. 2", "poprawnosc_danych": "True", "bledy": "None"},
            {"obrazek": "Rys. 3", "poprawnosc_danych": "Error", "bledy": "y"},
        ])
        self.assertEqual((summary["total"], summary["bad_count"], summary["good_count"]), (3, 1, 1))
        self.assertTrue(summary["analysis_failed"])

    def test_empty_report_is_not_a_failure(self):
        from app.llm_task import build_image_summary

        self.assertFalse(build_image_summary([])["analysis_failed"])


class ReportPanelTest(unittest.TestCase):
    def _texts(self, image_analysis):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QLabel

        self.app = QApplication.instance() or QApplication([])
        from ui.report_panel import build_report_panel

        data = {"content_grade": {"grade": 50, "max_grade": 100}, "image_analysis": image_analysis}
        content, _ = build_report_panel(data, lambda: None)
        return " | ".join(label.text() for label in content.findChildren(QLabel))

    def test_panel_shows_llm_counts_and_only_the_problems(self):
        from app.llm_task import build_image_summary

        text = self._texts(build_image_summary([
            {"obrazek": "Rys. 1", "poprawnosc_danych": "True", "bledy": "None"},
            {"obrazek": "Rys. 2", "poprawnosc_danych": "False", "bledy": "Zla wartosc"},
        ]))
        self.assertIn("Zla wartosc", text)
        self.assertNotIn("Rys. 1:", text)
        for number in ("2", "1"):
            self.assertIn(number, text)

    def test_report_saved_before_this_change_still_opens(self):
        text = self._texts({"total": 1, "bad_count": 0, "good_count": 1, "details": ["Rys. 1: Poprawny"]})
        self.assertNotIn("Rys. 1:", text)

    def test_all_correct_lists_no_problems(self):
        from app.llm_task import build_image_summary

        summary = build_image_summary([{"obrazek": "Rys. 1", "poprawnosc_danych": "True", "bledy": "None"}])
        self.assertEqual(summary["problem_details"], [])


if __name__ == "__main__":
    unittest.main()
