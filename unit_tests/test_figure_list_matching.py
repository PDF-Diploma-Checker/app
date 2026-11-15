"""CPU regressions for captions independent of image/table detection."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from types import SimpleNamespace as NS
from unit_tests.test_list_titles import _entry, _page, _validator
from analysis.modules.redaction.redaction_validator import RedactionValidator
from analysis.extraction.raw_extraction.front_and_back_matter import (
    TableOfFiguresExtractor, TableOfTablesExtractor,
)


def entry(title, page, number='A.1'):
    result = _entry(title, page)
    result.number = number
    return result


class CaptionMatchingTest(unittest.TestCase):
    def check_list(self, kind, pages, entries):
        validator, errors = _validator(pages, **{kind: entries})
        getattr(RedactionValidator, 'check_' + kind)(validator)
        return errors

    def test_unassociated_caption_and_split_words(self):
        for kind, label in [('tof', 'Rysunek'), ('tot', 'Tabela')]:
            with self.subTest(kind=kind):
                pages = [_page(4, label + ' A.1. Wyniki. Prze-', 'jazd robota.', footer=6)]
                self.assertEqual(self.check_list(kind, pages, [entry('Wyniki Przejazd robota', 6)]), [])

    def test_caption_continues_in_another_block(self):
        page = _page(4, 'Tabela A.1. Wyniki testu:')
        page.text_blocks += _page(4, 'sukces na przeszkodach.').text_blocks
        self.assertEqual(self.check_list('tot', [page], [entry('Wyniki testu: sukces na przeszkodach', 4)]), [])

    def test_wrong_page_number_title_and_kind_still_fail(self):
        page = _page(4, 'Rysunek A.1. Wyniki testu.')
        for kind, item in [('tof', entry('Wyniki testu', 5)),
                           ('tof', entry('Wyniki testu', 4, 'A.2')),
                           ('tof', entry('Inny tytuł', 4)),
                           ('tot', entry('Wyniki testu', 4))]:
            with self.subTest(kind=kind, item=item):
                self.assertEqual(len(self.check_list(kind, [page], [item])), 1)

    def test_prose_reference_is_not_a_caption(self):
        self.assertEqual(len(self.check_list('tof', [_page(4, 'Porównaj Rysunek A.1. Wyniki testu.')],
                                            [entry('Wyniki testu', 4)])), 1)

    def test_next_caption_cannot_complete_title(self):
        self.assertEqual(len(self.check_list('tof', [_page(4, 'Rysunek A.1. Wyniki', 'Rysunek A.2. testu')],
                                            [entry('Wyniki testu', 4)])), 1)

    def test_list_page_cannot_match_itself(self):
        v, errors = _validator([_page(4, 'Rysunek A.1. Wyniki')], tof=[entry('Wyniki', 4)])
        v.document_data.tof.page_nums = [4]
        RedactionValidator.check_tof(v)
        self.assertEqual(len(errors), 1)

    def test_restarted_numbering_and_missing_footer_fallback(self):
        pages = [_page(4, footer=6), _page(5, 'Rysunek A.1. Wyniki', footer=1),
                 _page(6, 'Tabela A.1. Dane')]
        self.assertEqual(self.check_list('tof', pages, [entry('Wyniki', 1)]), [])
        # A majority offset of +2 is used only on pages without a footer.
        pages.insert(0, _page(3, footer=5))
        self.assertEqual(self.check_list('tot', pages, [entry('Dane', 8)]), [])


class ListExtractionTest(unittest.TestCase):
    def test_wrapped_acronym_is_not_an_entry_and_appendix_numbers_survive(self):
        for cls, heading in [(TableOfFiguresExtractor, 'Spis rysunków'),
                             (TableOfTablesExtractor, 'Spis tabel')]:
            with self.subTest(cls=cls):
                page = _page(1, heading, '6.8. Polityka uczona algorytmem',
                             'PPO na 32 środowiskach . . . 70', 'A.1. Parametry . . . 95')
                for i, line in enumerate(page.text_blocks[0].lines):
                    line.bbox = (50, 40 + i * 20, 500, 55 + i * 20)
                result = cls().extract([page], [])
                self.assertEqual([(e.number, e.title, e.page) for e in result.entries],
                                 [('6.8', 'Polityka uczona algorytmem PPO na 32 środowiskach', 70),
                                  ('A.1', 'Parametry', 95)])


if __name__ == '__main__':
    unittest.main()
