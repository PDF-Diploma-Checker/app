'''
Tests of the second opinion of the text model on the findings of the language checks. No model or GPU is needed.
'''
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics.decision_log import report_sources  # noqa: E402
from analysis.modules.linguistics.linguistics_types import Error_type  # noqa: E402
try:
    from analysis.modules.llm import linguistic_review as review
except ImportError as e:  # the base variant has no AI libraries
    raise unittest.SkipTest(f"AI libraries are not available: {e}")


def finding(content="sie", source="language_tool", context="uczy «sie» dalej"):
    match = Error_type(content, "TYPOS", "Literówka", 0, len(content), 1, 1, 1, [], [], rule="R")
    match.source, match.context = source, context
    return match


def model(*answers):
    llm = MagicMock()
    llm.create_chat_completion.side_effect = [
        answer if isinstance(answer, Exception) else {"choices": [{"message": {"content": answer}}]} for answer in answers
    ]
    return llm


def verdict(is_error, reason="powód", fixed=None):
    return json.dumps({"poprawny_zapis": fixed, "uzasadnienie": reason, "blad": is_error})


class ReviewTest(unittest.TestCase):
    def run_review(self, matches, llm):
        with patch.object(review, "make_llama", return_value=llm), patch.object(review, "typo_check", return_value=False):
            return review.review_findings(matches)

    def test_only_rejected_findings_leave(self):
        real, correct = finding("sie"), finding("Kubernetes")
        with self.assertLogs("analysis.modules.linguistics.decision_log", "INFO") as logs:
            kept = self.run_review([real, correct], model(verdict(True, fixed="się"), verdict(False, "nazwa własna", "Kubernetes")))
        self.assertEqual(kept, [real])
        rejected = [line for line in logs.output if "[MODEL REJECTED]" in line]
        self.assertEqual(len(rejected), 1)
        self.assertIn("Kubernetes", rejected[0])
        self.assertIn("nazwa własna", rejected[0])

    def test_a_word_the_model_would_write_differently_stays(self):
        match = finding("czesto")
        with self.assertLogs("analysis.modules.linguistics.decision_log", "INFO") as logs:
            kept = self.run_review([match], model(verdict(False, "poprawne słowo", "często")))
        self.assertEqual(kept, [match])
        self.assertTrue(any("[MODEL CONFIRMED]" in line and "często" in line for line in logs.output))

    def test_a_long_fragment_needs_no_copy(self):
        match = finding("To jest bardzo długie zdanie, którego model nie przepisuje w odpowiedzi.")
        self.assertEqual(self.run_review([match], model(verdict(False))), [])

    def test_an_unclear_answer_keeps_the_finding(self):
        for answer in ('{"uzasadnienie": "nie wiem"}', '{"uzasadnienie": "ok", "blad": false}', "to nie JSON", RuntimeError("model")):
            match = finding()
            with self.assertLogs("analysis.modules.linguistics.decision_log", "INFO") as logs, patch.object(review.logger, "exception"):
                self.assertEqual(self.run_review([match], model(answer)), [match])
            self.assertTrue(any("[MODEL NOT ASKED]" in line for line in logs.output))

    def test_findings_the_text_does_not_show_are_not_asked_about(self):
        matches = [finding(source="first_definition"), finding(source="acronym_check"), finding(context="")]
        with patch.object(review, "make_llama") as make:
            self.assertEqual(review.review_findings(matches), matches)
        make.assert_not_called()

    def test_a_format_rule_is_not_asked_about(self):
        matches = [finding("możemy", source="sentence_check"), finding("-", source="dash_check")]
        matches[0].category = "PERSONAL_FORM"
        with patch.object(review, "make_llama") as make, patch.object(review, "typo_check", return_value=False):
            self.assertEqual(review.review_findings(matches), matches)
        make.assert_not_called()

    def test_a_word_known_with_polish_letters_is_a_typo_for_certain(self):
        with patch.object(review, "typo_check", side_effect=lambda word: word == "często"), patch.object(review, "make_llama") as make:
            match = finding("czesto")
            self.assertEqual(review.review_findings([match]), [match])
        make.assert_not_called()

    def test_names_are_not_treated_as_missing_letters(self):
        with patch.object(review, "typo_check", return_value=True):
            self.assertIsNone(review._with_polish_letters("ODE"))
            self.assertIsNone(review._with_polish_letters("czesto"))     # known as it is

    def test_the_model_reads_the_text_around_the_finding(self):
        llm = model(verdict(True))
        self.run_review([finding()], llm)
        prompt = llm.create_chat_completion.call_args.kwargs["messages"][0]["content"]
        self.assertIn("uczy «sie» dalej", prompt)
        self.assertIn("Literówka", prompt)


class IsolatedReviewTest(unittest.TestCase):
    def run_isolated(self, outcome):
        from app import llm_process

        matches = [finding()]
        with patch.object(llm_process, "_run_once", return_value=outcome), patch.object(llm_process.logger, "error") as error:
            return matches, llm_process.run_language_review_isolated(matches), error

    def test_the_result_of_the_process_is_used(self):
        from app import llm_process

        self.assertEqual(self.run_isolated(llm_process._Outcome("result", []))[1], [])

    def test_a_crash_or_an_error_keeps_all_the_findings(self):
        from app import llm_process

        for outcome in (llm_process._Outcome("crash", -6, "status"), llm_process._Outcome("error", "boom", "trace")):
            matches, kept, error = self.run_isolated(outcome)
            self.assertEqual(kept, matches)
            error.assert_called_once()


class DecisionLogTest(unittest.TestCase):
    def test_sources_mark_the_check_and_the_text_around(self):
        text = "Model uczy sie dalej."
        match = Error_type("sie", "TYPOS", "Literówka", text.index("sie"), 3, 7, 1, 1, [], [])
        block = SimpleNamespace(contents=text, language="pl", block=SimpleNamespace(block_id=7, type="paragraph"))
        report_sources([("language_tool", [match])], [match], [block])
        self.assertEqual(match.source, "language_tool")
        self.assertEqual(match.context, "Model uczy «sie» dalej.")


if __name__ == "__main__":
    unittest.main()
