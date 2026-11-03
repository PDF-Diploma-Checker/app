'''
Testy logów czasu analizy i wyników embeddingów. Nie wymagają modeli ani GPU.

Uruchomienie (z katalogu głównego repozytorium):
    .venv/bin/python -m unittest unit_tests.llm.test_analysis_logging -v
'''
import logging
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.llm.results_log import log_embedding_results, log_grade_calculation, log_results  # noqa: E402
from common.timing import StageTimer, log_time  # noqa: E402

logger = logging.getLogger("test.timing")


class TimingTest(unittest.TestCase):
    def test_finished_block_is_logged(self):
        with self.assertLogs(logger, "INFO") as logs:
            with log_time(logger, "Extraction"):
                pass
        self.assertRegex(logs.output[0], r"\[TIME\] Extraction: \d+\.\d s \(finished\)")

    def test_failed_block_is_logged_and_the_error_passes(self):
        with self.assertLogs(logger, "INFO") as logs:
            with self.assertRaises(ValueError):
                with log_time(logger, "Extraction"):
                    raise ValueError
        self.assertIn("(interrupted)", logs.output[0])

    def test_cancellation_is_logged_and_passes(self):
        from common.cancellation import AnalysisCancelled

        with self.assertLogs(logger, "INFO") as logs:
            with self.assertRaises(AnalysisCancelled):
                with log_time(logger, "Whole"):
                    raise AnalysisCancelled()
        self.assertIn("(interrupted)", logs.output[0])

    def test_stages_are_logged_in_order_once(self):
        timer = StageTimer(logger, "LLM")
        with self.assertLogs(logger, "INFO") as logs:
            timer.next("one")
            timer.next("two")
            timer.finish()
            timer.finish()
        self.assertEqual(len(logs.output), 2)
        self.assertIn("LLM - one:", logs.output[0])
        self.assertIn("LLM - two:", logs.output[1])


class EmbeddingLogTest(unittest.TestCase):
    NAME = "analysis.modules.llm.results_log"

    def test_record_has_purpose_scores_and_summaries(self):
        items = [
            {"display": "1. Wstęp", "summary": "Streszczenie wstępu", "cosine_similarity": 0.9, "below_threshold": False},
            {"display": "2. Inne", "summary": "O czym innym", "cosine_similarity": 0.12, "below_threshold": True},
        ]
        with self.assertLogs(self.NAME, "INFO") as logs:
            log_embedding_results("Cel pracy", items, 0.785, 0.51, 50.0)
        self.assertEqual(len(logs.records), 1)
        text = logs.records[0].getMessage()
        for expected in ("Thesis purpose: Cel pracy", "Threshold: 0.7850", "average similarity: 0.5100",
                         "off-topic sections: 1/2", "embedding grade: 50.00",
                         "1. [0.9000 ok] 1. Wstęp", "Summary: Streszczenie wstępu",
                         "2. [0.1200 OFF-TOPIC] 2. Inne", "Summary: O czym innym"):
            self.assertIn(expected, text)

    def test_missing_data_does_not_break_logging(self):
        with self.assertLogs(self.NAME, "INFO") as logs:
            log_embedding_results("", [{"summary": ""}], 0.785, 0.0, 0.0)
        text = logs.records[0].getMessage()
        self.assertIn("Thesis purpose: (none)", text)
        self.assertIn("Section 1", text)
        self.assertIn("Summary: (none)", text)


class ResultsLogTest(unittest.TestCase):
    NAME = "analysis.modules.llm.results_log"

    def test_results_are_one_record_with_all_fields(self):
        with self.assertLogs(self.NAME, "INFO") as logs:
            log_results("SOTA", score=50, title="Stan wiedzy")
        self.assertEqual(len(logs.records), 1)
        text = logs.records[0].getMessage()
        for expected in ("[RESULTS] SOTA", "score: 50", "title: Stan wiedzy"):
            self.assertIn(expected, text)

    def test_grade_calculation_shows_every_component(self):
        with self.assertLogs(self.NAME, "INFO") as logs:
            log_grade_calculation([("SOTA", 50, 0.2), ("Embeddings", 100.0, 0.6)], 70.0)
        text = logs.records[0].getMessage()
        for expected in ("SOTA: 50 x 0.2 = 10.00", "Embeddings: 100.0 x 0.6 = 60.00", "Overall grade: 70.00 / 100"):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
