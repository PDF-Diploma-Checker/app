"""Bilingual acceptance must not replace a diagnosis with foreign spelling advice."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from analysis.modules.linguistics import language_error_extractor as extractor
from unit_tests.linguistics.typos.test_sentence_wide_match import block, lt_match


class BilingualFindingsTest(unittest.TestCase):
    def analyse(self, language, foreign_accepts=False):
        text = 'Wynik uwzgędniono.' if language == 'pl' else 'Result misspeled.'
        word = 'uwzgędniono' if language == 'pl' else 'misspeled'
        primary, foreign = MagicMock(), MagicMock()
        original = lt_match(text, 'TYPOS', 'PRIMARY_SPELLING', word)
        original.replacements = ['uwzględniono' if language == 'pl' else 'misspelled']
        primary.check.return_value = [original]
        foreign.check.return_value = [] if foreign_accepts else [lt_match(word, 'TYPOS', 'FOREIGN_SPELLING')]
        item = block(text)
        item.language = item.block.language = language
        pl, en = (primary, foreign) if language == 'pl' else (foreign, primary)
        with patch.object(extractor, '_TOOL_PL', pl), patch.object(extractor, '_TOOL_EN', en), \
                patch.object(extractor, '_init_language_tools'), patch.object(extractor, 'typo_check', return_value=False), \
                patch.object(extractor, 'get_match_info', return_value=(1, 1, [], [], False)):
            return extractor.language_tool_analisys([item]), original

    def test_original_rule_suggestions_and_span_survive_bilingual_rejection(self):
        for language in ('pl', 'en'):
            with self.subTest(language=language):
                errors, original = self.analyse(language)
                self.assertEqual(len(errors), 1)
                error = errors[0]
                self.assertEqual(error.rule, original.rule_id)
                self.assertEqual(error.content, original.matched_text)
                self.assertEqual(error.offset, original.offset)
                self.assertIn(original.replacements[0], error.why)
                self.assertNotIn('FOREIGN_SPELLING', error.why)

    def test_intentional_foreign_word_is_still_accepted(self):
        for language in ('pl', 'en'):
            with self.subTest(language=language):
                self.assertEqual(self.analyse(language, foreign_accepts=True)[0], [])
