"""Deterministic chart evidence checks; no model or GPU libraries required."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from analysis.modules.llm.image_analysis.consistency_checker import (
    _numbers, values_are_printed, verdict_from_answer,
)


class ConsistencyEvidenceTest(unittest.TestCase):
    def verdict(self, text, image, paragraph=None, data=None, printed=None, element='A'):
        mismatch = dict(element=element, w_tekscie=text, na_rysunku=image,
                        text_quote=paragraph, image_quote=data)
        return verdict_from_answer({'niezgodnosci': [mismatch]}, paragraph=paragraph,
                                   image_data=data, printed=printed)['poprawnosc_danych']

    def test_signed_values(self):
        self.assertEqual(_numbers('−0,81 -5000 +2'), [(-.81, 2), (-5000, 0), (2, 0)])
        self.assertEqual(self.verdict('-0.81', '0.81'), 'False')
        self.assertEqual(self.verdict('−0.81', '-0.810'), 'True')
        self.assertEqual(self.verdict('-5000', '-5,000'), 'True')

    def test_printed_evidence_preserves_sign(self):
        self.assertEqual(self.verdict('-0.7', '-0.8', printed=[-.8]), 'False')
        self.assertEqual(self.verdict('-0.7', '-0.8', printed=[.8]), 'Unreadable')
        self.assertTrue(values_are_printed('A: -0.8', [-.8]))
        self.assertFalse(values_are_printed('A: -0.8', [.8]))

    def test_ratios_are_not_counts(self):
        for text, image in [('37/80', '35'), ('35', '37/80')]:
            self.assertEqual(self.verdict(text, image), 'Unreadable')

    def test_explicit_unit_conversions(self):
        for text, image in [('0.81 fraction', '81%'), ('81%', '0.81 proportion'),
                            ('1000 ms', '1 s'), ('1.5 GB', '1500 MB')]:
            self.assertEqual(self.verdict(text, image), 'True', (text, image))
        for text, image in [('0.81 fraction', '80%'), ('1100 ms', '1 s'), ('300 ms', '300 s')]:
            self.assertEqual(self.verdict(text, image), 'False', (text, image))

    def test_bare_percentage_conversion_is_ambiguous(self):
        for text, image in [('0.81', '81%'), ('81%', '0.81'),
                            ('0.81', '80%'), ('81', '81%')]:
            self.assertEqual(self.verdict(text, image), 'Unreadable')

    def test_ascii_and_en_dash_intervals_preserve_endpoints(self):
        for interval in ['0.4-0.6', '0.4 -0.6', '0.4 - 0.6', '0.4–0.6']:
            with self.subTest(interval=interval):
                self.assertEqual(_numbers(interval), [(0.4, 1), (0.6, 1)])
                self.assertEqual(self.verdict(interval, '0.5'), 'True')
                self.assertEqual(self.verdict(interval, '-0.5'), 'False')
                self.assertEqual(self.verdict(interval, '0.7'), 'False')
                self.assertEqual(self.verdict(interval, '0.7', f'A: {interval}', 'A: 0.7'), 'False')
        for interval in ['-0.6--0.4', '-0.6 - -0.4', '-0.6–-0.4', '−0.6–−0.4']:
            with self.subTest(interval=interval):
                self.assertEqual(_numbers(interval), [(-0.6, 1), (-0.4, 1)])
                self.assertEqual(self.verdict(interval, '-0.5'), 'True')
                self.assertEqual(self.verdict(interval, '0.5'), 'False')
                self.assertEqual(self.verdict(interval, '-0.7'), 'False')
                self.assertEqual(self.verdict(interval, '-0.7', f'A: {interval}', 'A: -0.7'), 'False')
        self.assertEqual(self.verdict('-0.4-0.6', '0'), 'True')

    def test_rounding_requires_decimal_precision(self):
        for text, image in [('0.81', '0'), ('0.4', '0'), ('1', '1.4'), ('0.81', '0.82')]:
            self.assertEqual(self.verdict(text, image), 'False', (text, image))
        self.assertEqual(self.verdict('0.989', '1.0'), 'True')
        self.assertEqual(self.verdict('0.4–0.6', '0.5'), 'True')
        self.assertEqual(self.verdict('0.4–0.6 s', '0.5 ms'), 'False')

    def test_fabricated_zero_and_wrong_sign_are_unverified(self):
        self.assertEqual(self.verdict('0.81', '0', 'A: 0.81', 'A: 0.8'), 'Unreadable')
        self.assertEqual(self.verdict('-0.81', '0.8', 'A: 0.81', 'A: 0.8'), 'Unreadable')

    def test_borrowed_values_from_other_items_or_series(self):
        for data in ['A: 40; B: 70', 'A: 40\nB: 70', 'A: 40, B: 70',
                     'A training: 40, validation: 70', 'BA: 70']:
            self.assertEqual(self.verdict('50', '70', 'A: 50', data), 'Unreadable', data)
        self.assertEqual(self.verdict('50', '70', 'B: 50', 'A: 70'), 'Unreadable')

    def test_grounded_errors_survive(self):
        self.assertEqual(self.verdict('40 ms', '70 ms', 'gzip: 40 ms',
                                     'gzip: 70 ms', [70], 'gzip'), 'False')
        self.assertEqual(self.verdict('40', '70', 'S1: 40', 'S1: 70', [70], 'S1'), 'False')
        self.assertEqual(self.verdict('40', '70', 'A: 40', 'A: 70; B: 40', [70]), 'False')

    def test_literal_quotes_cannot_truncate_a_number_or_item(self):
        for data, quote in [('A: 0.81', 'A: 0'), ('BA: 0', 'A: 0'),
                            ('A: -0.81', 'A: -0')]:
            mismatch = dict(element='A', w_tekscie='1', na_rysunku='0',
                            text_quote='A: 1', image_quote=quote)
            result = verdict_from_answer({'niezgodnosci': [mismatch]},
                                         paragraph='A: 1', image_data=data)
            self.assertEqual(result['poprawnosc_danych'], 'Unreadable')

    def test_units_cannot_be_invented_in_quotes(self):
        self.assertEqual(self.verdict('40 s', '70 ms', 'A: 40 ms', 'A: 70 ms'), 'Unreadable')


if __name__ == '__main__':
    unittest.main()
