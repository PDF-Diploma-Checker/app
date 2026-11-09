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

from analysis.extraction.linguistics_conversion.schema import ListBlock, ListItem, ParagraphBlock, WordInfo  # noqa: E402
from analysis.modules.linguistics.linguistics_types import Block_context  # noqa: E402
from analysis.extraction.linguistics_conversion.schema import PageArtifact, VisualElement  # noqa: E402
from analysis.modules.linguistics.decimal_point_extractor import (  # noqa: E402
    decimal_check, decimal_check_in_figures, follows_name, is_reference_word)
from unit_tests.utils_test import PDF_COMPILERS, pdf_to_blocks  # noqa: E402

PDF_DIR = Path(__file__).resolve().parent

CERTAIN_PL = "Niepoprawny separator dziesiętny."
POSSIBLE_PL = "Możliwe zastosowanie błędnego separatora dziesiętnego."
CERTAIN_EN = "Wrong decimal separator."
POSSIBLE_EN = "Possible use of an incorrect decimal separator."
BLACK_LIST = {"%", "$", "€", "£", "zł", "usd", "eur", "gbp", "°"}


def make_words(text, bold_words=(), italic_words=()):
    '''Words of the text split on spaces, placed on page 2 (after title pages).
    bold_words / italic_words - indexes of words written in bold / italics.'''
    words = []
    position = 0
    for index, token in enumerate(text.split(" ")):
        words.append(WordInfo(
            word_index=index, text=token, start_char=position, end_char=position + len(token),
            font="Times", size=12.0, bold=index in bold_words, italic=index in italic_words,
            bbox=[float(position), 0.0, float(position + len(token)), 10.0], page_number=2,
        ))
        position += len(token) + 1
    return words


def make_paragraph(text, language="pl", document_language="pl", block_id=1, block_type="paragraph",
                   bold_words=(), italic_words=()):
    '''Builds a minimal paragraph block context.
    language - language detected for the block, document_language - language of the whole thesis,
    set on each block by the pipeline (src/app/pipeline.py) and used for error messages.'''
    block = ParagraphBlock(block_id=block_id, content=text, type=block_type,
                           words=make_words(text, bold_words, italic_words))
    block.language = document_language
    return Block_context(contents=text, language=language, block=block)


def make_list(text, is_bibliography=False, block_id=1):
    '''Builds a list block context with a single item holding the whole text.'''
    words = make_words(text)
    item = ListItem(item_id=0, marker_type="bullet", text=text, bbox=[0.0, 0.0, 100.0, 10.0], words=words)
    block = ListBlock(block_id=block_id, content=text, bbox=[0.0, 0.0, 100.0, 10.0],
                      is_bibliography=is_bibliography, items=[item], words=words)
    return Block_context(contents=text, language="pl", block=block)


def run_blocks(blocks, chapter_nums=frozenset()):
    return {m.content: m.message for m in decimal_check(blocks, set(chapter_nums))}


def detected(text, chapter_nums=frozenset(), language="pl", document_language="pl", **block_kwargs):
    return run_blocks([make_paragraph(text, language, document_language, **block_kwargs)], chapter_nums)


