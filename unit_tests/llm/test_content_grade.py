'''
Tests of the content grade calculation. The models are not needed: the similarities are given by the test.

Run (from the repository root):
    .venv/bin/python -m unittest unit_tests.llm.test_content_grade -v
'''
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from analysis.modules.llm import evaluate_sota, find_sota, get_grade, section_relevance
except ImportError as e:  # the base variant has no AI libraries
    raise unittest.SkipTest(f"AI libraries are not available: {e}")


def _section(purpose, thesis=None, has_content=True, name="1.1 Sekcja"):
    item = {"display": name, "summary": "tekst", "cosine_similarity": purpose, "has_content": has_content}
    if thesis is not None:
        item["section_similarity"] = thesis
    return item


class EmbeddingGradeTest(unittest.TestCase):
    def grade(self, *items):
        with patch.object(get_grade, "compute_similarity_for_summaries", return_value={"items": list(items)}), \
                patch.object(get_grade, "review_sections", return_value=self.unrelated(items)) as self.review:
            return get_grade.calculate_embedding_grade("cel", [])

    def unrelated(self, items):
        return [item for item in items if item["display"] in getattr(self, "model_rejects", ())]

    def test_section_fitting_the_thesis_is_on_topic_despite_low_purpose_similarity(self):
        self.assertEqual(self.grade(_section(0.12, 0.75), _section(0.40, 0.72))["grade"], 100.0)
        self.review.assert_not_called()

    def test_doubtful_section_goes_to_the_model_which_can_reject_it(self):
        self.model_rejects = ["Sieci"]
        result = self.grade(_section(0.45, 0.80), _section(0.34, 0.26, name="Sieci"))
        self.assertEqual(result["off_topic_sections"], 1)
        self.assertEqual([s["display"] for s in self.review.call_args.args[2]], ["Sieci"])

    def test_doubtful_section_kept_by_the_model_is_on_topic(self):
        self.assertEqual(self.grade(_section(0.45, 0.80), _section(0.34, 0.26))["grade"], 100.0)

    def test_section_fitting_nothing_is_off_topic_without_the_model(self):
        result = self.grade(_section(0.45, 0.80), _section(0.05, 0.10, name="Przepis na ciasto"))
        self.assertEqual(result["grade"], 50.0)
        self.assertEqual(result["off_topic_sections"], 1)

    def test_empty_section_does_not_count(self):
        result = self.grade(_section(0.45, 0.80), _section(0.0, has_content=False))
        self.assertEqual((result["grade"], result["total_sections"]), (100.0, 1))

    def test_thesis_without_sections_has_no_grade(self):
        self.assertIsNone(self.grade()["grade"])


class OffTopicLabelsTest(unittest.TestCase):
    def test_label_carries_the_reason(self):
        item = _section(0.3, 0.3, name="2.1 Sieci")
        item.update(below_threshold=True, off_topic_reason="Inny temat.")
        with patch.object(get_grade, "calculate_embedding_grade", return_value={"grade": 0.0, "items": [item]}):
            self.assertEqual(get_grade.get_content_grade("cel", [])[1], ["2.1 Sieci: Inny temat."])


class ReviewAnswerTest(unittest.TestCase):
    def review(self, answer):
        llm = MagicMock()
        llm.create_chat_completion.return_value = {"choices": [{"message": {"content": answer}}]}
        section = {"title": "2.1 Sieci", "summary": "TCP"}
        with patch.object(section_relevance, "make_llama", return_value=llm):
            unrelated = section_relevance.review_sections("cel", ["2.1 Sieci"], [section])
        llm.close.assert_called_once()
        return unrelated

    def test_unrelated_section_gets_the_reason(self):
        unrelated = self.review('{"uzasadnienie": "Inny temat.", "zwiazany": false}')
        self.assertEqual(unrelated[0]["off_topic_reason"], "Inny temat.")

    def test_related_section_stays(self):
        self.assertEqual(self.review('{"uzasadnienie": "Tak.", "zwiazany": true}'), [])

    def test_unclear_answer_does_not_lower_the_grade(self):
        self.assertEqual(self.review('{"uzasadnienie": "Nie wiem."}'), [])
        self.assertEqual(self.review("to nie jest JSON"), [])


class OverallGradeTest(unittest.TestCase):
    def test_weighted_grade(self):
        self.assertAlmostEqual(get_grade.get_overall_grade(100, 50, 100), 70.0)

    def test_missing_part_is_not_a_zero(self):
        self.assertAlmostEqual(get_grade.get_overall_grade(100, None, 50), 75.0)


class SotaPromptsTest(unittest.TestCase):
    def test_no_placeholders_in_the_rules(self):
        with patch.object(evaluate_sota, "evaluate_condition_over_chunks", side_effect=lambda prompt, chunks: prompt):
            for rule in (evaluate_sota.evaluate_r1, evaluate_sota.evaluate_r2, evaluate_sota.evaluate_r3):
                prompt = rule([])
                self.assertNotIn("reszta promptu", prompt)
                self.assertIn("ZWRÓĆ TRUE", prompt)

    def test_chapter_prompts_get_the_title_and_the_text(self):
        for prompt in (find_sota.PROMPT_EVALUATE_PL, find_sota.PROMPT_EVALUATE_EN):
            filled = prompt.format(title="TYTUL", content="TRESC")
            self.assertIn("TYTUL", filled)
            self.assertIn("TRESC", filled)


if __name__ == "__main__":
    unittest.main()
