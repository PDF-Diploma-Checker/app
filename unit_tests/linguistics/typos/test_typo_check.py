'''
Testy sprawdzania literówek (typo_check) dla zapożyczeń z polską końcówką, np. "rankowania", "transformerowym".

Uruchomienie (z katalogu głównego repozytorium):
    .venv/bin/python -m unittest discover -s unit_tests -t . -v

Pozytyw = słowo jest literówką:
- TP/FN - literówki (także w zapożyczeniach) muszą zostać wykryte (typo_check zwraca False),
- TN/FP - poprawne słowa, w tym zapożyczenia z polską końcówką, nie mogą zostać wykryte (typo_check zwraca True).

Testy filtra reguły LT "ZDANIA_ZLOZONE" (predicative_adjective_reason), bez uruchamiania LanguageTool:
- przymiotnik po łączniku ("pozostaje ona stała i równa") nie jest drugim czasownikiem - trafienie odrzucone,
- czasownik w czasie przeszłym ("wróciłem ona stała i czekała") - trafienie zostaje.
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics.language_error_extractor import ( 
    is_adjective_verb_homograph, is_polish_inflected_loanword, predicative_adjective_reason, typo_check
)


def compound_sentence_reason(sentence, span, first, second):
    '''Runs the ZDANIA_ZLOZONE filter on a match covering span, with the message LanguageTool gives for this rule.'''
    message = (f"W tym zdaniu złożonym brakuje przecinka lub spójnika między jednym czasownikiem („{first}”) "
               f"a drugim („{second}”).")
    return predicative_adjective_reason(message, sentence, sentence.index(span), len(span))


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


class TestAdjectiveVerbHomograph(unittest.TestCase):

    def test_homographs(self):
        for word in ("stała", "Stała", "trwała", "dojrzała", "stały"):
            with self.subTest(word=word):
                self.assertTrue(is_adjective_verb_homograph(word))

    def test_not_homographs(self):
        for word in ("czekała", "patrzyła", "równa", "niezależna"):
            with self.subTest(word=word):
                self.assertFalse(is_adjective_verb_homograph(word))


class TestCompoundSentenceDropped(unittest.TestCase):
    '''Przymiotnik po łączniku - LT uznaje go za drugi czasownik, trafienie musi zostać odrzucone.'''

    def test_adjective_after_copula_with_pronoun(self):
        # Przypadek ze zgłoszenia: dezambiguator LT po "ona" zostawia tylko odczytanie "stać"
        sentence = ("Rząd modelu określa przy tym charakter prognozy: dla R = 1 pozostaje ona stała i równa "
                    "ostatniemu oszacowaniu ceny bazowej, a dla R = 2 przedłuża ostatni oszacowany trend liniowy.")
        self.assertIsNotNone(compound_sentence_reason(sentence, "pozostaje ona stała i", "pozostaje", "stała"))

    def test_adjective_after_copula(self):
        for sentence in ("Po kalibracji pozostaje ona stała i niezależna od temperatury.",
                         "Wartość progowa pozostaje ona stała i równa zeru."):
            with self.subTest(sentence=sentence):
                self.assertIsNotNone(compound_sentence_reason(sentence, "pozostaje ona stała i", "pozostaje", "stała"))

    def test_coordinated_adjectives(self):
        sentence = "Po kilku iteracjach okazuje się ona trwała i odporna na zakłócenia."
        self.assertIsNotNone(compound_sentence_reason(sentence, "okazuje się ona trwała i", "okazuje", "trwała"))


class TestCompoundSentenceKept(unittest.TestCase):
    '''Rzeczywisty brak przecinka - trafienie musi zostać.'''

    def test_homograph_used_as_verb(self):
        for sentence, span, first in (
            ("Gdy wróciłem ona stała i czekała przy drzwiach.", "wróciłem ona stała i", "wróciłem"),
            ("Kiedy przyszedłem ona stała i patrzyła w okno.", "przyszedłem ona stała i", "przyszedłem"),
            ("Gdy go zobaczyła ona stała i milczała.", "zobaczyła ona stała i", "zobaczyła"),
            ("Kiedy weszliśmy ona stała przy oknie i płakała.", "weszliśmy ona stała przy oknie i", "weszliśmy"),
            ("Kiedy dziecko płakało ona stała i nic nie robiła.", "płakało ona stała i", "płakało"),
        ):
            with self.subTest(sentence=sentence):
                self.assertIsNone(compound_sentence_reason(sentence, span, first, "stała"))

    def test_second_verb_not_homograph(self):
        sentence = "Gdy ona stała i patrzyła przyszedł autobus."
        self.assertIsNone(compound_sentence_reason(sentence, "patrzyła przyszedł autobus.", "patrzyła", "przyszedł"))

    def test_message_without_verbs(self):
        sentence = "Po kalibracji pozostaje ona stała i niezależna od temperatury."
        self.assertIsNone(predicative_adjective_reason("Błąd interpunkcyjny.", sentence, 14, 21))


if __name__ == "__main__":
    unittest.main()