class TestReferenceWord(unittest.TestCase):
    def test_inflected_forms_are_references(self):
        for word in ("podrozdziale", "podrozdział", "rozdziale", "rozdziałach", "sekcji", "punkcie",
                     "rysunku", "tabeli", "załączniku", "wersji", "równaniu", "section", "figure",
                     "schemacie", "schematu", "grafice", "grafika", "grafiki"):
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
                     "Biblioteka w wersji 3.12 została zaktualizowana.",
                     # Przypadki ze zgłoszenia: odwołania do rysunków przez "schemacie" i "grafice"
                     "Proces opisano na schemacie 2.4 poniżej.",
                     "Okno przedstawiono na grafice 5.2."):
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

    def test_version_after_acronym_or_name(self):
        # Przypadek ze zgłoszenia: "WCAG 2.0" oznaczane jako DECIMAL
        for text in ("Wytyczne WCAG 2.0 lub wyższe opracowano w W3C.",
                     "Standard (WCAG 2.1) obowiązuje od dawna.",
                     "Porty USB 3.0 są szybsze.",
                     "Skrypt napisano w języku Python 3.12 bez zmian.",
                     "Aplikacja działa na iOS 17.1 i nowszych."):
            with self.subTest(text=text):
                self.assertEqual(detected(text), {})


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

    def test_capitalised_word_at_sentence_start_is_not_a_name(self):
        self.assertEqual(detected("Wynik był dobry. Średnio 3.5 punktu."), {"3.5": POSSIBLE_PL})

    def test_currency_code_before_number_is_not_a_name(self):
        self.assertEqual(detected("Kosztuje to EUR 3.5 za sztukę."), {"3.5": POSSIBLE_PL})

    def test_unit_wins_over_table_of_contents_number(self):
        self.assertEqual(detected("Kurs wynosi 3.1 zł obecnie.", chapter_nums={"3.1"}), {"3.1": CERTAIN_PL})

    def test_message_follows_document_language(self):
        self.assertEqual(detected("The average value was 3,5 units in total.", language="en", document_language="en"),
                         {"3,5": "Possible use of an incorrect decimal separator."})
        self.assertEqual(detected("Średnia wartość wyniosła 3.5 jednostki.", language="pl", document_language="pl"),
                         {"3.5": POSSIBLE_PL})

    def test_rules_follow_document_language(self):
        # Detektor myli polskie bloki (nagłówki, podpisy) z angielskimi - zawsze obowiązują zasady języka pracy
        self.assertEqual(detected("Pomiar UART wynosi 3.5 ms tutaj.", language="en", document_language="pl"),
                         {"3.5": POSSIBLE_PL})
        self.assertEqual(detected("Pomiar UART wynosi 3,5 ms tutaj.", language="en", document_language="pl"), {})
        self.assertEqual(detected("The measured delay was 3.5 ms here.", language="pl", document_language="en"), {})
        self.assertEqual(detected("The measured delay was 3,5 ms here.", language="pl", document_language="en"),
                         {"3,5": "Possible use of an incorrect decimal separator."})


class TestFollowsName(unittest.TestCase):
    '''follows_name - czy liczba stoi bezpośrednio po akronimie/nazwie (wersja, oznaczenie standardu).'''

    def test_names_and_acronyms(self):
        for before in ("Wytyczne WCAG", "porty USB", "w języku Python", "działa na iOS", "pakiet macOS",
                       "Standard (WCAG", "cytat „Python", "Wersja A"):
            with self.subTest(before=before):
                self.assertTrue(follows_name(before, BLACK_LIST))

    def test_not_names(self):
        for before in ("",                       # liczba na początku tekstu
                       "wartość (",              # ostatni znak nie jest literą/cyfrą
                       "Wynik wyniósł:",
                       "średnia wynosi",         # zwykłe słowo małą literą
                       "Python",                 # wielka litera na początku tekstu
                       "Był dobry. Średnio",     # wielka litera na początku zdania
                       "Czy tak? Około",
                       "Uwaga! Około",
                       "kosztuje EUR",           # kod waluty z czarnej listy
                       "kosztuje USD",
                       "w roku 2024",            # brak liter
                       "zmienna x2"):            # jedna mała litera
            with self.subTest(before=before):
                self.assertFalse(follows_name(before, BLACK_LIST))


