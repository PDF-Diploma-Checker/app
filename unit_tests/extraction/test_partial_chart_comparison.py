import sys
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from analysis.modules.llm.image_analysis.consistency_checker import ConsistencyChecker, confirmed_reading
from analysis.modules.llm.image_analysis.figures import consistency_verdict
from app.llm_task import build_image_summary


class PartialChartComparisonTest(unittest.TestCase):
    def checker(self, answer):
        checker = object.__new__(ConsistencyChecker)
        checker.llm = MagicMock()
        checker.llm.create_chat_completion.return_value = {'choices': [{'message': {'content': json.dumps(answer)}}]}
        return checker

    def test_confirmed_minority_is_still_compared(self):
        checker = self.checker({'niezgodnosci': []})
        result = checker.check('A: 42 ms', 'Title\nA: 42 ms\nB: 0.3\nC: 0.7', printed=[42])
        self.assertEqual(result['poprawnosc_danych'], 'Partial')
        prompt = checker.llm.create_chat_completion.call_args.kwargs['messages'][0]['content']
        self.assertIn('A: 42 ms', prompt)
        self.assertNotIn('B: 0.3', prompt)
        self.assertNotIn('C: 0.7', prompt)

    def test_confirmed_mismatch_is_reported_despite_unconfirmed_rows(self):
        checker = self.checker({'niezgodnosci': [{'element': 'A', 'w_tekscie': '40 ms',
            'na_rysunku': '42 ms', 'text_quote': 'A: 40 ms', 'image_quote': 'A: 42 ms'}]})
        result = checker.check('A: 40 ms', 'A: 42 ms\nB: 0.3\nC: 0.7', printed=[42])
        self.assertEqual(result['poprawnosc_danych'], 'False')

    def test_axis_only_still_cannot_verify_estimated_values(self):
        checker = self.checker({'niezgodnosci': []})
        result = checker.check('A: 0.8', 'A: 0.8', printed=[0, .2, .4, .6, .8, 1])
        self.assertEqual(result['poprawnosc_danych'], 'Unreadable')
        checker.llm.create_chat_completion.assert_not_called()

    def test_no_unverified_number_in_a_multi_value_row_is_passed_through(self):
        self.assertEqual(confirmed_reading('A: 42, 55\nB: 21', [42, 21]), ('B: 21', True))

    def test_complete_comparison_remains_correct(self):
        checker = self.checker({'niezgodnosci': []})
        self.assertEqual(checker.check('A: 42', 'A: 42', printed=[42])['poprawnosc_danych'], 'True')

    def test_partial_is_neither_correct_nor_a_model_failure(self):
        self.assertEqual(consistency_verdict({'poprawnosc_danych': 'Partial'}), 'Partial')
        summary = build_image_summary([{'obrazek': 'Rysunek 1', 'poprawnosc_danych': 'Partial', 'bledy': 'Only A checked'}])
        self.assertEqual(summary['partial_count'], 1)
        self.assertEqual(summary['good_count'], 0)
        self.assertEqual(summary['bad_count'], 0)
        self.assertFalse(summary['analysis_failed'])
        self.assertIn('Częściowo sprawdzono', summary['details'][0])
