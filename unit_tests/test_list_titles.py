import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.redaction.redaction_validator import RedactionValidator, _comparable_title


def _line(text):
    return NS(spans=[NS(text=text)])


def _page(number, *lines, images=(), tables=(), footer=None):
    blocks = [NS(lines=[_line(t) for t in lines], block_type="text")]
    if footer is not None:
        blocks.append(NS(lines=[_line(str(footer))], block_type="footer", bbox=(290, 800, 300, 810)))
    return NS(number=number, text_blocks=blocks, images=list(images), tables=list(tables), width=595, height=842)


def _entry(title, page):
    return NS(title=title, page=page, src_page=1, bbox=(0, 0, 0, 0))


def _validator(pages, **lists):
    errors = []
    document = NS(pages=pages, toc=None, tof=None, tot=None, **{})
    for name, entries in lists.items():
        setattr(document, name, NS(entries=entries))
    return NS(document_data=document, errors=errors, language="pl", module="redaction", _get_next_id=lambda: len(errors)), errors


class ComparableTitleTest(unittest.TestCase):
    def test_entry_and_heading_become_the_same(self):
        self.assertEqual(_comparable_title("1. Wstęp"), "1wstęp")
        self.assertEqual(_comparable_title("2.1. Metody  słownikowe."), "2.1metodysłownikowe")
        self.assertEqual(_comparable_title("Cel - zakres"), "celzakres")

    def test_dots_inside_a_number_stay(self):
        self.assertEqual(_comparable_title("2.1 Metody"), "2.1metody")

    def test_space_next_to_a_bracket_does_not_count(self):
        self.assertEqual(_comparable_title("Diagramy (ang. backup diagrams )"), _comparable_title("Diagramy (ang backup diagrams)"))


class ListTitlesTest(unittest.TestCase):
    def test_heading_with_a_dot_after_its_number_is_found(self):
        # the extractor gives "1 Wstęp" for the entry "1. Wstęp"
        validator, errors = _validator([_page(3, "1. Wstęp"), _page(4, "2.1. Metody słownikowe")],
                                       toc=[_entry("1 Wstęp", 3), _entry("2.1 Metody słownikowe", 4)])
        RedactionValidator.check_toc(validator)
        self.assertEqual(errors, [])

    def test_heading_on_another_page_is_still_reported(self):
        validator, errors = _validator([_page(3, "1. Wstęp"), _page(4, "Coś innego")], toc=[_entry("1 Wstęp", 4)])
        RedactionValidator.check_toc(validator)
        self.assertEqual([e.category for e in errors], ["TOC_mismatch"])

    def test_figure_and_table_titles_with_a_dash(self):
        image = NS(description="Rysunek 1. Schemat - widok ogólny.")
        table = NS(description="Tabela 1. Wyniki - zestawienie.")
        validator, errors = _validator([_page(5, images=[image], tables=[table])],
                                       tof=[_entry("Schemat widok ogólny", 5)], tot=[_entry("Wyniki zestawienie", 5)])
        RedactionValidator.check_tof(validator)
        RedactionValidator.check_tot(validator)
        self.assertEqual(errors, [])


class PrintedPageNumbersTest(unittest.TestCase):
    """Page 0 is the title page, and theses leave different front pages out of the numbering."""

    def _shifted_document(self, shift, **lists):
        return _validator([_page(n, f"Rozdział {n}", footer=n + shift) for n in range(1, 8)], **lists)

    def test_lists_use_the_numbers_printed_on_the_pages(self):
        for shift in (0, 1, 2, 3):
            validator, errors = self._shifted_document(shift, toc=[_entry("Rozdział 4", 4 + shift)])
            RedactionValidator.check_toc(validator)
            self.assertEqual(errors, [], shift)

    def test_wrong_page_in_a_list_is_still_reported(self):
        validator, errors = self._shifted_document(2, toc=[_entry("Rozdział 4", 5)])
        RedactionValidator.check_toc(validator)
        self.assertEqual([e.category for e in errors], ["TOC_mismatch"])

    def test_numbering_with_or_without_the_title_page_is_not_an_error(self):
        for shift in (0, 1):
            validator, errors = self._shifted_document(shift)
            RedactionValidator.check_footers(validator)
            self.assertEqual(errors, [], shift)

    def test_wrong_start_is_reported_once_and_the_lists_stay_checkable(self):
        validator, errors = self._shifted_document(3)
        RedactionValidator.check_footers(validator)
        self.assertEqual([e.category for e in errors], ["Wrong_page_numbering_start"])
        self.assertIn("Wykryto: 4, oczekiwano: 2", errors[0].comments)

    def test_one_page_out_of_line_is_reported_with_the_expected_number(self):
        validator, errors = _validator([_page(n, f"Rozdział {n}", footer=99 if n == 4 else n + 1) for n in range(1, 8)])
        RedactionValidator.check_footers(validator)
        self.assertEqual([e.category for e in errors], ["Wrong_page_number", "numeration_invalid"])
        self.assertIn("Wykryto: 99, oczekiwano: 5", errors[0].comments)

    def test_figures_and_tables_on_a_shifted_document(self):
        image = NS(description="Rysunek 1. Schemat systemu.")
        table = NS(description="Tabela 1. Wyniki badań.")
        pages = [_page(1, footer=3), _page(2, footer=4, images=[image], tables=[table]), _page(3, footer=5)]
        validator, errors = _validator(pages, tof=[_entry("Schemat systemu", 4)], tot=[_entry("Wyniki badań", 4)])
        RedactionValidator.check_tof(validator)
        RedactionValidator.check_tot(validator)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