class TestDecimalRegex(unittest.TestCase):
    '''Które zapisy liczb są w ogóle kandydatami (regex dla tekstu polskiego i angielskiego).'''

    def test_polish_candidates(self):
        for text, expected in (("Średnia wyniosła 3.5 jednostki.", {"3.5"}),
                               ("Średnia wyniosła 0.75 jednostki.", {"0.75"}),
                               ("Średnia wyniosła 123.456 jednostki.", {"123.456"}),
                               ("Wynik końcowy wyniósł 1.5.", {"1.5"}),          # kropka kończąca zdanie
                               ("Wyniki to 3.5 i 4.5 punktu.", {"3.5", "4.5"}),  # kilka liczb w bloku
                               ("Wynik to 35 punktów.", set()),                  # liczba całkowita
                               ("Wartość .5 jest mała.", set()),                 # brak części całkowitej
                               ("Wartość 1.2.3 jest numerem.", set()),           # numeracja wielopoziomowa
                               ("Wartość 1.2.3.4 jest numerem.", set()),
                               ("Używamy v1.5 biblioteki.", set()),              # litera przed liczbą
                               ("Średnia wyniosła 3,5 jednostki.", set())):      # przecinek jest poprawny
            with self.subTest(text=text):
                self.assertEqual(set(detected(text)), expected)

    def test_english_candidates(self):
        for text, expected in (("The average was 3,5 units.", {"3,5"}),
                               ("The average was 0,25 units.", {"0,25"}),
                               ("The ratio was 1,0000 units.", {"1,0000"}),      # 4 cyfry - nie tysiące
                               ("The ratio was 1,25 units.", {"1,25"}),
                               ("There were 1,000 users.", set()),               # separator tysięcy
                               ("There were 1,000,000 users.", set()),
                               ("The average was 3.5 units.", set())):           # kropka jest poprawna
            with self.subTest(text=text):
                self.assertEqual(set(detected(text, language="en", document_language="en")), expected)


class TestSkippedBlocks(unittest.TestCase):
    '''Bloki, których nie sprawdzamy w ogóle - nawet pewny błąd nie może zostać zgłoszony.'''

    def test_skipped_block_types(self):
        for block_type in ("math", "code_snippet", "toc", "tot", "tof", "acronyms"):
            with self.subTest(block_type=block_type):
                self.assertEqual(detected("Produkt kosztuje 9.99 zł za sztukę.", block_type=block_type), {})

    def test_bibliography_list(self):
        self.assertEqual(run_blocks([make_list("Kowalski J., Cena 9.99 zł, wyd. 2.5", is_bibliography=True)]), {})

    def test_regular_list_reports_only_certain_errors(self):
        # Poza akapitami tolerancja = 2 - zgłaszamy tylko pewne błędy
        self.assertEqual(run_blocks([make_list("Cena 9.99 zł oraz średnio 3.5 sztuki")]), {"9.99": CERTAIN_PL})

    def test_no_blocks(self):
        self.assertEqual(decimal_check([], set()), [])


