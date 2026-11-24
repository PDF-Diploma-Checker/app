'''
Lemmatization must not return a punctuation mark as the lemma of a word written with it.

Before the fix lemmatization("Transformer,") gave ",", because it returned the lemma of the last token. Italic words
like "Transformer," go into the proper names, so "," became a proper-name lemma, and every typo written right before
a comma ("subskrybcji,") had the lemma "," too and was dropped as a proper name (thesis from 2026-11-24, s.26).

Run:
    uv run python -m unittest unit_tests/linguistics/typos/test_lemma_punctuation.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, WordInfo
from analysis.modules.linguistics.helpers import lemmatization
from analysis.modules.linguistics.linguistics_types import Error_type
from analysis.modules.linguistics.proper_check import check_if_proper


class TestLemmaWithoutPunctuation(unittest.TestCase):

    def test_edge_punctuation_cut_off(self):
        for word, clean in [("subskrybcji,", "subskrybcji"), ("Transformer,", "Transformer"),
                            ("(Models)", "Models"), ("mechanism).", "mechanism"), ("„słowo”", "słowo")]:
            with self.subTest(word=word):
                self.assertEqual(lemmatization(word, "pl"), lemmatization(clean, "pl"))
                self.assertNotIn(lemmatization(word, "pl"), {",", ".", ")", "("})

    def test_comma_inside_number_kept(self):
        self.assertEqual(lemmatization("0,6,", "pl"), lemmatization("0,6", "pl"))

    def test_only_punctuation_unchanged(self):
        self.assertEqual(lemmatization(",", "pl"), ",")


class TestTypoBeforeCommaNotProperName(unittest.TestCase):

    def test_typo_before_comma_not_dropped(self):
        words = [WordInfo(word_index=0, text="subskrybcji,", start_char=0, end_char=12, font="Arial", size=10.0,
                          bold=False, italic=False, bbox=[0, 0, 10, 10], page_number=1)]
        block = ParagraphBlock(block_id=1, content="subskrybcji,", words=words)
        match = Error_type(content="subskrybcji", category="TYPOS", message="", offset=0, error_length=11,
                           block_id=1, page_start=1, page_end=1, word_idxs=[0], error_coordinate=[])
        # what the italic words "Transformer," and "(Models)" put into the proper names
        proper_names = [(text, lemmatization(text, "pl")) for text in ("Transformer,", "Models)")]
        self.assertFalse(check_if_proper(block, match, proper_names, lemmatization("subskrybcji", "pl")))


if __name__ == "__main__":
    unittest.main()
