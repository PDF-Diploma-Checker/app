"""The option of the analysis dialog: is a last line of two words still a widow, or only a single word."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.redaction import redaction_validator as rv  # noqa: E402


def validator(max_words, blocks):
    v = rv.RedactionValidator.__new__(rv.RedactionValidator)
    v.widow_max_words = max_words
    v.document_data_linguistics = SimpleNamespace(logical_blocks=blocks)
    v.errors = []
    v.reported = []
    v._handle_widow = lambda block, words: v.reported.append(words) or None
    return v


BLOCKS = [SimpleNamespace(type="paragraph", is_widow=1), SimpleNamespace(type="paragraph", is_widow=2),
          SimpleNamespace(type="list", items=[SimpleNamespace(is_widow=2), SimpleNamespace(is_widow=1)])]


class WidowOptionTest(unittest.TestCase):
    def test_by_default_one_and_two_words_are_widows(self):
        v = validator(2, BLOCKS)
        v.check_widows()
        self.assertEqual(v.reported, [1, 2, 2, 1])

    def test_only_a_single_word_when_chosen(self):
        v = validator(1, BLOCKS)
        v.check_widows()
        self.assertEqual(v.reported, [1, 1])

    def test_the_setting_is_read_from_the_app_config(self):
        from analysis.modules.llm import config
        with mock.patch.object(config, "load_config", return_value={"widow_max_words": 1}):
            self.assertEqual(rv.widow_max_words_setting(), 1)
        with mock.patch.object(config, "load_config", return_value={}):
            self.assertEqual(rv.widow_max_words_setting(), 2)


if __name__ == "__main__":
    unittest.main()
