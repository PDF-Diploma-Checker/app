'''
Tests that the acronym check reports only real abbreviations that need expanding.

Checks that:
- mixed case words and capitalised names (PhysX, Unitree, Featherstone) are not reported,
- an engine name (ODE) and a product with a model number (RTX 5060) are not reported,
- an acronym written right after its Polish description is accepted, both when the initials match
  and when the description shares words with a definition given later (GAE),
- a definition glued to a stray parenthesis, e.g. "RMA( (Rapid Motor Adaptation)", is accepted,
- a real undefined acronym is still reported.

Run:
    uv run python -m unittest unit_tests/linguistics/acronyms/test_names_and_described_acronyms.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics.first_definition import check_first_definition
from analysis.modules.linguistics.check_acronym import check_if_was_defined
from unit_tests.linguistics.acronyms.test_first_definition_extraction import make_block


def reported(texts):
    blocks = [make_block(text, block_id=i, page=i) for i, text in enumerate(texts, start=1)]
    acronyms_with_defs, proper_names, _ = check_first_definition(blocks, [], [])
    matches, _ = check_if_was_defined(blocks, acronyms_with_defs, proper_names)
    return {m.content.strip("(),.;:") for m in matches}


class TestNamesAreNotAcronyms(unittest.TestCase):

    def test_mixed_case_and_capitalised_names(self):
        text = "Symulację wykonano w PhysX na robocie Unitree A1 z algorytmem Featherstone oraz SemiImplicit."
        self.assertEqual(reported([text]), set())

    def test_engine_name(self):
        text = "Z kolei Webots opiera się na silniku ODE [58], który stawia na szybkość."
        self.assertNotIn("ODE", reported([text]))

    def test_product_with_model_number(self):
        text = "Wydajność zweryfikowano na karcie graficznej NVIDIA GeForce RTX 5060 Ti."
        self.assertNotIn("RTX", reported([text]))

    def test_real_undefined_acronym_still_reported(self):
        text = "Procedura obejmuje szum pomiarowy w odczytach enkoderów i jednostki IMU oraz losowe impulsy."
        self.assertIn("IMU", reported([text]))


class TestDescribedAcronyms(unittest.TestCase):

    def test_polish_description_before_acronym_with_matching_initials(self):
        text = "Dane przechowuje system zarządzania bazą danych SZBD na serwerze uczelni."
        self.assertNotIn("SZBD", reported([text]))

    def test_polish_description_before_acronym_defined_later(self):
        first_use = "W algorytmie stanowi fundament uogólnionego estymatora korzyści GAE (podrozdz. 2.6)."
        later = "Uogólniona estymacja funkcji korzyści (GAE) jest sumą ważoną błędów różnicy czasowej."
        self.assertNotIn("GAE", reported([first_use, later]))

    def test_unrelated_words_before_acronym_defined_later(self):
        first_use = "Wyniki porównano z metodą GAE w kolejnym rozdziale."
        later = "Uogólniona estymacja funkcji korzyści (GAE) jest sumą ważoną błędów różnicy czasowej."
        self.assertIn("GAE", reported([first_use, later]))

    def test_definition_after_stray_parenthesis(self):
        text = "Architektura RMA( (Rapid Motor Adaptation) [45] rozdziela sterowanie na dwie części."
        self.assertNotIn("RMA", reported([text]))


if __name__ == "__main__":
    unittest.main()
