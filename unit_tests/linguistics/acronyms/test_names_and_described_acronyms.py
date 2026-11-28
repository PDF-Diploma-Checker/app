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

    def test_rtx_needs_no_expansion_without_a_model_number_too(self):
        text = "Trening przyspieszono na kartach RTX, a obliczenia przeniesiono na GPU."
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

    def test_polish_description_matches_second_definition(self):
        first_use = "W algorytmie stanowi fundament uogólnionego estymatora korzyści GAE (podrozdz. 2.6)."
        english = "Metoda GAE (ang. Generalized Advantage Estimation) jest sumą ważoną błędów."
        polish = "Uogólniona estymacja funkcji korzyści (GAE) jest sumą ważoną błędów różnicy czasowej."
        self.assertNotIn("GAE", reported([first_use, english, polish]))

    def test_unrelated_words_before_acronym_defined_later(self):
        first_use = "Wyniki porównano z metodą GAE w kolejnym rozdziale."
        later = "Uogólniona estymacja funkcji korzyści (GAE) jest sumą ważoną błędów różnicy czasowej."
        self.assertIn("GAE", reported([first_use, later]))

    def test_definition_after_stray_parenthesis(self):
        text = "Architektura RMA( (Rapid Motor Adaptation) [45] rozdziela sterowanie na dwie części."
        self.assertNotIn("RMA", reported([text]))


class TestAcronymBeforeParenthesis(unittest.TestCase):

    def test_description_in_parenthesis_is_a_definition(self):
        first_use = "Użyto modelu BGE (nazwa modelu) do uporządkowania wyników."
        later = "Model BGE uzyskał najwyższą średnią precyzję."
        self.assertNotIn("BGE", reported([first_use, later]))

    def test_model_identifier_in_parenthesis_is_a_definition(self):
        first_use = "W dalszej części modele oznaczono skrótami: e5 (multilingual-e5-large) i BGE (bge-re-ranker-v2-m3)."
        later = "BGE miał wyższe AP niż LaBSE na 10 z 11 uczelni."
        self.assertNotIn("BGE", reported([first_use, later]))

    def test_reference_in_parenthesis_is_not_a_definition(self):
        text = "Wynik wyznaczono miarą IMU (podrozdz. 2.6) oraz IMU (tabela 6.5)."
        self.assertIn("IMU", reported([text]))

    def test_number_in_parenthesis_is_not_a_definition(self):
        self.assertIn("IMU", reported(["Wynik uzyskano miarą IMU (2024) na zbiorze testowym."]))

    def test_heading_in_capitals_registers_no_acronyms(self):
        heading = make_block("EWALUACJA MODELI (ZOFIA NARLOCH)", block_id=1, page=1)
        heading.block.type = "heading"
        acronyms_with_defs, _, _ = check_first_definition([heading], [], [])
        self.assertNotIn("MODELI", acronyms_with_defs)


if __name__ == "__main__":
    unittest.main()
