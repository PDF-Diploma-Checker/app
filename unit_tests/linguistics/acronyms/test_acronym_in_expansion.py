'''
Tests that an acronym written inside the expansion of another acronym needs no definition of its own.

Run:
    uv run python -m unittest unit_tests/linguistics/acronyms/test_acronym_in_expansion.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from unit_tests.linguistics.acronyms.test_names_and_described_acronyms import reported


class TestAcronymInsideExpansion(unittest.TestCase):

    def test_acronym_in_expansion_of_another_is_not_reported(self):
        text = "Modele 4B w formacie GGUF (ang. GGML Unified Format) uruchamiano przez serwer llama.cpp."
        self.assertNotIn("GGML", reported([text]))

    def test_unrelated_undefined_acronym_is_still_reported(self):
        text = "Modele 4B w formacie GGUF (ang. GGML Unified Format) uruchamiano z IMU."
        self.assertIn("IMU", reported([text]))


if __name__ == "__main__":
    unittest.main()
