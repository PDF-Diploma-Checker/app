'''
Tests for the check that foreign language definitions are written in italic (first_definition.check_italic_def).

Run (from the repository root):
    .venv/Scripts/python.exe -m unittest discover -s unit_tests -t . -v

- check_italic_def - a match (STYLE) is returned when any word of the definition is not italic,
- check_first_definition - definitions in "(ang. ...)" are found in the paragraph and passed to check_italic_def,
- TestGeneratedPdfs - full run on the PDFs from generate_pdfs.py. File names describe the expected result:
  tp_* - all definitions must be reported, fp_* - nothing may be reported.
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, WordInfo
from analysis.modules.linguistics.linguistics_types import Block_context
from analysis.modules.linguistics.first_definition import check_first_definition, check_italic_def
from unit_tests.utils_generate_pdfs import LATEX_COMPILERS
from unit_tests.utils_test import pdf_to_blocks

PDF_DIR = Path(__file__).resolve().parent

CONTENT = "Sieć CNN (ang. Convolutional Neural Network) działa"
DEFINITION = "Convolutional Neural Network"
MESSAGE_PL = "Obcojęzyczne definicje powinny być zapisane kursywą."


def make_words(content, italic_words=()):
    '''Splits the text on spaces into WordInfo objects; words listed in italic_words get the italic flag.'''
    words = []
    pos = 0
    for i, text in enumerate(content.split(" ")):
        words.append(WordInfo(word_index=i, text=text, start_char=pos, end_char=pos + len(text),
                              font="Times", size=12.0, bold=False, italic=text in italic_words,
                              bbox=[10.0 * i, 100.0, 10.0 * i + 8, 112.0], page_number=2))
        pos += len(text) + 1
    return words


def make_paragraph(content, italic_words=(), language="pl"):
    block = ParagraphBlock(block_id=3, content=content, words=make_words(content, italic_words))
    # As in pipeline.py - each block gets the language chosen in the GUI
    block.language = language
    return Block_context(contents=content, language=language, block=block)


def check(italic_words=(), language="pl"):
    block = make_paragraph(CONTENT, italic_words, language).block
    return check_italic_def(DEFINITION, block, CONTENT.index(DEFINITION), len(DEFINITION), language)


class TestCheckItalicDef(unittest.TestCase):
    '''A foreign language definition must be written entirely in italic.'''

    def test_definition_not_italic(self):
        match = check()
        self.assertEqual(match.content, DEFINITION)
        self.assertEqual(match.category, "STYLE")
        self.assertEqual(match.message, MESSAGE_PL)
        self.assertEqual(match.block_id, 3)
        self.assertEqual(match.word_idxs, [3, 4, 5])
        self.assertEqual((match.page_start, match.page_end), (2, 2))

    def test_definition_italic(self):
        self.assertIsNone(check(italic_words=("Convolutional", "Neural", "Network)")))

    def test_italic_outside_definition_does_not_count(self):
        # Only the words of the definition are checked
        self.assertIsNotNone(check(italic_words=("Sieć", "CNN", "(ang.", "działa")))


class TestItalicDefinitionInParagraph(unittest.TestCase):
    '''check_first_definition finds "(ang. ...)" definitions and returns matches for those not in italic.'''

    def test_definition_not_italic_reported(self):
        _, _, italic_matches = check_first_definition([make_paragraph(CONTENT)], [], [])
        self.assertEqual([m.content for m in italic_matches], [DEFINITION])

    def test_definition_italic_not_reported(self):
        block = make_paragraph(CONTENT, italic_words=("Convolutional", "Neural", "Network)"))
        _, _, italic_matches = check_first_definition([block], [], [])
        self.assertEqual(italic_matches, [])


class TestGeneratedPdfs(unittest.TestCase):
    '''Full run extraction -> check_first_definition on PDFs from different compilers.'''

    @staticmethod
    def run_pdf(pdf_path):
        _, blocks = pdf_to_blocks(pdf_path)
        _, _, italic_matches = check_first_definition(blocks, [], [])
        return [m.content for m in italic_matches]

    def test_tp_foreign_definition_not_italic(self):
        expected = ["Convolutional Neural Network", "attention mechanism", "edge computing", "in vivo"]
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                self.assertEqual(self.run_pdf(PDF_DIR / f"tp_foreign_definition_not_italic_{compiler}.pdf"), expected)

    def test_fp_foreign_definition_italic(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                self.assertEqual(self.run_pdf(PDF_DIR / f"fp_foreign_definition_italic_{compiler}.pdf"), [])


if __name__ == "__main__":
    unittest.main()
