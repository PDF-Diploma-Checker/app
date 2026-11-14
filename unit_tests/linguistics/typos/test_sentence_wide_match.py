'''
Tests of a LanguageTool finding that covers a whole sentence. The tools are replaced, no LanguageTool is started.
'''
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics import language_error_extractor as extractor  # noqa: E402


def lt_match(text, category, rule, part=None):
    part = part or text
    return SimpleNamespace(category=category, rule_id=rule, matched_text=part, offset=text.index(part), error_length=len(part),
                           message="komunikat", replacements=[], sentence=text)


def block(sentence):
    return SimpleNamespace(block=SimpleNamespace(type="paragraph", block_id=1, language="pl"), contents=sentence, language="pl")


class SentenceWideMatchTest(unittest.TestCase):
    def analyse(self, sentence):
        polish, english = MagicMock(), MagicMock()
        polish.check.side_effect = lambda text: (
            [lt_match(sentence, "SYNTAX", "PCON_VERB")] if text == sentence else
            [lt_match(text, "TYPOS", "MORFOLOGIK_RULE_PL")] if text == "uwzgędniono" else [])
        english.check.side_effect = lambda text: [lt_match(text, "TYPOS", "MORFOLOGIK_RULE_EN_GB", word) for word in text.split()]
        with patch.object(extractor, "_TOOL_PL", polish), patch.object(extractor, "_TOOL_EN", english), \
                patch.object(extractor, "_init_language_tools"), patch.object(extractor, "dropped") as dropped, \
                patch.object(extractor, "get_match_info", return_value=(1, 1, [], [], False)):
            return extractor.language_tool_analisys([block(sentence)]), dropped

    def test_only_the_misspelled_word_is_reported(self):
        errors, _ = self.analyse("Badając silnik uwzgędniono jego stany")
        self.assertEqual([error.content for error in errors], ["uwzgędniono"])
        self.assertEqual(errors[0].category, "TYPOS")
        self.assertEqual(errors[0].rule, "MORFOLOGIK_RULE_PL")

    def test_the_finding_is_dropped_without_a_misspelled_word(self):
        errors, dropped = self.analyse("Badając silnik sprawdzono jego stany")
        self.assertEqual(errors, [])
        dropped.assert_called_once()

    def test_english_dictionary_cannot_invent_polish_typos_from_syntax(self):
        with patch.object(extractor, "typo_check", return_value=False):
            errors, dropped = self.analyse("Badając model sprawdzono amplitudy")
        self.assertEqual(errors, [])
        dropped.assert_called_once()

    def test_recovered_typo_keeps_absolute_offset_and_polish_rule(self):
        sentence = "Badając silnik uwzgędniono jego stany"
        errors, _ = self.analyse(sentence)
        self.assertEqual(errors[0].offset, sentence.index("uwzgędniono"))
        self.assertEqual(errors[0].error_length, len("uwzgędniono"))
        self.assertEqual(errors[0].rule, "MORFOLOGIK_RULE_PL")


if __name__ == "__main__":
    unittest.main()
