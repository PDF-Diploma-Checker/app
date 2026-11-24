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

    def test_math_accent_after_a_symbol_in_the_same_math_font_goes_to_the_next_symbol(self):
        # "𝜖) ̂𝐴" in a thesis whose text and formulas are both set in one math font: the hat is not the previous word's
        words, full_text = extract(("𝜖)", MATH_FONT), (HAT, MATH_FONT), ("𝐴", MATH_FONT))
        self.assertEqual([unicodedata.normalize("NFD", w.text) for w in words], ["𝜖)", "𝐴" + HAT])
        self.assert_offsets(words, full_text)

    def test_mark_without_following_word_falls_back_to_previous_word(self):
        words, full_text = extract(("Przez", TEXT_FONT), (HAT, MATH_FONT))
        self.assertEqual(unicodedata.normalize("NFD", words[0].text), "Przez" + HAT)
        self.assert_offsets(words, full_text)

    def test_polish_letters_without_marks_not_changed(self):
        words, full_text = extract(("Zażółć", TEXT_FONT), ("gęślą", TEXT_FONT), ("jaźń", TEXT_FONT))
        self.assertEqual([w.text for w in words], ["Zażółć", "gęślą", "jaźń"])
        self.assert_offsets(words, full_text)


class TestAccentAfterAWord(unittest.TestCase):
    '''PyMuPDF puts an accent drawn right after a word into that word ("gdzie" + hat of \\hat{\\mathbb{E}} = "gdziê").'''

    @staticmethod
    def block(*spans):
        return {"lines": [{"spans": [{"text": text, "font": font, "bbox": bbox} for text, font, bbox in spans]}]}

    def test_the_accent_moves_to_the_symbol_of_its_math_span(self):
        from analysis.extraction.raw_extraction.text_extractor import move_math_accents_to_symbols
        raw = self.block(("gdzie", "ArialMT", (85.0, 652.9, 108.8, 662.8)),
                         (HAT + " \U0001D53C", MATH_FONT, (108.8, 652.5, 117.8, 662.5)),
                         ("oznacza", "ArialMT", (124.2, 652.9, 161.3, 662.8)))
        words = [(85.0, 652.5, 108.8, 662.8, "gdzie" + HAT, 0, 0, 0),
                 (111.7, 652.5, 117.8, 662.5, "\U0001D53C", 0, 0, 1),
                 (124.2, 652.9, 161.3, 662.8, "oznacza", 0, 0, 2)]
        moved = move_math_accents_to_symbols(words, raw)
        self.assertEqual([w[4] for w in moved], ["gdzie", "\U0001D53C" + HAT, "oznacza"])

    def test_an_accent_of_a_formula_elsewhere_is_dropped_from_the_word(self):
        from analysis.extraction.raw_extraction.text_extractor import move_math_accents_to_symbols
        raw = self.block(("sumę ważoną wykładniczo:", "ArialMT", (85.0, 361.0, 266.0, 371.0)))
        words = [(210.0, 360.0, 266.0, 371.0, "wykładniczo:" + HAT, 0, 0, 0)]
        self.assertEqual(move_math_accents_to_symbols(words, raw)[0][4], "wykładniczo:")

    def test_a_mark_in_the_text_font_stays(self):
        from analysis.extraction.raw_extraction.text_extractor import move_math_accents_to_symbols
        raw = self.block(("gdzie" + HAT, "ArialMT", (85.0, 652.9, 108.8, 662.8)),
                         ("x", MATH_FONT, (111.0, 652.5, 117.8, 662.5)))
        words = [(85.0, 652.5, 108.8, 662.8, "gdzie" + HAT, 0, 0, 0), (111.0, 652.5, 117.8, 662.5, "x", 0, 0, 1)]
        self.assertEqual(move_math_accents_to_symbols(words, raw), words)


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
