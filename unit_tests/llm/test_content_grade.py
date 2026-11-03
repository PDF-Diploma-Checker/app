'''
Tests of the content grade calculation. The models are not needed: the similarities are given by the test.

Run (from the repository root):
    .venv/bin/python -m unittest unit_tests.llm.test_content_grade -v
'''
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from analysis.modules.llm import evaluate_sota, find_sota, get_grade
except ImportError as e:  # the base variant has no AI libraries
    raise unittest.SkipTest(f"AI libraries are not available: {e}")


def _section(purpose, thesis=None, has_content=True, name="1.1 Sekcja"):
    item = {"display": name, "summary": "tekst", "cosine_similarity": purpose, "has_content": has_content}
    if thesis is not None:
        item["section_similarity"] = thesis
    return item


class EmbeddingGradeTest(unittest.TestCase):
    def grade(self, *items):
        with patch.object(get_grade, "compute_similarity_for_summaries", return_value={"items": list(items)}):
            return get_grade.calculate_embedding_grade("cel", [])

    def test_section_fitting_the_thesis_is_on_topic_despite_low_purpose_similarity(self):
        self.assertEqual(self.grade(_section(0.12, 0.60), _section(0.40, 0.30))["grade"], 100.0)

    def test_section_fitting_nothing_is_off_topic(self):
        result = self.grade(_section(0.45, 0.60), _section(0.05, 0.10, name="Przepis na ciasto"))
        self.assertEqual(result["grade"], 50.0)
        self.assertEqual(result["off_topic_sections"], 1)

    def test_empty_section_does_not_count(self):
        result = self.grade(_section(0.45, 0.60), _section(0.0, has_content=False))
        self.assertEqual((result["grade"], result["total_sections"]), (100.0, 1))

    def test_thesis_without_sections_has_no_grade(self):
        self.assertIsNone(self.grade()["grade"])


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
