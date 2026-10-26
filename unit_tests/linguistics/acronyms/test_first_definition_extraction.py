'''
Tests for acronym definition extraction in first_definition.py.

Checks that:
- definitions in parentheses (e.g. "CNN (ang. Convolutional Neural Network)", "RF (Random Forest)")
  extract the actual definition words without regex pollution or "ang.",
- proper_names dictionary is not polluted with surrounding words or punctuation,
- extracted definitions properly satisfy check_if_was_defined so no undefined acronym error is raised.

Run:
    uv run python -m unittest unit_tests/linguistics/acronyms/test_first_definition_extraction.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, WordInfo
from analysis.modules.linguistics.linguistics_types import Block_context
from analysis.modules.linguistics.first_definition import check_first_definition
from analysis.modules.linguistics.check_acronym import check_if_was_defined


def make_words(content, page=1):
    words = []
    pos = 0
    for i, text in enumerate(content.split(" ")):
        words.append(WordInfo(
            word_index=i, text=text, start_char=pos, end_char=pos + len(text),
            font="Times", size=12.0, bold=False, italic=False,
            bbox=[10.0 * i, 100.0, 10.0 * i + 8, 112.0], page_number=page
        ))
        pos += len(text) + 1
    return words


def make_block(content, block_id=1, language="pl"):
    p = ParagraphBlock(block_id=block_id, content=content, words=make_words(content))
    p.language = language
    return Block_context(contents=content, language=language, block=p)


class TestFirstDefinitionExtraction(unittest.TestCase):

    def test_acronym_with_foreign_expansion(self):
        text = "Zastosowano model CNN (ang. Convolutional Neural Network) do klasyfikacji obrazów."
        block = make_block(text, block_id=1)
        proper_names = []
        acronyms_with_defs, proper_names, _ = check_first_definition([block], proper_names, [])

        self.assertIn("CNN", acronyms_with_defs)
        definition = acronyms_with_defs["CNN"][0]
        self.assertIn("Convolutional Neural Network", definition)
        self.assertNotIn("ang.", definition)

    def test_acronym_simple_parentheses(self):
        text = "Wykorzystano algorytm RF (Random Forest) do wstępnej analizy danych."
        block = make_block(text, block_id=2)
        proper_names = []
        acronyms_with_defs, proper_names, _ = check_first_definition([block], proper_names, [])

        self.assertIn("RF", acronyms_with_defs)
        definition = acronyms_with_defs["RF"][0]
        self.assertEqual(definition, "Random Forest")

    def test_acronym_inside_ang_parentheses(self):
        text = "Badano algorytmy (ang. Reinforcement Learning, RL) w grach."
        block = make_block(text, block_id=3)
        proper_names = []
        acronyms_with_defs, proper_names, _ = check_first_definition([block], proper_names, [])

        self.assertIn("RL", acronyms_with_defs)
        definition = acronyms_with_defs["RL"][0]
        self.assertIn("Reinforcement Learning", definition)

    def test_proper_names_not_polluted(self):
        text = "Metoda SVM (ang. Support Vector Machine) jest popularna."
        block = make_block(text, block_id=4)
        proper_names = []
        _, proper_names, _ = check_first_definition([block], proper_names, [])

        pn_words = [p[0] for p in proper_names]
        # Valid words from definition or the acronym itself
        self.assertIn("SVM", pn_words)
        self.assertIn("Support", pn_words)
        self.assertIn("Vector", pn_words)
        self.assertIn("Machine", pn_words)
        # Should not include punctuation or sentence end words
        for w in pn_words:
            self.assertFalse(any(c in w for c in "(),.:;[]"))
        self.assertNotIn("ang", pn_words)
        self.assertNotIn("popularna", pn_words)

    def test_defined_acronym_resolves_undefined_check(self):
        block1 = make_block("Użyto modelu LLM (ang. Large Language Model) w projekcie.", block_id=1)
        block2 = make_block("Model LLM poradził sobie znakomicie z tym zadaniem.", block_id=2)
        proper_names = []
        acronyms_with_defs, proper_names, _ = check_first_definition([block1, block2], proper_names, [])
        undef_matches, _ = check_if_was_defined([block1, block2], acronyms_with_defs, proper_names)

        # Since LLM was defined in block 1, its subsequent use in block 2 must NOT be flagged
        llm_errors = [m for m in undef_matches if m.content == "LLM"]
        self.assertEqual(len(llm_errors), 0)


class TestGeneratedPdfs(unittest.TestCase):
    """Test extraction of acronym definitions from existing generated test PDFs."""

    def test_fp_defined_math_font_acronym_definitions_clean(self):
        from unit_tests.utils_test import LATEX_COMPILERS, pdf_to_blocks
        from analysis.modules.linguistics.proper_names import get_proper_names

        pdf_dir = Path(__file__).resolve().parent
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                pdf_path = pdf_dir / f"fp_defined_math_font_acronym_{compiler}.pdf"
                if not pdf_path.exists():
                    continue
                raw_blocks, blocks = pdf_to_blocks(pdf_path)
                proper_names, _ = get_proper_names(blocks)
                definitions, proper_names, _ = check_first_definition(
                    blocks, proper_names, raw_blocks.reference_sections.acronyms
                )
                matches, _ = check_if_was_defined(blocks, definitions, proper_names)

                # Definitions must be properly extracted without 'ang.'
                self.assertIn("QXV", definitions)
                self.assertEqual(definitions["QXV"][0], "Quick Xray Vector")
                self.assertIn("JXW", definitions)
                self.assertEqual(definitions["JXW"][0], "Joint Xray Weighting")
                self.assertIn("GXW", definitions)
                self.assertEqual(definitions["GXW"][0], "Global Xray Wave")
                self.assertIn("MXW", definitions)
                self.assertEqual(definitions["MXW"][0], "Multi Xray Weighting")

                # No false positive undefined acronym errors
                self.assertEqual(len(matches), 0)


if __name__ == "__main__":
    unittest.main()