class TestNotErrorBranches(unittest.TestCase):
    '''Każda gałąź check_decimal_matches, która uznaje liczbę za poprawną.'''

    def test_toc_like_line_with_dot_leaders(self):
        # Linia z kropkami prowadzącymi traktowana jak spis treści, a jej numery są zapamiętywane
        toc = make_paragraph("Wstęp ..... 3.5 opis", block_id=1)
        later = make_paragraph("Średnia wartość wyniosła 3.5 jednostki.", block_id=2)
        self.assertEqual(run_blocks([toc, later]), {})

    def test_toc_like_line_with_unit_is_reported(self):
        self.assertEqual(detected("Cena ..... 3.5 zł obecnie"), {"3.5": CERTAIN_PL})

    def test_reference_number_is_remembered_for_later_blocks(self):
        reference = make_paragraph("Opis znajduje się w rozdziale 3.1 pracy.", block_id=1)
        later = make_paragraph("Średnia wartość wyniosła 3.1 jednostki.", block_id=2)
        self.assertEqual(run_blocks([reference, later]), {})

    def test_reference_word_after_number(self):
        for text in ("Zestawienie 2.1 tabela przedstawia dokładnie.",
                     "Zestawienie 4.3 rysunek przedstawia dokładnie.",
                     "Zależność 1.2 wzór opisuje dokładnie.",
                     "Kod 5.1 listing zawiera w całości."):
            with self.subTest(text=text):
                self.assertEqual(detected(text), {})

    def test_reference_abbreviations_before_number(self):
        for text in ("Pokazano to na rys. 2.1 powyżej.", "Pokazano to w tab. 2.1 powyżej.",
                     "Pokazano to w rozdz. 2.1 powyżej.", "Pokazano to w pkt 2.1 powyżej.",
                     "Pokazano to we wzorze 2.1 powyżej.", "It is shown in Section 2.1 above.",
                     "It is shown in Fig. 2.1 above.", "It is shown in Table 2.1 above."):
            with self.subTest(text=text):
                self.assertEqual(detected(text), {})

    def test_number_in_square_brackets(self):
        self.assertEqual(detected("Zgodnie z opisem [3.1] wartość jest stała."), {})

    def test_number_in_different_quotes(self):
        for text in ('Program wypisał "wynik 3.5" na ekranie.',
                     "Program wypisał 'wynik 3.5' na ekranie.",
                     "Program wypisał “wynik 3.5” na ekranie."):
            with self.subTest(text=text):
                self.assertEqual(detected(text), {})

    def test_number_in_quotes_with_unit(self):
        # Cytat ma pierwszeństwo przed czarną listą
        self.assertEqual(detected("Na metce było „9.99 zł” napisane."), {})

    def test_bold_or_italic_number(self):
        # "Średnia wartość wyniosła 3.5 jednostki." - liczba jest słowem o indeksie 3
        self.assertEqual(detected("Średnia wartość wyniosła 3.5 jednostki.", bold_words={3}), {})
        self.assertEqual(detected("Średnia wartość wyniosła 3.5 jednostki.", italic_words={3}), {})

    def test_number_from_table_of_contents_with_punctuation(self):
        self.assertEqual(detected("Szczegóły opisano w 3.1: poniżej.", chapter_nums={"3.1"}), {})

    def test_heading_number(self):
        self.assertEqual(detected("3.5 Wyniki badań", block_type="heading"), {})
        self.assertEqual(detected("Rozdział 3.5 Wyniki badań", block_type="heading"), {})


class TestErrorBranches(unittest.TestCase):
    '''Gałęzie zgłaszające błąd - pewny (jednostka/waluta) lub możliwy.'''

    def test_every_black_list_unit_is_certain(self):
        for text in ("Wzrost o 2.75% rocznie.", "Wzrost o 2.75 % rocznie.", "Koszt 2.75 $ za sztukę.",
                     "Koszt 2.75 € za sztukę.", "Koszt 2.75 £ za sztukę.", "Koszt 2.75 zł za sztukę.",
                     "Koszt 2.75zł za sztukę.", "Koszt 2.75 USD za sztukę.", "Koszt 2.75 EUR za sztukę.",
                     "Koszt 2.75 GBP za sztukę.", "Kąt 2.75° w pionie.", "Koszt 2.75 zł."):
            with self.subTest(text=text):
                self.assertEqual(detected(text), {"2.75": CERTAIN_PL})

    def test_unit_wins_over_reference_word_and_name(self):
        self.assertEqual(detected("W tabeli 2.5 zł za sztukę."), {"2.5": CERTAIN_PL})
        self.assertEqual(detected("Abonament Netflix 9.99 zł miesięcznie."), {"9.99": CERTAIN_PL})

    def test_reference_word_too_far_before_number(self):
        # Słowo odwołania jest dalej niż 15 znaków przed liczbą
        self.assertEqual(detected("Na rysunku widać, że średnia wynosi 3.5 punktu."), {"3.5": POSSIBLE_PL})

    def test_unclosed_bracket(self):
        self.assertEqual(detected("Wartość (3.5 jednostki) jest stała."), {"3.5": POSSIBLE_PL})

    def test_heading_reports_only_certain_errors(self):
        self.assertEqual(detected("Wyniki pomiaru 3.5 jednostki", block_type="heading"), {})
        self.assertEqual(detected("Koszt 9.99 zł za sztukę", block_type="heading"), {"9.99": CERTAIN_PL})

    def test_english_messages(self):
        en = {"language": "en", "document_language": "en"}
        self.assertEqual(detected("The price was 9,99 $ in total.", **en), {"9,99": CERTAIN_EN})
        self.assertEqual(detected("The growth was 2,5% per year.", **en), {"2,5": CERTAIN_EN})
        self.assertEqual(detected("Kosztuje to 9.99 $ za sztukę.", language="en", document_language="pl"),
                         {"9.99": CERTAIN_PL})

    def test_english_version_after_name(self):
        self.assertEqual(detected("We used Python 3,12 for tests.", language="en", document_language="en"), {})

    def test_match_position(self):
        text = "Średnia wartość wyniosła 3.5 jednostki."
        [match] = decimal_check([make_paragraph(text, block_id=7)], set())
        self.assertEqual((match.category, match.offset, match.error_length, match.block_id, match.page_start,
                          match.page_end, match.word_idxs),
                         ("DECIMAL", text.index("3.5"), 3, 7, 2, 2, [3]))


