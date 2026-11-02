'''
Tests for detecting sentences without a subject or a verb (sentence_check.py).

Checks that:
- merge_abbreviation_splits joins sentences cut by spaCy after an initial or abbreviation ("m.in. A. Staniszewski",
  "w 2019 r. Komisja"), but not after a variable or unit ending a sentence ("grupy G.", "220 °C."),
- sentences without a verb are flagged as NO_VERB and impersonal sentences ("można", also before a colon) as NO_SUBJECT,
- correct sentences are not flagged: past tense with implicit subject, copula "to", verbs tagged by spaCy as
  a proper noun, introductions to a list ending with a colon, fragments without end punctuation and captions,
- TestGeneratedPdfs verifies full pipeline run (extraction -> analysis) on test PDFs
  built by different LaTeX compilers (pdflatex, xelatex, lualatex).

Run:
    uv run python -m unittest unit_tests/linguistics/sentence_check/test_sentence_check.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, WordInfo
from analysis.modules.linguistics.helpers import nlp_pl
from analysis.modules.linguistics.linguistics_types import Block_context
from analysis.modules.linguistics.sentence_check import merge_abbreviation_splits, sentence_check
from unit_tests.utils_generate_pdfs import LATEX_COMPILERS
from unit_tests.utils_test import pdf_to_blocks

PDF_DIR = Path(__file__).resolve().parent


def make_words(content, page=1):
    words = []
    pos = 0
    for i, text in enumerate(content.split(" ")):
        words.append(WordInfo(
            word_index=i, text=text, start_char=pos, end_char=pos + len(text),
            font="Arial", size=10.0, bold=False, italic=False,
            bbox=[10.0 * i, 100.0, 10.0 * i + 8, 112.0], page_number=page
        ))
        pos += len(text) + 1
    return words


def make_block(content, block_id=1, language="pl"):
    p = ParagraphBlock(block_id=block_id, content=content, words=make_words(content))
    p.language = language
    return Block_context(contents=content, language=language, block=p)


def check(content, language="pl"):
    '''Runs sentence_check on a single paragraph and returns categories of NO_SUBJECT / NO_VERB matches.'''
    matches, _ = sentence_check([make_block(content, language=language)], chapter_nums=set())
    return [m.category for m in matches if m.category in ("NO_SUBJECT", "NO_VERB")]


class TestAbbreviationSplits(unittest.TestCase):

    def split(self, text):
        return [s.text for s in merge_abbreviation_splits(nlp_pl(text).sents)]

    def test_initials_before_surname_merged(self):
        for text in ("Pracę tę wspierali m.in. A. Staniszewski i B. Gruchelski oraz J. Nowak.",
                     "Według F. Kotlera marka jest najważniejszym zasobem przedsiębiorstwa.",
                     "Model opisany w pracy K. Dośpiał-Borysiak został rozszerzony o nowe warstwy."):
            with self.subTest(text=text):
                self.assertEqual(self.split(text), [text])

    def test_abbreviations_merged(self):
        for text in ("W 2019 r. Komisja Europejska ogłosiła nowy plan działań.",
                     "Zespół ds. jakości przygotował raport końcowy z badań."):
            with self.subTest(text=text):
                self.assertEqual(self.split(text), [text])

    def test_sentence_end_not_merged(self):
        # Variables and units at the end of a sentence look like initials
        for text in ("Niech x należy do grupy G. Mówimy, że x jest sprzężone.",
                     "Temperatura wynosiła 220 °C. Próbki wysuszono."):
            with self.subTest(text=text):
                self.assertEqual(len(self.split(text)), 2)


class TestSentenceCheck(unittest.TestCase):

    def test_missing_verb_detected(self):
        self.assertEqual(check("Najbardziej popularny model emocji opracowany przez Paula Ekmana."), ["NO_SUBJECT", "NO_VERB"])
        self.assertEqual(check("Wpływ temperatury dyszy na średnią rezystancję próbek."), ["NO_VERB"])

    def test_impersonal_sentence_detected(self):
        # Impersonal sentences are reported on purpose, also when they introduce a list
        self.assertEqual(check("W przyszłości można spodziewać się dalszego wzrostu liczby użytkowników."), ["NO_SUBJECT"])
        self.assertEqual(check("Można wyróżnić następujące rodzaje modulacji sygnału:"), ["NO_SUBJECT"])

    def test_correct_sentences_not_detected(self):
        for text in ("Model przetestowano na nowym zbiorze danych. Wykazał też słabą zdolność adaptacji do zmian oświetlenia.",
                     "Ból to subiektywne doświadczenie zmysłowe i emocjonalne.",
                     "Zakotwicza on się w strukturze materiału kompozytowego.",
                     "Pracę tę wspierali m.in. A. Staniszewski i B. Gruchelski oraz J. Nowak.",
                     "Podczas walidacji i testów augmentacja nie była wykorzystywana.",
                     # spaCy does not mark "wartości" as the subject, the finite form "były" decides
                     "Ze względu na odmienny zakres przewidywań wartości straty w obu zadaniach nie były bezpośrednio porównywane."):
            with self.subTest(text=text):
                self.assertEqual(check(text), [])

    def test_colon_introduction_not_detected(self):
        self.assertEqual(check("W każdej kolejnej iteracji algorytmu:"), [])

    def test_missing_end_punctuation_not_detected(self):
        # Headings and blocks cut at the end of a page are not sentences
        self.assertEqual(check("Wpływ temperatury dyszy na średnią rezystancję próbek"), [])

    def test_captions_not_detected(self):
        for text in ("Rys. 2.1 Schemat stanowiska pomiarowego z zaznaczonymi czujnikami.",
                     "Rys. 1.7. Schematyczne przedstawienie struktury materiału kompozytowego.",
                     "Źródło: opracowanie własne na podstawie danych GUS."):
            with self.subTest(text=text):
                self.assertEqual(check(text), [])

    def test_english_message(self):
        matches, _ = sentence_check([make_block("The results of the second experiment with the new dataset.", language="en")], set())
        self.assertEqual([m.message for m in matches], ["No subject in the sentence.", "No verb in the sentence."])


class TestGeneratedPdfs(unittest.TestCase):
    '''Full run extraction -> sentence_check on PDFs built by different compilers.'''

    @classmethod
    def setUpClass(cls):
        def run(pdf_path):
            _, blocks = pdf_to_blocks(pdf_path)
            matches, _ = sentence_check(blocks, set())
            return [(m.category, m.content) for m in matches if m.category in ("NO_SUBJECT", "NO_VERB")]

        cls.run_pdf = staticmethod(run)

    def test_tp_missing_subject_or_verb(self):
        expected = [
            ("NO_SUBJECT", "Najbardziej popularny model emocji opracowany przez Paula Ekmana."),
            ("NO_VERB", "Najbardziej popularny model emocji opracowany przez Paula Ekmana."),
            ("NO_SUBJECT", "W przyszłości można spodziewać się dalszego wzrostu liczby użytkowników."),
            ("NO_VERB", "Wpływ temperatury dyszy na średnią rezystancję próbek."),
        ]
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                self.assertEqual(self.run_pdf(PDF_DIR / f"tp_missing_subject_or_verb_{compiler}.pdf"), expected)

    def test_fp_correct_sentences(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                self.assertEqual(self.run_pdf(PDF_DIR / f"fp_correct_sentences_{compiler}.pdf"), [])


if __name__ == "__main__":
    unittest.main()
