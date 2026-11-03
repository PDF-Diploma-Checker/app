'''
Tests for extraction of combining marks and math accents (converter_linguistics_clean.py, _extract_words_with_spacing).

LuaTeX and XeTeX (unicode-math) draw a math accent as a separate zero-width span in the math font BEFORE the symbol
it decorates: "Przez" (text font), hat (math font), "x" (bold). The extraction used to glue every mark-only span
to the preceding word, which made "Przeẑ" and "Oszacowaniê" and reported them as typos.

Checks that:
- a mark in a different font than the preceding word moves to the next word ("Przez x̂"),
- a mark in the same font as the preceding word is still glued to it (accents of letters in the text font),
- a mark already carried by the preceding word is not duplicated,
- a mark with no word after it in the line falls back to the preceding word,
- word offsets (start_char/end_char) match the text in every case,
- TestGeneratedPdfs verifies full extraction on test PDFs built by different LaTeX compilers
  (pdflatex, xelatex, lualatex). tp_* - the accent must land on the symbol, fp_* - Polish letters stay intact.

Run:
    uv run python -m unittest unit_tests/extraction/math_accents/test_math_accents.py -v
'''
import sys
import unicodedata
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from analysis.extraction.raw_extraction.bare_struct import TextLine, TextSpan
from unit_tests.utils_generate_pdfs import LATEX_COMPILERS
from unit_tests.utils_test import pdf_to_blocks

PDF_DIR = Path(__file__).resolve().parent

HAT = "̂"
TEXT_FONT = "LatinModernRoman-Regular"
MATH_FONT = "LatinModernMath-Regular"
BOLD_FONT = "Arial-BoldMT"


def make_line(*spans):
    '''Builds a line from (text, font) pairs placed one after another (a mark has zero width).'''
    x = 100.0
    result = []
    for i, (text, font) in enumerate(spans):
        width = 0.0 if text.strip() and all(unicodedata.category(c).startswith("M") for c in text) else 6.0 * len(text)
        result.append(TextSpan(
            span_id=i, text=text, font=font, size=12.0, color=0,
            bold=False, italic=False, bbox=(x, 100.0, x + width, 112.0)
        ))
        x += width
    return TextLine(spans=result, bbox=(100.0, 100.0, x, 112.0), baseline=0)


def extract(*spans):
    '''Runs the word extraction of the converter on one line, returns (words, full_text).'''
    mapper = PDFMapper()
    mapper.curr_line = 0
    full_text, words, _ = mapper._extract_words_with_spacing(make_line(*spans), "", [], 0, 0, 500.0)
    return words, full_text


class TestCombiningMarks(unittest.TestCase):

    def assert_offsets(self, words, full_text):
        for w in words:
            self.assertEqual(full_text[w.start_char:w.end_char], w.text)

    def test_mark_in_other_font_goes_to_next_word(self):
        words, full_text = extract(("Przez", TEXT_FONT), (HAT, MATH_FONT), ("x", BOLD_FONT))
        self.assertEqual([w.text for w in words], ["Przez", "x̂"])
        self.assertEqual(full_text.strip(), "Przez x̂")
        self.assert_offsets(words, full_text)

    def test_mark_in_other_font_polish_word_not_changed(self):
        words, full_text = extract(("Oszacowanie", TEXT_FONT), (HAT, MATH_FONT), ("x", BOLD_FONT), ("𝑘|𝑘", MATH_FONT))
        self.assertEqual(words[0].text, "Oszacowanie")
        self.assertEqual(words[1].text, "x̂")
        self.assert_offsets(words, full_text)

    def test_mark_in_same_font_is_glued_to_previous_word(self):
        words, full_text = extract(("Gurri", TEXT_FONT), ("́", TEXT_FONT), ("a", TEXT_FONT))
        self.assertEqual(words[0].text, "Gurrí".replace("í", "í"))
        self.assert_offsets(words, full_text)

    def test_mark_already_in_previous_word_is_moved_not_duplicated(self):
        # PyMuPDF may already put the mark in the text of the preceding span ("H" + hat)
        words, full_text = extract(("H" + HAT, BOLD_FONT), (HAT, MATH_FONT), ("x", BOLD_FONT))
        self.assertEqual([w.text for w in words], ["H", "x̂"])
        self.assert_offsets(words, full_text)

    def test_mark_already_in_previous_word_same_font_not_duplicated(self):
        words, full_text = extract(("l" + HAT, MATH_FONT), (HAT, MATH_FONT))
        self.assertEqual(unicodedata.normalize("NFD", words[0].text), "l" + HAT)
        self.assert_offsets(words, full_text)

    def test_mark_without_following_word_falls_back_to_previous_word(self):
        words, full_text = extract(("Przez", TEXT_FONT), (HAT, MATH_FONT))
        self.assertEqual(unicodedata.normalize("NFD", words[0].text), "Przez" + HAT)
        self.assert_offsets(words, full_text)

    def test_polish_letters_without_marks_not_changed(self):
        words, full_text = extract(("Zażółć", TEXT_FONT), ("gęślą", TEXT_FONT), ("jaźń", TEXT_FONT))
        self.assertEqual([w.text for w in words], ["Zażółć", "gęślą", "jaźń"])
        self.assert_offsets(words, full_text)


class TestGeneratedPdfs(unittest.TestCase):
    '''Full extraction of PDFs built by different compilers.'''

    @staticmethod
    def contents(pdf_path):
        raw_blocks, _ = pdf_to_blocks(pdf_path)
        return " ".join(b.content for b in raw_blocks.logical_blocks if getattr(b, "content", None))

    def test_tp_accent_lands_on_symbol_not_on_word(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                text = self.contents(PDF_DIR / f"tp_math_accents_{compiler}.pdf")
                for word in ("Przez", "Oszacowanie", "Prognozę", "oznaczono", "pozwala"):
                    self.assertIn(word, text.split())
                for broken in ("Przeẑ", "Oszacowaniê", "Prognozę̂"):
                    self.assertNotIn(broken, text)
                # unicode-math compilers write the accent as U+0302: it must follow a symbol, never a letter of a word
                # (Polish letters do not use a circumflex)
                for word in text.split():
                    if word.isalpha():
                        self.assertNotIn(HAT, unicodedata.normalize("NFD", word), word)

    def test_fp_polish_letters_stay_intact(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                text = self.contents(PDF_DIR / f"fp_accents_in_text_{compiler}.pdf")
                self.assertIn("Zażółć gęślą jaźń, a następnie pchnąć w tę łódź jeża lub ośm skrzyń fig oraz źdźbło trawy.", text)
                self.assertIn("ĄĆĘŁŃÓŚŹŻ", text)
                self.assertIn("ąćęłńóśźż", text)
                self.assertIn("Przez", text.split())
                self.assertIn("Oszacowanie.", text.split())


if __name__ == "__main__":
    unittest.main()
