'''
Testy sprawdzania literówek (typo_check) dla zapożyczeń z polską końcówką, np. "rankowania", "transformerowym".

Uruchomienie (z katalogu głównego repozytorium):
    .venv/bin/python -m unittest discover -s unit_tests -t . -v

Pozytyw = słowo jest literówką:
- TP/FN - literówki (także w zapożyczeniach) muszą zostać wykryte (typo_check zwraca False),
- TN/FP - poprawne słowa, w tym zapożyczenia z polską końcówką, nie mogą zostać wykryte (typo_check zwraca True).
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics.language_error_extractor import is_polish_inflected_loanword, typo_check  # noqa: E402


class TestTypoNotDetected(unittest.TestCase):
    '''Poprawne słowa - nie mogą zostać zgłoszone jako literówka.'''

    def test_loanwords_with_polish_endings(self):
        # Przypadki ze zgłoszenia: "do rankowania wyników", "na modelu transformerowym"
        for word in ("rankowania", "Rankowania", "transformerowym", "transformerowe", "frameworku", "frameworkach",
                     "embeddingów", "debugowania", "commitować", "deployować", "slotach", "mockowania"):
            with self.subTest(word=word):
                self.assertTrue(typo_check(word))

    def test_loanword_with_dropped_final_e(self):
        # "cache" -> "cachowania" - niema końcówka -e znika przy odmianie
        self.assertTrue(typo_check("cachowania"))

    def test_polish_and_english_words(self):
        for word in ("prezentacji", "wyszukiwania", "model", "transformer", "ranking", "framework"):
            with self.subTest(word=word):
                self.assertTrue(typo_check(word))

    def test_multi_word_match(self):
        self.assertTrue(typo_check("modelu transformerowym"))


class TestTypoDetected(unittest.TestCase):
    '''Literówki - muszą zostać zgłoszone.'''

    def test_typos_in_loanwords(self):
        for word in ("transfromerowym", "rankowsnia", "frameworkk", "embedingów"):
            with self.subTest(word=word):
                self.assertFalse(typo_check(word))

    def test_typo_with_polish_dictionary_stem(self):
        # "progam" jest w Morfeuszu (rzadka forma) - rdzenie sprawdzane są tylko w słowniku angielskim
        self.assertFalse(typo_check("progamowania"))

    def test_typo_with_rare_short_english_stem(self):
        # "prog" jest w słowniku angielskim, ale to rzadki skrót - 4-literowe rdzenie muszą być częste
        self.assertFalse(is_polish_inflected_loanword("progowania"))

    def test_short_stem_with_ending(self):
        # Rdzenie krótsze niż 4 litery nie są akceptowane ("the" + "owania")
        self.assertFalse(typo_check("theowania"))

    def test_polish_typos_and_nonsense(self):
        for word in ("kszałtowania", "dsfgh", "teha"):
            with self.subTest(word=word):
                self.assertFalse(typo_check(word))

    def test_multi_word_match_with_typo(self):
        self.assertFalse(typo_check("modelu transfromerowym"))


if __name__ == "__main__":
    unittest.main()
