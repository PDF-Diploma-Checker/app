'''
Tests that a number with a decimal dot and a size suffix ("0.6B", "1.7B") is not cut into two sentences.

Run:
    uv run python -m unittest unit_tests/linguistics/sentence_check/test_number_sentence_split.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics.helpers import nlp_pl


class TestNumberSentenceSplit(unittest.TestCase):

    def sentences(self, text):
        return [s.text for s in nlp_pl(text).sents]

    def test_model_size_is_not_a_sentence_end(self):
        text = "Pulę utworzyły modele e5, Qwen3-Embedding 0.6B i Qwen3-Reranker 0.6B, uzupełnione o 88 par."
        self.assertEqual(len(self.sentences(text)), 1)

    def test_model_name_in_parenthesis(self):
        text = "Mniejszy model (Qwen3-1.7B-Base) osiąga wyniki. Drugie zdanie."
        self.assertEqual(len(self.sentences(text)), 2)


if __name__ == "__main__":
    unittest.main()
