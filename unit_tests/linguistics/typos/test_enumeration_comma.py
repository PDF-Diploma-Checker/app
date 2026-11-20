'''
Testy filtra przecinka w wyliczeniu (removed_enumeration_comma), bez uruchamiania LanguageTool.

Uruchomienie (z katalogu app/):
    ..\\.venv\\Scripts\\python.exe -m unittest unit_tests.linguistics.typos.test_enumeration_comma -v

LanguageTool (np. reguła POZA_TYM) proponuje usunięcie przecinka po "Dla ...", "Dzięki ..." na początku zdania.
Pozytyw = przecinek naprawdę jest zbędny (trafienie LT zostaje):
- TN/FP - przecinek rozdziela elementy wyliczenia "coś, coś, ... i/lub/oraz coś" - trafienie odrzucone,
- TP/FN - przecinek po wtrąceniu na początku zdania - trafienie zostaje.
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics.language_error_extractor import removed_enumeration_comma


def lt_comma_match(sentence, span):
    '''Runs the filter on a match covering span, with the LanguageTool suggestion that removes the comma in it.'''
    offset = sentence.index(span)
    comma = span.index(",")
    suggestion = span[:comma] + span[comma + 1:]
    return removed_enumeration_comma(sentence, offset, len(span), [suggestion])


class TestEnumerationCommaDropped(unittest.TestCase):
    '''TN/FP - comma between items of an enumeration, the LanguageTool match is dropped.'''

    def test_letters_with_i(self):
        self.assertTrue(lt_comma_match("Dla 30% budżetu wyniki wariantów B, C i D uległy wyraźnemu zbliżeniu.",
                                       "Dla 30% budżetu wyniki wariantów B, C"))

    def test_acronyms_with_oraz(self):
        self.assertTrue(lt_comma_match("Dla sieci LSTM, GRU oraz CNN uzyskano podobne wyniki.",
                                       "Dla sieci LSTM, GRU"))

    def test_nouns_with_lub(self):
        self.assertTrue(lt_comma_match("Dzięki precyzji, czułości lub swoistości można ocenić model.",
                                       "Dzięki precyzji, czułości"))

    def test_multiword_items_with_i_lub(self):
        self.assertTrue(lt_comma_match(
            "Dla modelu liniowego, drzewa decyzyjnego i/lub lasu losowego dobrano parametry.",
            "Dla modelu liniowego, drzewa decyzyjnego"))

    def test_longer_enumeration(self):
        self.assertTrue(lt_comma_match("Poza metodą A, metodą B, metodą C albo metodą D nic nie działało.",
                                       "Poza metodą A, metodą B"))


class TestIntroductoryCommaKept(unittest.TestCase):
    '''TP/FN - comma after an introductory phrase, the LanguageTool match stays.'''

    def test_comma_after_introductory_phrase(self):
        self.assertFalse(lt_comma_match("Dla 30% budżetu, wyniki wariantów B i D uległy wyraźnemu zbliżeniu.",
                                        "Dla 30% budżetu, wyniki"))

    def test_clause_with_verb_after_comma(self):
        self.assertFalse(lt_comma_match("Dla mnie, to jest ważne i ciekawe.", "Dla mnie, to"))

    def test_no_connector(self):
        self.assertFalse(lt_comma_match("Dzięki temu, wyniki uległy zbliżeniu.", "Dzięki temu, wyniki"))

    def test_connector_in_next_sentence(self):
        self.assertFalse(lt_comma_match("Dla wariantu B, C. I D uległ zmianie.", "Dla wariantu B, C"))

    def test_suggestion_does_not_remove_comma(self):
        sentence = "Dla 30% budżetu wyniki wariantów B, C i D uległy wyraźnemu zbliżeniu."
        span = "wariantów B, C"
        self.assertFalse(removed_enumeration_comma(sentence, sentence.index(span), len(span), ["wariantów B; C"]))


if __name__ == "__main__":
    unittest.main()
