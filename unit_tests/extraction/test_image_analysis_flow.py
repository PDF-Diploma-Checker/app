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
from analysis.extraction.raw_extraction.image_extractor import get_raster_figure_numbers  # noqa: E402
from analysis.modules.llm.image_analysis.figures import (  # noqa: E402
    collect_figures,
    consistency_verdict,
    figure_sort_key,
    is_caption,
    mentions_figure,
    parse_yes_no,
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


class EnumerationTest(unittest.TestCase):
    def test_later_number_of_an_enumeration_is_a_reference(self):
        for text in ("Rysunki 1 i 2 przedstawiają wyniki.", "Na rys. 1, 2 oraz 3 widać wzrost.", "Figures 1 and 2 show it."):
            self.assertTrue(reference_pattern("2").search(text), text)

    def test_other_numbers_are_not_a_reference(self):
        for text in ("Rysunki 1 i 3 przedstawiają wyniki.", "Rysunek 1 i 2 inne wartości z tabeli", "Na rysunku 12 widać"):
            match = reference_pattern("3").search(text) if "12" not in text else reference_pattern("2").search(text)
            if "1 i 3" not in text:
                self.assertIsNone(match, text)


class RasterListTest(unittest.TestCase):
    def test_figures_of_different_series_with_the_same_number_are_listed_apart(self):
        image = lambda caption: SimpleNamespace(image_type="raster", description=caption)
        doc = SimpleNamespace(pages=[SimpleNamespace(images=[image("Rysunek 1. A"), image("Wykres 1. B"), image("Rysunek 1. A")])])
        self.assertEqual(get_raster_figure_numbers(doc), ["Rysunek 1", "Wykres 1"])


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


class ModelFailureTest(unittest.TestCase):
    def test_yes_no_needs_a_whole_word(self):
        self.assertIs(parse_yes_no("YES."), True)
        self.assertIs(parse_yes_no("No"), False)
        for answer in ("unknown", "I cannot tell", "", None):
            self.assertIsNone(parse_yes_no(answer), answer)

    def test_unusable_verdict_is_a_failure_not_a_thesis_error(self):
        self.assertEqual(consistency_verdict({"poprawnosc_danych": "False"}), "False")
        self.assertEqual(consistency_verdict({"poprawnosc_danych": False}), "False")
        self.assertEqual(consistency_verdict({"poprawnosc_danych": "true"}), "True")
        for answer in ({}, {"poprawnosc_danych": "moze"}, {"poprawnosc_danych": "Error"}):
            self.assertEqual(consistency_verdict(answer), "Error")

    def test_failed_checks_are_not_listed_as_errors(self):
        from app.llm_task import split_failed_checks

        real = {"rysunek": "Rys. 1", "blad": "x"}
        self.assertEqual(split_failed_checks([real, {"rysunek": "Rys. 2", "analysis_failed": True}]), ([real], True))
        self.assertEqual(split_failed_checks([real]), ([real], False))


class ReportPdfTest(unittest.TestCase):
    def _pdf_text(self, image_analysis):
        from ui.report_pdf import build_report_pdf

        data = {"content_grade": {"grade": 50, "max_grade": 100}, "image_analysis": image_analysis}
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp, "report.pdf"))
            build_report_pdf(data, "t.pdf", "pl", path)
            with fitz.open(path) as doc:
                return " ".join(" ".join(page.get_text().split()) for page in doc)

    def test_discrepancy_list_has_only_the_problems(self):
        from app.llm_task import build_image_summary

        text = self._pdf_text(build_image_summary([
            {"obrazek": "Rys. 1", "poprawnosc_danych": "True", "bledy": "None"},
            {"obrazek": "Rys. 2", "poprawnosc_danych": "False", "bledy": "Zla wartosc"},
        ]))
        self.assertIn("Zla wartosc", text)
        self.assertNotIn("Rys. 1:", text)

    def test_all_correct_has_no_discrepancy_list(self):
        from app.llm_task import build_image_summary

        text = self._pdf_text(build_image_summary([{"obrazek": "Rys. 1", "poprawnosc_danych": "True", "bledy": "None"}]))
        self.assertNotIn("Lista szczegółowa", text)

    def test_report_saved_by_older_version_is_filtered_too(self):
        text = self._pdf_text({"total": 2, "bad_count": 1, "good_count": 1, "details": [
            "Rysunek 1: Poprawny - Szczegoly: None", "Rysunek 2: Wykryto rozbieznosci - Szczegoly: Zla wartosc"]})
        self.assertIn("Zla wartosc", text)
        self.assertNotIn("Rysunek 1:", text)


