import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.redaction.redaction_validator import RedactionValidator

A4 = (595.28, 841.89)
A5 = (419.53, 595.28)


def _validator(page_format):
    errors = []
    return NS(config=NS(format=page_format), errors=errors, language="pl", module="redaction", _get_next_id=lambda: len(errors)), errors


def _document(*sizes):
    return NS(get_page_dimensions=lambda: {number: size for number, size in enumerate(sizes, 1)})


class PageFormatTest(unittest.TestCase):
    def test_a4_page_matches_uppercase_format(self):
        validator, errors = _validator("A4")
        with self.assertNoLogs(level="WARNING"):
            self.assertTrue(RedactionValidator.check_format(validator, _document(A4, A4)))
        self.assertEqual(errors, [])

    def test_lowercase_format_works_the_same(self):
        validator, errors = _validator("a4")
        self.assertTrue(RedactionValidator.check_format(validator, _document(A4)))
        self.assertEqual(errors, [])

    def test_landscape_a4_page_matches(self):
        validator, errors = _validator("A4")
        self.assertTrue(RedactionValidator.check_format(validator, _document(A4, A4[::-1])))
        self.assertEqual(errors, [])

    def test_page_of_another_size_is_reported(self):
        validator, errors = _validator("A4")
        self.assertFalse(RedactionValidator.check_format(validator, _document(A5)))
        self.assertEqual([e.page_number for e in errors], [1])
        self.assertIn("A4", errors[0].comments)

    def test_page_of_another_size_after_the_first_page_is_reported(self):
        validator, errors = _validator("A4")
        self.assertFalse(RedactionValidator.check_format(validator, _document(A4, A4, A5)))
        self.assertEqual([e.page_number for e in errors], [3])

    def test_unknown_format_is_only_logged(self):
        validator, errors = _validator("B5")
        with self.assertLogs(level="WARNING"):
            self.assertFalse(RedactionValidator.check_format(validator, _document(A4)))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
