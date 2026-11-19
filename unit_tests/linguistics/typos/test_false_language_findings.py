'''
LanguageTool findings that are wrong for a thesis: a missing comma between two sentences, the preposition rule on
"we/wy". The tools are replaced, no LanguageTool is started.
'''
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics import language_error_extractor as extractor  # noqa: E402
from unit_tests.linguistics.typos.test_sentence_wide_match import block, lt_match  # noqa: E402


class FalseLanguageFindingsTest(unittest.TestCase):
    def analyse(self, text, category, rule, part):
        polish = MagicMock()
        polish.check.side_effect = lambda checked: [lt_match(text, category, rule, part)] if checked == text else []
        with patch.object(extractor, "_TOOL_PL", polish), patch.object(extractor, "_TOOL_EN", MagicMock()), \
                patch.object(extractor, "_init_language_tools"), patch.object(extractor, "dropped"), \
                patch.object(extractor, "get_match_info", return_value=(1, 1, [], [], False)):
            return extractor.language_tool_analisys([block(text)])

    def test_comma_between_two_sentences_is_not_reported(self):
        text = "Próbki pobierane są z częstotliwością 3200 Hz. Na mikrokontrolerze zaimplementowano przetwarzanie."
        part = "są z częstotliwością 3200 Hz. Na mikrokontrolerze zaimplementowano"
        self.assertEqual(self.analyse(text, "PUNCTUATION", "ZDANIA_ZLOZONE", part), [])

    def test_comma_after_an_abbreviation_is_still_reported(self):
        text = "Układ np. Arduino zbiera dane wysyła je dalej."
        part = "zbiera dane wysyła"
        with patch.object(extractor, "predicative_adjective_reason", return_value=None):
            self.assertEqual(len(self.analyse(text, "PUNCTUATION", "ZDANIA_ZLOZONE", part)), 1)

    def test_inputs_outputs_abbreviation_is_not_a_preposition(self):
        text = "Piny we/wy mikrokontrolera ustawiono w trybie wyjścia."
        self.assertEqual(self.analyse(text, "PHONETICS", "WE_W", "we"), [])

    def test_preposition_we_is_still_checked(self):
        text = "Pracowano we firmie przez rok."
        self.assertEqual(len(self.analyse(text, "PHONETICS", "WE_W", "we")), 1)


if __name__ == "__main__":
    unittest.main()
