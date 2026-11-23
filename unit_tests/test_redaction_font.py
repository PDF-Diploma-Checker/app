"""Typographic errors (orphan, widow, bastard, shoemaker) are not reported in text set in a font other than the main one."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.redaction.redaction_validator import RedactionValidator, _font_family

MAIN = "TimesNewRomanPSMT"


def _word(text, font=MAIN, size=12.0, x=100.0):
    return NS(text=text, font=font, size=size, bbox=(x, 700.0, x + 40.0, 712.0), page_number=5, italic=False)


def _validator(pages=()):
    document = NS(
        pages=list(pages),
        get_most_common_font=lambda: MAIN,
        get_most_common_font_size=lambda: 12.0,
        is_rect_intersecting=lambda rect, page: [],
    )
    return RedactionValidator(document_data=document, document_data_linguistics=None)


def _block(*last_words):
    return NS(words=[_word("Tekst"), _word("akapitu")] + list(last_words))


def _span(text, font=MAIN, size=12.0, x=100.0):
    return NS(text=text, font=font, size=size, italic=False, bbox=(x, 700.0, x + 30.0, 712.0))


def _page_with_line(*spans):
    return NS(number=5, width=595.0, text_blocks=[NS(block_type="text", lines=[NS(spans=list(spans))])])


class FontFamilyTest(unittest.TestCase):
    def test_bold_and_italic_are_the_main_family(self):
        self.assertEqual(_font_family("TimesNewRomanPS-BoldMT"), _font_family(MAIN))
        self.assertEqual(_font_family("ABCDEF+TimesNewRomanPS-ItalicMT"), _font_family(MAIN))
        self.assertNotEqual(_font_family("ArialMT"), _font_family(MAIN))


class FontFilterTest(unittest.TestCase):
    def test_widow_in_the_main_font_is_reported(self):
        error = _validator()._handle_widow(_block(_word("trening.")), 1)
        self.assertEqual(error.category, "widow")

    def test_italic_book_title_counts_as_the_main_font(self):
        block = _block(_word("Countries.", font="TimesNewRomanPS-ItalicMT"))
        self.assertIsNotNone(_validator()._handle_widow(block, 1))

    def test_widow_in_code_is_not_reported(self):
        block = _block(_word("...", font="t1xtt", size=9.96))
        self.assertIsNone(_validator()._handle_widow(block, 1))

    def test_lone_listing_line_number_is_not_reported(self):
        block = _block(_word("2", size=4.98))
        self.assertIsNone(_validator()._handle_widow(block, 1))

    def test_widow_in_another_family_is_not_reported(self):
        block = _block(_word("z", font="ArialMT"), _word("promotorem.", font="ArialMT"))
        self.assertIsNone(_validator()._handle_widow(block, 2))

    def test_shoemaker_in_code_is_not_reported(self):
        block = NS(words=[_word('temp.wav"):', font="t1xtt"), _word("dalej")])
        self.assertIsNone(_validator()._handle_szewc(block, 1))

    def test_orphan_in_another_family_is_not_reported(self):
        validator = _validator([_page_with_line(_span("tekst", font="ArialMT"), _span("o", font="ArialMT", x=140.0))])
        self.assertEqual(validator.check_orphans(), [])


if __name__ == "__main__":
    unittest.main()