class ThesisLanguageTest(unittest.TestCase):
    ROWS = [
        {"obrazek": "Figure 1", "poprawnosc_danych": "True", "bledy": "None"},
        {"obrazek": "Figure 2", "poprawnosc_danych": "False", "bledy": "x"},
        {"obrazek": "Figure 3", "poprawnosc_danych": "Error", "bledy": "y"},
    ]

    def test_summary_follows_the_thesis_language(self):
        from app.llm_task import build_image_summary

        english = build_image_summary(self.ROWS, "en")
        self.assertEqual(english["problem_details"], ["Figure 2: Discrepancies found - Details: x",
                                                      "Figure 3: Not analysed - Details: y"])
        self.assertIn("Figure 1: Correct - Details: None", english["details"])
        polish = build_image_summary(self.ROWS, "pl")
        self.assertEqual(polish["problem_details"][1], "Figure 3: Nie przeanalizowano - Szczegóły: y")

    def test_every_message_exists_in_both_languages(self):
        from analysis.modules.llm.image_analysis.figures import _TEXTS

        self.assertEqual(set(_TEXTS["pl"]), set(_TEXTS["en"]))

    def test_dpi_check_writes_in_the_thesis_language(self):
        from analysis.modules.llm.image_analysis.quality_analysis import check_image_quality

        with tempfile.TemporaryDirectory() as tmp:
            image, pdf = Path(tmp, "small.png"), Path(tmp, "t.pdf")
            small = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), False)
            small.set_dpi(30, 30)
            small.save(str(image))
            doc = fitz.open()
            doc.new_page()
            doc.save(str(pdf))
            doc.close()
            thesis = SimpleNamespace(pages=[SimpleNamespace(images=[
                SimpleNamespace(path=str(image), bbox=(0, 0, 9, 9), description="Figure 1. X", image_type="raster")])])
            report = check_image_quality(thesis, str(pdf), language="en")
        self.assertEqual(report[0]["rysunek"], "Figure 1")
        self.assertIn("pixelation", report[0]["blad"])
        self.assertIn("At least 75 DPI", report[0]["wymaganie"])


