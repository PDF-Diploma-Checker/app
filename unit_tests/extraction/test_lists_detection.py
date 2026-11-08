'''Lists of figures and tables: a thesis that has them must not be told that it does not.'''
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

import fitz

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.main_extractor import extractPDF
from analysis.modules.redaction.redaction_validator import RedactionValidator


def _entry(number, title, page):
    return f"{number} {title} " + ". " * 20 + str(page)


def _extract(*pages):
    """Extracts a PDF made of pages given as lists of lines, the first line being at the top of the page."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=595, height=842)
        for i, text in enumerate(lines):
            page.insert_text((70, 90 + i * 22), text, fontsize=16 if i == 0 else 11)
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            doc.save("thesis.pdf")
            return extractPDF("thesis.pdf")
        finally:
            os.chdir(cwd)


TITLE = ["Praca dyplomowa"]
TOC = ["Spis tresci", "1 Wstep " + ". " * 20 + "3", "2 Wyniki " + ". " * 20 + "4"]


class ListsFoundTest(unittest.TestCase):
    def test_title_with_an_accent_apart_from_its_letter(self):
        document = _extract(TITLE, TOC, ["SPIS RYSUNK ´ OW", _entry("2.1", "Schemat systemu", 3), _entry("2.2", "Wyniki badania", 4)])
        self.assertEqual([e.title for e in document.tof.entries], ["Schemat systemu", "Wyniki badania"])

    def test_list_with_one_entry(self):
        document = _extract(TITLE, TOC, ["Spis tabel", _entry("3.1", "Zestawienie cech", 4)])
        self.assertEqual([e.title for e in document.tot.entries], ["Zestawienie cech"])

    def test_list_with_only_its_title(self):
        document = _extract(TITLE, TOC, ["Spis tabel"])
        self.assertIsNotNone(document.tot)
        self.assertEqual(document.tot.entries, [])

    def test_mention_in_the_text_is_not_a_list(self):
        document = _extract(TITLE, TOC, ["Wstep", "Wyniki przedstawiono dalej, a spis tabel znajduje sie na koncu pracy."])
        self.assertIsNone(document.tot)

    def test_list_right_after_the_contents_is_not_part_of_them(self):
        entries = [_entry(f"2.{i}", f"Rysunek numer {i}", 3) for i in range(1, 7)]
        document = _extract(TITLE, TOC, ["Spis rysunkow", *entries])
        self.assertEqual(len(document.toc.entries), 2)
        self.assertEqual(len(document.tof.entries), 6)


class MissingListReportedTest(unittest.TestCase):
    def _errors(self, images=(), tables=()):
        page = NS(number=3, images=list(images), tables=list(tables))
        errors = []
        validator = NS(document_data=NS(pages=[page], tof=None, tot=None), errors=errors, language="pl", module="redaction",
                       _get_next_id=lambda: len(errors))
        RedactionValidator.check_tof(validator)
        RedactionValidator.check_tot(validator)
        return [e.category for e in errors]

    def test_nothing_to_list(self):
        self.assertEqual(self._errors(images=[NS(description="")]), [])

    def test_figure_and_table_without_a_list(self):
        self.assertEqual(self._errors([NS(description="Rysunek 1. Schemat.")], [NS(description="Tabela 1. Wyniki.")]),
                         ["lack_of_TOF", "lack_of_TOT"])


if __name__ == "__main__":
    unittest.main()