class TestDotInFigures(unittest.TestCase):
    '''Tekst rysunków wektorowych (etykiety, wymiary) trafia do page_artifacts, nie do bloków.'''

    @staticmethod
    def figure_matches(labels, language="pl"):
        from types import SimpleNamespace
        figure = VisualElement(element_id=1, type="image", page_number=23, bbox=[20.0, 4.0, 570.0, 400.0], caption={})
        artifacts = [PageArtifact(artifact_id=f"math_{i}", type="math_3", page_number=page, text=text, bbox=bbox)
                     for i, (text, page, bbox) in enumerate(labels)]
        artifacts.append(PageArtifact(artifact_id=99, type="nr strony (tymczasowo uproszczone)", page_number=23,
                                      text="2.5", bbox=[278.0, 100.0, 288.0, 110.0]))
        raw = SimpleNamespace(floating_elements=SimpleNamespace(visual_elements=[figure], page_artifacts=artifacts))
        return [(m.content, m.page_start, m.error_coordinate[0]["coordinates"]) for m in decimal_check_in_figures(raw, language)]

    def test_dimensions_of_braille_cell(self):
        # Przypadek ze zgłoszenia: wymiary na Rys. 2.5 nie były sprawdzane
        inside = [282.0, 170.0, 302.0, 194.0]
        self.assertEqual(self.figure_matches([("Ø1.5", 23, inside), ("7.5", 23, inside), (".95", 23, inside),
                                              ("9", 23, inside)]),
                         [("1.5", 23, inside), ("7.5", 23, inside), (".95", 23, inside)])

    def test_text_outside_figure_is_skipped(self):
        self.assertEqual(self.figure_matches([("7.5", 23, [20.0, 500.0, 40.0, 510.0]),
                                              ("7.5", 24, [282.0, 170.0, 302.0, 194.0])]), [])

    def test_version_label_in_figure(self):
        self.assertEqual(self.figure_matches([("WCAG 2.0", 23, [282.0, 170.0, 330.0, 194.0])]), [])

    def test_decimal_comma_in_english_figure(self):
        inside = [282.0, 170.0, 302.0, 194.0]
        self.assertEqual(self.figure_matches([("3,5", 23, inside), ("1,000", 23, inside), ("3.5", 23, inside)],
                                             language="en"), [("3,5", 23, inside)])

    def test_regex_in_polish_figure(self):
        inside = [282.0, 170.0, 302.0, 194.0]
        labels = [(text, 23, inside) for text in ("1.2.3", "v1.5", "3,5", "12", "0.5 i 2.25")]
        self.assertEqual([m[0] for m in self.figure_matches(labels)], ["0.5", "2.25"])

    def test_names_in_figure(self):
        inside = [282.0, 170.0, 330.0, 194.0]
        labels = [(text, 23, inside) for text in ("język Python 3.12", "iOS 17.1", "USB 3.0", "EUR 3.5", "masa 3.5",
                                                  # Wielka litera na początku etykiety = początek zdania, nie nazwa
                                                  # (nie da się odróżnić "Python 3.12" od "Masa 3.5")
                                                  "Masa 4.5")]
        self.assertEqual([m[0] for m in self.figure_matches(labels)], ["3.5", "3.5", "4.5"])

    def test_figure_margin(self):
        # Etykieta może wystawać poza rysunek o FIGURE_MARGIN (10 pt)
        self.assertEqual(len(self.figure_matches([("7.5", 23, [12.0, 0.0, 30.0, 10.0])])), 1)
        self.assertEqual(self.figure_matches([("7.5", 23, [5.0, 0.0, 30.0, 10.0])]), [])
        self.assertEqual(self.figure_matches([("7.5", 23, [560.0, 390.0, 581.0, 410.0])]), [])

    def test_footnotes_and_page_numbers_are_skipped(self):
        # figure_matches dodaje zawsze numer strony "2.5" leżący wewnątrz rysunku
        from types import SimpleNamespace
        figure = VisualElement(element_id=1, type="image", page_number=23, bbox=[20.0, 4.0, 570.0, 400.0], caption={})
        footnote = PageArtifact(artifact_id=1, type="footnote", page_number=23, text="3.5", bbox=[30.0, 30.0, 40.0, 40.0])
        raw = SimpleNamespace(floating_elements=SimpleNamespace(visual_elements=[figure], page_artifacts=[footnote]))
        self.assertEqual(decimal_check_in_figures(raw, "pl"), [])
        self.assertEqual(self.figure_matches([]), [])

    def test_only_image_elements_are_figures(self):
        from types import SimpleNamespace
        table = VisualElement(element_id=1, type="table", page_number=23, bbox=[20.0, 4.0, 570.0, 400.0], caption={})
        label = PageArtifact(artifact_id=1, type="math_3", page_number=23, text="3.5", bbox=[30.0, 30.0, 40.0, 40.0])
        raw = SimpleNamespace(floating_elements=SimpleNamespace(visual_elements=[table], page_artifacts=[label]))
        self.assertEqual(decimal_check_in_figures(raw, "pl"), [])

    def test_empty_label(self):
        self.assertEqual(self.figure_matches([(None, 23, [282.0, 170.0, 302.0, 194.0]),
                                              ("", 23, [282.0, 170.0, 302.0, 194.0])]), [])

    def test_match_fields_and_messages(self):
        from types import SimpleNamespace
        figure = VisualElement(element_id=1, type="image", page_number=5, bbox=[0.0, 0.0, 100.0, 100.0], caption={})
        label = PageArtifact(artifact_id="math_7", type="math_3", page_number=5, text="Ø 1.5", bbox=[10.0, 10.0, 20.0, 20.0])
        raw = SimpleNamespace(floating_elements=SimpleNamespace(visual_elements=[figure], page_artifacts=[label]))
        [match] = decimal_check_in_figures(raw, "pl")
        self.assertEqual((match.content, match.category, match.message, match.offset, match.error_length,
                          match.block_id, match.page_start, match.page_end, match.error_coordinate),
                         ("1.5", "DECIMAL", POSSIBLE_PL, 2, 3, "math_7", 5, 5,
                          [{"page": 5, "coordinates": [10.0, 10.0, 20.0, 20.0]}]))
        label.text = "1,5"
        self.assertEqual([m.message for m in decimal_check_in_figures(raw, "en")], [POSSIBLE_EN])


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
