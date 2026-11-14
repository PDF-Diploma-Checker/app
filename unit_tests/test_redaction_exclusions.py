"""Typographic errors are not reported in lists (TOC/TOF/TOT), images and tables (redaction_info.md)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.redaction.redaction_validator import RedactionValidator, TYPOGRAPHY_CATEGORIES

MAIN = "TimesNewRomanPSMT"
BOX = NS(bbox=(50.0, 100.0, 500.0, 400.0))


def _word(text, page=5):
    return NS(text=text, font=MAIN, size=12.0, bbox=(100.0, 200.0, 140.0, 212.0), page_number=page, italic=False)


def _validator(images=(), tables=(), toc_pages=()):
    page = NS(number=5, width=595.0, images=list(images), tables=list(tables), text_blocks=[])
    document = NS(
        pages=[page],
        toc=NS(page_nums=list(toc_pages)) if toc_pages else None,
        tof=None,
        tot=None,
        get_most_common_font=lambda: MAIN,
        get_most_common_font_size=lambda: 12.0,
    )
    return RedactionValidator(document_data=document, document_data_linguistics=None)


def _errors(validator):
    """One error of every typographic check, built by the checks themselves, so their real category names are used."""
    block = NS(words=[_word("Tekst", page=4), _word("akapitu"), _word("koniec.")])
    return [
        validator._handle_widow(block, 1),
        validator._handle_bekart(block, 1),
        validator._handle_szewc(NS(words=[_word("Pierwszy"), _word("dalej", page=6)]), 1),
        NS(category="orphan", page_number=5, bounding_box=(100.0, 200.0, 110.0, 212.0)),
    ]


class TypographyCategoriesTest(unittest.TestCase):
    def test_every_typographic_check_is_on_the_list(self):
        for error in _errors(_validator()):
            self.assertIn(error.category, TYPOGRAPHY_CATEGORIES)


class ExclusionAreasTest(unittest.TestCase):
    def _left_after(self, remove, **areas):
        validator = _validator(**areas)
        validator.errors = _errors(validator)
        getattr(validator, remove)()
        return [e.category for e in validator.errors]

    def test_removed_from_table_of_contents_pages(self):
        self.assertEqual(self._left_after("remove_errors_from_toc_tof_tot", toc_pages=[5]), [])

    def test_removed_from_images(self):
        self.assertEqual(self._left_after("remove_errors_from_images", images=[BOX]), [])

    def test_removed_from_tables(self):
        self.assertEqual(self._left_after("remove_errors_from_tables", tables=[BOX]), [])

    def test_kept_outside_the_areas(self):
        left = self._left_after("remove_errors_from_images")
        self.assertEqual(sorted(left), ["bastard", "orphan", "shoemaker", "widow"])


if __name__ == "__main__":
    unittest.main()
