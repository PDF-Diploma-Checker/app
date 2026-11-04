import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.redaction.redaction_validator import RedactionValidator, _comparable_title


def _line(text):
    return NS(spans=[NS(text=text)])


def _page(number, *lines, images=(), tables=()):
    return NS(number=number, text_blocks=[NS(lines=[_line(t) for t in lines])], images=list(images), tables=list(tables))


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


if __name__ == "__main__":
    unittest.main()
