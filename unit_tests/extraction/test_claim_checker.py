'''
Tests of checking what the text says about a figure on the figure itself. The answers of the models are given by the test.

Run (from the repository root):
    .venv/bin/python -m unittest unit_tests.extraction.test_claim_checker -v
'''
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.llm.image_analysis.claim_checker import (
    about_figure, check_claim, claims_from_answer, claims_verdict, extract_claims,
)
from app.llm_task import build_image_summary

PARAGRAPH = "Na rysunku 6.3 przedstawiono przebieg nagrody. Widoczna jest poprawa nagrody z około 5,0 do 6,0."


def _figure(number):
    return {"id": f"Rysunek {number}", "number": number, "family": "rys"}


def _engine(*answers):
    engine = MagicMock()
    engine.ask_yes_no.side_effect = list(answers)
    return engine


class ClaimsFromAnswerTest(unittest.TestCase):
    def test_a_quote_from_the_paragraph_is_kept(self):
        answer = {"stwierdzenia": [{"cytat": "poprawa nagrody z około 5,0 do 6,0", "teza": "The reward rises from 5.0 to 6.0."}]}
        self.assertEqual(claims_from_answer(answer, PARAGRAPH),
                         [{"quote": "poprawa nagrody z około 5,0 do 6,0", "claim": "The reward rises from 5.0 to 6.0."}])

    def test_a_quote_the_paragraph_does_not_have_is_dropped(self):
        answer = {"stwierdzenia": [{"cytat": "nagroda spada do 3,0", "teza": "The reward falls to 3.0."}]}
        self.assertEqual(claims_from_answer(answer, PARAGRAPH), [])

    def test_an_answer_without_the_list_gives_nothing(self):
        self.assertEqual(claims_from_answer({"cos": 1}, PARAGRAPH), [])
        self.assertEqual(claims_from_answer([], PARAGRAPH), [])

    def test_a_broken_model_answer_gives_nothing(self):
        llm = MagicMock()
        llm.create_chat_completion.return_value = {"choices": [{"message": {"content": "not json"}}]}
        self.assertEqual(extract_claims(llm, PARAGRAPH, "Rysunek 6.3"), [])

    def test_the_statements_come_from_the_text_model(self):
        llm = MagicMock()
        answer = {"stwierdzenia": [{"cytat": "z około 5,0 do 6,0", "teza": "The reward rises from 5.0 to 6.0."}]}
        llm.create_chat_completion.return_value = {"choices": [{"message": {"content": json.dumps(answer)}}]}
        self.assertEqual([c["claim"] for c in extract_claims(llm, PARAGRAPH, "Rysunek 6.3")],
                         ["The reward rises from 5.0 to 6.0."])


class AboutFigureTest(unittest.TestCase):
    def test_a_paragraph_on_one_figure_stays_whole(self):
        images = [_figure("6.3"), _figure("6.4")]
        self.assertEqual(about_figure(PARAGRAPH, images[0], images), PARAGRAPH)

    def test_a_paragraph_on_two_figures_keeps_the_sentences_of_this_one(self):
        images = [_figure("7.6"), _figure("7.7")]
        paragraph = "Skuteczność wzrosła z 37/80 do 76/80 (rys. 7.6). Upadki na skrzyniach zniknęły (rys. 7.7)."
        self.assertEqual(about_figure(paragraph, images[0], images), "Skuteczność wzrosła z 37/80 do 76/80 (rys. 7.6).")


class CheckClaimTest(unittest.TestCase):
    def test_a_yes_supports_the_statement(self):
        self.assertEqual(check_claim(_engine("YES."), b"", "The reward rises."), "supported")

    def test_a_no_is_never_an_error(self):
        self.assertEqual(check_claim(_engine("NO."), b"", "The reward rises to 8.0."), "unclear")

    def test_an_answer_that_is_neither_is_unclear(self):
        self.assertEqual(check_claim(_engine("I cannot tell."), b"", "The reward rises."), "unclear")


class ClaimsVerdictTest(unittest.TestCase):
    claim = {"quote": "z około 5,0 do 6,0", "claim": "The reward rises from 5.0 to 6.0."}

    def test_a_supported_statement_makes_the_figure_agree(self):
        self.assertEqual(claims_verdict([(self.claim, "supported"), (self.claim, "unclear")]), ("True", "None"))

    def test_nothing_to_check_is_not_an_error(self):
        self.assertEqual(claims_verdict([])[0], "NoData")
        self.assertEqual(claims_verdict([(self.claim, "unclear")])[0], "NoData")


class SummaryTest(unittest.TestCase):
    def test_figures_with_nothing_to_compare_are_counted_apart(self):
        summary = build_image_summary([
            {"obrazek": "Rysunek 1", "poprawnosc_danych": "NoData", "bledy": "x"},
            {"obrazek": "Rysunek 2", "poprawnosc_danych": "NoData", "bledy": "x"},
            {"obrazek": "Rysunek 2", "poprawnosc_danych": "True", "bledy": "None"},
            {"obrazek": "Rysunek 3", "poprawnosc_danych": "Error", "bledy": "x"},
        ])
        self.assertEqual((summary["nodata_count"], summary["good_count"], summary["unchecked_count"]), (1, 1, 1))
        self.assertFalse(any(line.startswith("Rysunek 1") for line in summary["problem_details"]))


if __name__ == "__main__":
    unittest.main()
