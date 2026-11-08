'''
Tests for detecting missing space after abbreviations (abbreviation_space_check in dash_check.py).

Checks that:
- missing space after abbreviation (e.g. "tzw.krótkiej", "np.pierwszy") is flagged as PUNCTUATION,
- correct usage with space (e.g. "tzw. krótkiej") is not flagged,
- abbreviation ending a sentence with capitalized next word is not flagged,
- abbreviations inside quotations and URL addresses are ignored,
- TestGeneratedPdfs verifies full pipeline run (extraction -> analysis) on test PDFs
  built by different LaTeX compilers (pdflatex, xelatex, lualatex).

Run:
    uv run python -m unittest unit_tests/linguistics/abbreviation_space/test_abbreviation_space.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, WordInfo
from analysis.modules.linguistics.linguistics_types import Block_context
from analysis.modules.linguistics.dash_check import abbreviation_space_check
from unit_tests.utils_generate_pdfs import LATEX_COMPILERS
from unit_tests.utils_test import pdf_to_blocks

PDF_DIR = Path(__file__).resolve().parent


def make_words(content, page=1):
    words = []
    pos = 0
    for i, text in enumerate(content.split(" ")):
        words.append(WordInfo(
            word_index=i, text=text, start_char=pos, end_char=pos + len(text),
            font="Arial", size=10.0, bold=False, italic=False,
            bbox=[10.0 * i, 100.0, 10.0 * i + 8, 112.0], page_number=page
        ))
        pos += len(text) + 1
    return words


def make_block(content, block_id=1, language="pl"):
    p = ParagraphBlock(block_id=block_id, content=content, words=make_words(content))
    p.language = language
    return Block_context(contents=content, language=language, block=p)


class TestAbbreviationSpaceCheck(unittest.TestCase):

    def test_missing_space_detected(self):
        text = "Badano przypadek tzw.krótkiej sprzedaży aktywów na rynku."
        block = make_block(text, block_id=1, language="pl")
        matches = abbreviation_space_check([block])

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].content, "tzw.krótkiej")
        self.assertEqual(matches[0].category, "PUNCTUATION")
        self.assertEqual(matches[0].message, "Brak spacji po skrócie.")

    def test_various_abbreviations_detected(self):
        text = "Wybrano różne elementy, np.pierwszy oraz tzn.drugi przypadek."
        block = make_block(text, block_id=2, language="pl")
        matches = abbreviation_space_check([block])

        contents = [m.content for m in matches]
        self.assertIn("np.pierwszy", contents)
        self.assertIn("tzn.drugi", contents)
        self.assertEqual(len(matches), 2)

    def test_correct_space_not_detected(self):
        text = "Badano przypadek tzw. krótkiej sprzedaży aktywów na rynku."
        block = make_block(text, block_id=3, language="pl")
        matches = abbreviation_space_check([block])

        self.assertEqual(len(matches), 0)

    def test_sentence_end_not_detected(self):
        text = "Użyto metod typu tzw. Następnie przeprowadzono kolejny etap."
        block = make_block(text, block_id=4, language="pl")
        matches = abbreviation_space_check([block])

        self.assertEqual(len(matches), 0)

    def test_url_address_ignored(self):
        text = "Więcej informacji na stronie http://example.com/np.html w sekcji."
        block = make_block(text, block_id=5, language="pl")
        matches = abbreviation_space_check([block])

        self.assertEqual(len(matches), 0)

    def test_english_message(self):
        text = "An example of tzw.short sale was analyzed."
        block = make_block(text, block_id=6, language="en")
        matches = abbreviation_space_check([block])

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].message, "Missing space after an abbreviation.")


class TestGeneratedPdfs(unittest.TestCase):
    '''Full run extraction -> abbreviation_space_check on PDFs compiled with different compilers.'''

    @classmethod
    def setUpClass(cls):
        def run(pdf_path):
            _, blocks = pdf_to_blocks(pdf_path)
            return {m.content: m.message for m in abbreviation_space_check(blocks)}

        cls.run_pdf = staticmethod(run)

    def test_fp_correct_space_after_abbreviation(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                results = self.run_pdf(PDF_DIR / f"fp_correct_space_after_abbreviation_{compiler}.pdf")
                self.assertEqual(results, {})

    def test_tp_missing_space_after_abbreviation(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                results = self.run_pdf(PDF_DIR / f"tp_missing_space_after_abbreviation_{compiler}.pdf")
                self.assertIn("tzw.krótkiej", results)
                self.assertIn("np.pierwszy", results)
                self.assertIn("tzn.drugi", results)
                self.assertIn("itp.kolejne", results)


if __name__ == "__main__":
    unittest.main()