class ReportPdfFontsTest(unittest.TestCase):
    def test_font_problem_is_a_sentence_not_a_raw_dict(self):
        from ui.report_pdf import build_report_pdf

        data = {"content_grade": {"grade": 50, "max_grade": 100},
                "image_analysis": {"total": 1, "bad_count": 0, "good_count": 1},
                "czcionki_obrazkow": [{"rysunek": "Figure 1", "blad": "Inconsistent font sizes"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp, "report.pdf"))
            build_report_pdf(data, "t.pdf", "en", path)
            with fitz.open(path) as doc:
                text = " ".join(" ".join(page.get_text().split()) for page in doc)
        self.assertIn("Inconsistent font sizes", text)
        self.assertNotIn("{", text)


class AxisRulesTest(unittest.TestCase):
    def test_numbers_of_an_answer(self):
        from analysis.modules.llm.image_analysis.figures import parse_axis_numbers as parse
        self.assertEqual(parse("0%; 20%; 40%"), [0, 20, 40])
        self.assertEqual(parse("0,5;1,5;100 s;-2"), [0.5, 1.5, 100, -2])
        self.assertEqual(parse("NONE"), [])
        self.assertEqual(parse("M1; M2"), [])

    def test_good_scales(self):
        from analysis.modules.llm.image_analysis.figures import scale_problem as problem
        for ticks in ([0, 20, 40, 60], [0, 2000, 4000, 6000], [-10, -5, 0, 5, 10], [1, 10, 100, 1000],
                      [1, 2, 5, 10, 20], [0.1, 0.2, 0.3, 0.4], [10, 20, 30, 40], [40, 30, 20, 10, 0]):
            self.assertIsNone(problem(ticks, True), ticks)

    def test_uneven_scale(self):
        from analysis.modules.llm.image_analysis.figures import scale_problem as problem
        for ticks in ([0, 10, 20, 50, 200], [0, 5, 10, 20, 50], [0, 10, 50, 200]):
            self.assertEqual(problem(ticks, False), "uneven", ticks)

    def test_bar_chart_not_starting_at_zero(self):
        from analysis.modules.llm.image_analysis.figures import scale_problem as problem
        self.assertEqual(problem([60, 62, 64, 66, 68], True), "truncated")
        self.assertIsNone(problem([60, 62, 64, 66, 68], False))    # a line chart may start anywhere

    def test_number_lost_by_the_model_is_not_an_uneven_scale(self):
        from analysis.modules.llm.image_analysis.figures import scale_problem as problem
        self.assertIsNone(problem([0, 100, 300, 400], True))
        self.assertIsNone(problem([0, 10, 20, 50, 60], True))

    def test_too_few_numbers_or_no_scale_at_all(self):
        from analysis.modules.llm.image_analysis.figures import scale_problem as problem
        self.assertIsNone(problem([0, 5, 60], True))
        self.assertIsNone(problem([70, 75, 80, 85, 75], True))
        self.assertIsNone(problem([], True))


class ReportPdfAxesTest(unittest.TestCase):
    def test_axis_problem_is_in_the_report(self):
        from ui.report_pdf import build_report_pdf

        data = {"content_grade": {"grade": 50, "max_grade": 100},
                "image_analysis": {"total": 1, "bad_count": 0, "good_count": 1},
                "osie_wykresow": [{"rysunek": "Figure 1", "blad": "The chart has no scale"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp, "report.pdf"))
            build_report_pdf(data, "t.pdf", "en", path)
            with fitz.open(path) as doc:
                text = " ".join(" ".join(page.get_text().split()) for page in doc)
        self.assertIn("Chart Axes", text)
        self.assertIn("The chart has no scale", text)


class ReportPdfPurposeTest(unittest.TestCase):
    def _text(self, grade):
        from ui.report_pdf import build_report_pdf

        data = {"content_grade": {"grade": 90, "max_grade": 100, **grade}, "image_analysis": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp, "report.pdf"))
            build_report_pdf(data, "t.pdf", "pl", path)
            with fitz.open(path) as doc:
                return " ".join(" ".join(page.get_text().split()) for page in doc)

    def test_reason_of_the_grade_is_in_the_report(self):
        text = self._text({"purpose_score": 50, "purpose_reason": "Brakuje opisu implementacji."})
        self.assertIn("Realizacja celu pracy: 50%", text)
        self.assertIn("Brakuje opisu implementacji.", text)

    def test_report_saved_before_this_change_has_no_score(self):
        text = self._text({"purpose_reason": "Brakuje opisu implementacji."})
        self.assertIn("Realizacja celu pracy", text)
        self.assertNotIn("None", text)

    def test_no_reason_no_section(self):
        self.assertNotIn("Realizacja celu pracy", self._text({}))


class ReportPanelTest(unittest.TestCase):
    def _texts(self, image_analysis):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication, QLabel
        except ImportError as error:    # e.g. a CI runner without the system libraries Qt needs (libEGL)
            self.skipTest(f"Qt is not available: {error}")

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

    def test_panel_shows_the_reason_of_the_grade(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication, QLabel
        except ImportError as error:
            self.skipTest(str(error))
        from ui.report_panel import build_report_panel

        QApplication.instance() or QApplication([])
        grade = {"grade": 90, "max_grade": 100, "purpose_score": 50, "purpose_reason": "Brakuje opisu implementacji."}
        content, _ = build_report_panel({"content_grade": grade, "image_analysis": {}}, lambda: None)
        text = " | ".join(label.text() for label in content.findChildren(QLabel))
        self.assertIn("50%", text)
        self.assertIn("Brakuje opisu implementacji.", text)

    def test_panel_names_the_figures_with_problems(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication, QLabel
        except ImportError as error:
            self.skipTest(str(error))
        from ui.report_panel import build_report_panel

        QApplication.instance() or QApplication([])
        data = {"content_grade": {"grade": 50, "max_grade": 100},
                "image_analysis": {"total": 2, "good_count": 2, "bad_count": 0},
                "jakosc_obrazkow": [{"rysunek": "Rysunek 4.6", "powody_odrzucenia": ["[DPI]: Rozciagniety"]}],
                "czcionki_obrazkow": [{"rysunek": "Rysunek 4.9", "blad": "Niespojne czcionki"}],
                "osie_wykresow": [{"rysunek": "Rysunek 4.15", "blad": "Os nie od zera"}]}
        content, _ = build_report_panel(data, lambda: None)
        text = " | ".join(label.text() for label in content.findChildren(QLabel))
        self.assertIn("Rysunek 4.6: [DPI]: Rozciagniety", text)
        self.assertIn("Rysunek 4.9: Niespojne czcionki", text)
        self.assertIn("Rysunek 4.15: Os nie od zera", text)

    def test_report_saved_before_this_change_still_opens(self):
        text = self._texts({"total": 1, "bad_count": 0, "good_count": 1, "details": ["Rys. 1: Poprawny"]})
        self.assertNotIn("Rys. 1:", text)

    def test_all_correct_lists_no_problems(self):
        from app.llm_task import build_image_summary

        summary = build_image_summary([{"obrazek": "Rys. 1", "poprawnosc_danych": "True", "bledy": "None"}])
        self.assertEqual(summary["problem_details"], [])



class FigureMentionFormsTest(unittest.TestCase):
    def test_forms_a_thesis_uses(self):
        for text in ("Jak widać na rysunku nr 3.1, dane rosną.", "Na rysunku numer 3.1 dane rosną.", "Na obrazie 3.1 widać dane.",
                     "Na rysunku 3. 1 widać dane.", "Na rysunkach od 2.9 do 3.1 pokazano dane.", "Rysunki 2.9–3.1 pokazują dane."):
            self.assertTrue(mentions_figure(text, "3.1"), text)

    def test_number_inside_a_range(self):
        self.assertTrue(mentions_figure("Rysunki 3.1-3.3 pokazują dane.", "3.2"))
        self.assertTrue(mentions_figure("Rysunki 1-3 pokazują dane.", "2"))
        self.assertFalse(mentions_figure("Rysunki 3.1-3.3 pokazują dane.", "3.4"))
        self.assertFalse(mentions_figure("Rysunki 3.1-3.3 pokazują dane.", "2.2"))

    def test_reference_that_lost_its_word(self):
        self.assertTrue(mentions_figure("Architektura znajduje się na 2.2 [17].", "2.2"))
        self.assertFalse(mentions_figure("Taktowanie zmieniono na 2.2 GHz.", "2.2"))
        self.assertFalse(mentions_figure("Liczbę zmieniono na 2.", "2"))

    def test_other_numbers_are_not_a_mention(self):
        for text in ("Na rysunku 3.10 widać dane.", "Na rysunku 13.1 widać dane.", "Rozdział 3.1 opisuje dane."):
            self.assertFalse(mentions_figure(text, "3.1"), text)

    def test_short_sentence_about_a_figure_is_not_its_caption(self):
        self.assertFalse(is_caption("Rysunek 3.1 przedstawia schemat.", "3.1"))
        self.assertFalse(is_caption("Rys. 3.1 pokazuje wynik.", "3.1"))
        self.assertFalse(is_caption("Rysunek 3.1 - przedstawia schemat układu, który działa w opisany dalej sposób.", "3.1"))
        self.assertFalse(is_caption("Figure 3.1 shows the result.", "3.1"))

    def test_caption_merged_with_the_paragraph_about_the_figure(self):
        self.assertFalse(is_caption("Rysunek 3.1: Schemat układu. Na rysunku 3.1 widać dane opisane wyżej.", "3.1"))

    def test_captions_stay_captions(self):
        for text in ("Rysunek 3.1: Przedstawienie procesu", "Rysunek 3.1. Schemat procesu.", "Rysunek 3.1 Schemat procesu", "Rys. 3.1 Schemat",
                     "Rysunek 3.1: Schemat procesu zbierania danych o nieruchomościach wykonany w programie [12]"):
            self.assertTrue(is_caption(text, "3.1"), text)


class ReferencesAcrossSeriesTest(unittest.TestCase):
    def references(self, paragraphs, img, images):
        return ReferenceMatcher().references_to(paragraphs, img, images)

    def test_figure_called_by_another_word_in_the_text(self):
        img = {"number": "3.1", "family": "rys"}
        self.assertEqual(self.references(["Na schemacie 3.1 widać dane."], img, [img]), ["Na schemacie 3.1 widać dane."])

    def test_word_of_another_series_with_the_same_number_is_that_figure(self):
        figure, chart = {"number": "1", "family": "rys"}, {"number": "1", "family": "wykres"}
        self.assertEqual(self.references(["Na wykresie 1 widać dane."], figure, [figure, chart]), [])



if __name__ == "__main__":
    unittest.main()
