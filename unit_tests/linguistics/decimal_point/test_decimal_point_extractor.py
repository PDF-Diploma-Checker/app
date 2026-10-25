'''
Testy sprawdzania separatora dziesiętnego (decimal_point_extractor).

Uruchomienie (z katalogu głównego repozytorium):
    .venv/bin/python -m unittest discover -s unit_tests -t . -v

PDF-y w tym katalogu generuje generate_pdfs.py. Nazwy plików opisują oczekiwany wynik:
- fp_unnecessarily_detected_dot_* - żadna kropka nie powinna zostać zgłoszona,
- tp_correctly_detected_dot_* - wszystkie kropki-separatory muszą zostać zgłoszone.
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, WordInfo  # noqa: E402
from analysis.modules.linguistics.linguistics_types import Block_context  # noqa: E402
from analysis.modules.linguistics.decimal_point_extractor import decimal_check, is_reference_word  # noqa: E402
from unit_tests.utils_test import PDF_COMPILERS, pdf_to_blocks  # noqa: E402

PDF_DIR = Path(__file__).resolve().parent

CERTAIN_PL = "Niepoprawny separator dziesiętny."
POSSIBLE_PL = "Możliwe zastosowanie błędnego separatora dziesiętnego."


def make_paragraph(text, language="pl", document_language="pl", block_id=1):
    '''Builds a minimal paragraph block context, with words placed on page 2 (after title pages).
    language - language detected for the block, document_language - language of the whole thesis,
    set on each block by the pipeline (src/app/pipeline.py) and used for error messages.'''
    words = []
    position = 0
    for index, token in enumerate(text.split(" ")):
        words.append(WordInfo(
            word_index=index, text=token, start_char=position, end_char=position + len(token),
            font="Times", size=12.0, bold=False, italic=False,
            bbox=[float(position), 0.0, float(position + len(token)), 10.0], page_number=2,
        ))
        position += len(token) + 1
    block = ParagraphBlock(block_id=block_id, content=text, words=words)
    block.language = document_language
    return Block_context(contents=text, language=language, block=block)


def detected(text, chapter_nums=frozenset(), language="pl", document_language="pl"):
    blocks = [make_paragraph(text, language, document_language)]
    return {m.content: m.message for m in decimal_check(blocks, set(chapter_nums))}


class TestReferenceWord(unittest.TestCase):
    def test_inflected_forms_are_references(self):
        for word in ("podrozdziale", "podrozdział", "rozdziale", "rozdziałach", "sekcji", "punkcie",
                     "rysunku", "tabeli", "załączniku", "wersji", "równaniu", "section", "figure"):
            with self.subTest(word=word):
                self.assertTrue(is_reference_word(word))

    def test_similar_words_are_not_references(self):
        for word in ("rozmiar", "rozkład", "punktacja", "dodatkowo", "średnia", "wynosi", "tablet"):
            with self.subTest(word=word):
                self.assertFalse(is_reference_word(word))


class TestDotNotDetected(unittest.TestCase):
    '''Kropki niebędące separatorem dziesiętnym - nie mogą zostać zgłoszone (false positive).'''

    def test_subsection_reference_at_sentence_end(self):
        # Przypadek ze zgłoszenia: "w kolejnym podrozdziale 3.1." oznaczane jako DECIMAL
        self.assertEqual(detected("Omówienie znajduje się w kolejnym podrozdziale 3.1."), {})

    def test_references_to_numbered_elements(self):
        for text in ("Wyniki przedstawiono w sekcji 2.4 pracy.",
                     "Opisano to w punkcie 1.2 pracy.",
                     "Dane zebrano w tabeli 2.1 i 2.2 poniżej.",
                     "Kod umieszczono w załączniku 1.3 pracy.",
                     "Metodę z podrozdz. 4.2 zastosowano ponownie.",
                     "Biblioteka w wersji 3.12 została zaktualizowana."):
            with self.subTest(text=text):
                self.assertEqual(detected(text), {})

    def test_number_from_table_of_contents(self):
        self.assertEqual(detected("Szczegóły opisano w 3.1 poniżej.", chapter_nums={"3.1"}), {})

    def test_number_in_quotes(self):
        self.assertEqual(detected("Program wypisał „wynik 3.5” na ekranie."), {})

    def test_number_in_brackets(self):
        self.assertEqual(detected("Zgodnie z opisem (3.1) wartość jest stała."), {})

    def test_decimal_comma_in_polish_text(self):
        self.assertEqual(detected("Średnia wartość wyniosła 3,5 jednostki."), {})

    def test_multi_level_numbering(self):
        self.assertEqual(detected("Wartość 1.2.3 jest numerem wersji pakietu."), {})


class TestDotDetected(unittest.TestCase):
    '''Kropki użyte jako separator dziesiętny w polskim tekście - muszą zostać zgłoszone.'''

    def test_plain_decimal_dot(self):
        self.assertEqual(detected("Średnia wartość wyniosła 3.5 jednostki."), {"3.5": POSSIBLE_PL})

    def test_decimal_dot_with_unit_is_certain(self):
        self.assertEqual(detected("Cena wzrosła o 2.75% w ciągu roku."), {"2.75": CERTAIN_PL})
        self.assertEqual(detected("Produkt kosztuje 9.99 zł za sztukę."), {"9.99": CERTAIN_PL})

    def test_words_similar_to_reference_words(self):
        for text, number in (("Rozmiar to 4.2 metra.", "4.2"),
                             ("Dodatkowo 6.5 kilograma zużyto.", "6.5"),
                             ("Punktacja to 7.25 w skali.", "7.25")):
            with self.subTest(text=text):
                self.assertEqual(detected(text), {number: POSSIBLE_PL})

    def test_unit_wins_over_table_of_contents_number(self):
        self.assertEqual(detected("Kurs wynosi 3.1 zł obecnie.", chapter_nums={"3.1"}), {"3.1": CERTAIN_PL})

    def test_message_follows_document_language(self):
        # Komunikat ma być w języku całej pracy, nie w języku wykrytym dla akapitu
        self.assertEqual(detected("The average value was 3,5 units in total.", language="en", document_language="en"),
                         {"3,5": "Possible use of an incorrect decimal separator."})
        self.assertEqual(detected("The average value was 3,5 units in total.", language="en", document_language="pl"),
                         {"3,5": POSSIBLE_PL})
        self.assertEqual(detected("Średnia wartość wyniosła 3.5 jednostki.", language="pl", document_language="en"),
                         {"3.5": "Possible use of an incorrect decimal separator."})


class TestGeneratedPdfs(unittest.TestCase):
    '''Pełny przebieg ekstrakcja -> analiza na PDF-ach z różnych kompilatorów.'''

    @classmethod
    def setUpClass(cls):
        from analysis.modules.linguistics.helpers import extract_chapter_numbers

        def run(pdf_path):
            _, blocks = pdf_to_blocks(pdf_path)
            return {m.content: m.message for m in decimal_check(blocks, extract_chapter_numbers(blocks))}

        cls.run_pdf = staticmethod(run)

    def test_fp_unnecessarily_detected_dot(self):
        for compiler in PDF_COMPILERS:
            with self.subTest(compiler=compiler):
                self.assertEqual(self.run_pdf(PDF_DIR / f"fp_unnecessarily_detected_dot_{compiler}.pdf"), {})

    def test_tp_correctly_detected_dot(self):
        expected = {"3.5": POSSIBLE_PL, "2.75": CERTAIN_PL, "4.2": POSSIBLE_PL, "6.5": POSSIBLE_PL,
                    "7.25": POSSIBLE_PL}
        for compiler in PDF_COMPILERS:
            with self.subTest(compiler=compiler):
                self.assertEqual(self.run_pdf(PDF_DIR / f"tp_correctly_detected_dot_{compiler}.pdf"), expected)


if __name__ == "__main__":
    unittest.main()
