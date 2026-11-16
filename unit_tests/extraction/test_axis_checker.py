"""Conservative axis evidence checks; no vision runtime, model or GPU is loaded."""
import importlib
import io
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from PIL import Image
from analysis.modules.llm.image_analysis.figures import scale_problem

# Import only the checker, replacing the heavyweight runtime at its boundary.
_runtime = ModuleType('analysis.modules.llm.image_analysis.vision_engine')
_runtime.VisionEngine = MagicMock()
_runtime.too_small_to_read = MagicMock(return_value=False)
with patch.dict(sys.modules, {_runtime.__name__: _runtime}):
    axes = importlib.import_module('analysis.modules.llm.image_analysis.axis_checker')


def picture(width=400, height=300):
    out = io.BytesIO()
    Image.new('RGB', (width, height), 'white').save(out, 'PNG')
    return out.getvalue()


class AxisEvidenceTests(unittest.TestCase):
    def read(self, first, second, bar=True):
        engine = MagicMock()
        engine.list_numbers.side_effect = [first, second]
        return axes._axis_error(engine, picture(), bar, 'en')

    def test_empty_readouts_are_unassessed(self):
        with self.assertRaises(axes._AxisUnchecked):
            self.read('NONE', 'NONE')

    def test_different_readouts_with_same_problem_are_unassessed(self):
        with self.assertRaises(axes._AxisUnchecked):
            self.read('100;110;120;130', '200;210;220;230')

    def test_only_one_readable_sequence_is_unassessed(self):
        with self.assertRaises(axes._AxisUnchecked):
            self.read('0;10;20;30', 'NONE')

    def test_too_few_ticks_are_unassessed(self):
        with self.assertRaises(axes._AxisUnchecked):
            self.read('100;110;120', '100;110;120')

    def test_nonmonotonic_readouts_are_unassessed(self):
        with self.assertRaises(axes._AxisUnchecked):
            self.read('100;120;110;130', '100;120;110;130')

    def test_partial_readouts_are_unassessed(self):
        with self.assertRaises(axes._AxisUnchecked):
            self.read('100;110;UNKNOWN;120;130', '100;110;UNKNOWN;120;130')

    def test_confirmed_truncated_bar_is_reported(self):
        self.assertIn('starts at 100', self.read('100;110;120;130', '100;110;120;130'))

    def test_confirmed_uneven_axis_is_reported(self):
        self.assertIn('uneven', self.read('0;10;25;55', '0;10;25;55'))

    def test_line_chart_may_start_above_zero(self):
        self.assertIsNone(self.read('100;110;120;130', '100;110;120;130', False))

    def test_logarithmic_axis_is_not_reported(self):
        self.assertIsNone(self.read('1;10;100;1000', '1;10;100;1000'))

    def test_missing_tick_is_not_reported(self):
        self.assertIsNone(self.read('0;10;30;40', '0;10;30;40'))

    def test_descending_axis_is_supported(self):
        self.assertIn('starts at 100', self.read('130;120;110;100', '130;120;110;100'))

    def test_strip_never_pads_beyond_image(self):
        for width in (1, 20, 59, 60, 100, 1000):
            with self.subTest(width=width):
                with Image.open(io.BytesIO(axes._axis_strip(picture(width), 2))) as strip:
                    self.assertEqual(strip.width, min(width, max(int(width * .16), 60)) * 2)

    def test_scrambled_ticks_are_not_sorted_into_evidence(self):
        self.assertIsNone(scale_problem([130, 110, 120, 100], True))

    def test_nonfinite_ticks_are_not_evidence(self):
        self.assertIsNone(scale_problem([0, 10, 20, float('inf')], True))


class AxisReportTests(unittest.TestCase):
    def report(self, answers, numbers=('100;110;120;130',) * 2, blurry=False, small=False, language='en'):
        engine = MagicMock()
        engine.ask_yes_no.side_effect = answers
        engine.list_numbers.side_effect = numbers
        engine.is_blurry.return_value = blurry
        with patch.object(axes, 'collect_figures', return_value=[{'id': 'Fig. 1', 'bytes': picture()}]), \
             patch.object(axes, 'VisionEngine') as runtime, \
             patch.object(axes, 'too_small_to_read', return_value=small):
            runtime.return_value.__enter__.return_value = engine
            return axes.get_axis_report(None, None, language), engine

    def test_unknown_bar_never_falls_back_to_line(self):
        report, engine = self.report(['UNKNOWN', 'YES'])
        self.assertTrue(report[0]['analysis_unchecked'])
        self.assertEqual(engine.ask_yes_no.call_count, 1)
        engine.list_numbers.assert_not_called()

    def test_ambiguous_classification_is_unassessed(self):
        for answer in ('yes no', '', 'not yes', 'yes, maybe'):
            with self.subTest(answer=answer):
                report, _ = self.report([answer])
                self.assertTrue(report[0]['analysis_unchecked'])

    def test_unknown_line_is_unassessed(self):
        report, _ = self.report(['NO', 'UNKNOWN'])
        self.assertTrue(report[0]['analysis_unchecked'])

    def test_noncartesian_is_skipped(self):
        report, engine = self.report(['NO', 'NO'])
        self.assertEqual(report, [])
        engine.list_numbers.assert_not_called()

    def test_unconfirmed_complete_linear_axis_is_unassessed(self):
        for answer in ('NO', 'UNKNOWN'):
            with self.subTest(answer=answer):
                report, engine = self.report(['YES', answer])
                self.assertTrue(report[0]['analysis_unchecked'])
                engine.list_numbers.assert_not_called()

    def test_unreadable_or_unknown_quality_is_unassessed(self):
        for blurry in (True, None):
            with self.subTest(blurry=blurry):
                report, engine = self.report(['YES'], blurry=blurry)
                self.assertTrue(report[0]['analysis_unchecked'])
                engine.list_numbers.assert_not_called()

    def test_small_image_has_localized_reason(self):
        report, _ = self.report([], small=True, language='pl')
        self.assertEqual(report, [{'rysunek': 'Fig. 1', 'analysis_unchecked': True,
                                   'reason': axes._UNCHECKED['pl']}])

    def test_empty_readouts_return_unassessed_contract(self):
        report, _ = self.report(['YES', 'YES'], numbers=('NONE', 'NONE'))
        self.assertTrue(report[0]['analysis_unchecked'])
        self.assertNotIn('blad', report[0])

    def test_confirmed_error_contract(self):
        report, _ = self.report(['YES', 'YES'])
        self.assertEqual(set(report[0]), {'rysunek', 'blad'})

    def test_line_with_regular_ticks_has_no_error(self):
        report, _ = self.report(['NO', 'YES', 'YES'])
        self.assertEqual(report, [])

    def test_runtime_exception_is_failed(self):
        with self.assertLogs(axes.logger, level='ERROR'):
            report, _ = self.report([RuntimeError('inference failed')])
        self.assertEqual(report, [{'rysunek': 'Fig. 1', 'analysis_failed': True}])


if __name__ == '__main__':
    unittest.main()
