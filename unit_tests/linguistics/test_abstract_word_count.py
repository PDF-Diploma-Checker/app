import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from analysis.modules.linguistics.abstract_word_count import count_abstract_words


def doc(*blocks):
    return NS(logical_blocks=[NS(type=kind, content=text) for kind, text in blocks])


class AbstractWordCountTest(unittest.TestCase):
    def test_polish_and_english_abstracts_until_keywords(self):
        document = doc(('heading', 'PRACA DYPLOMOWA'),
                       ('heading', 'STRESZCZENIE'), ('paragraph', 'W pracy przedstawiono algorytm (ang. Model Predictive Control, MPC).'),
                       ('paragraph', 'Zespół filtrów Kalmana dopasowuje się.'),
                       ('keywords', 'Słowa kluczowe: filtr Kalmana, sterowanie'),
                       ('heading', 'ABSTRACT'), ('paragraph', 'The thesis presents a decision-support algorithm.'),
                       ('acronyms', 'Keywords: Kalman filter'), ('heading', '1. WSTĘP'), ('paragraph', 'Tekst pracy.'))
        self.assertEqual(count_abstract_words(document), {'pl': 14, 'en': 6})

    def test_only_polish_abstract(self):
        document = doc(('heading', 'Streszczenie'), ('paragraph', 'Jedno dwa trzy.'),
                       ('heading', 'Dziedzina nauki i techniki, zgodnie z wymogami OECD:'), ('paragraph', 'Nauki inżynieryjne'))
        self.assertEqual(count_abstract_words(document), {'pl': 3})

    def test_stops_at_keywords_inside_the_same_block_and_at_field_of_science(self):
        document = doc(('heading', 'ABSTRACT'), ('paragraph', 'One two three. Fields of science: engineering'))
        self.assertEqual(count_abstract_words(document), {'en': 3})

    def test_next_heading_ends_an_abstract_without_keywords(self):
        document = doc(('heading', 'ABSTRACT'), ('paragraph', 'One two.'), ('heading', '1. Introduction'),
                       ('paragraph', 'Many more words here.'))
        self.assertEqual(count_abstract_words(document), {'en': 2})

    def test_no_abstract_and_abstract_inside_a_sentence(self):
        self.assertEqual(count_abstract_words(doc(('paragraph', 'abstract algebra is fun'))), {})
        self.assertEqual(count_abstract_words(doc()), {})


if __name__ == '__main__':
    unittest.main()
