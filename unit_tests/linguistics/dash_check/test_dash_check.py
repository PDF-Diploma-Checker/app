'''
Tests for telling a compound word (hyphen) from a range/relation (en dash) in dash_check.py.

Checks that:
- classify_dash returns "compound" for compound words (polsko-niemiecki, 10-letni, COVID-19, PA12-CF, PDF-a,
  e-mail, między-datasetowych), "range" for ranges (1990-2000, XIX-XX, maj-czerwiec, sty-mar, pon-pt)
  and "unknown" for noun-noun relations (serwer-klient, Warszawa-Kraków) that cannot be decided by rules,
- en dash without spaces is flagged only in a compound word ("biało–czerwony"), not in ranges/relations
  ("serwer–klient", "maj–czerwiec", "1990–2000") nor in chains ("serwer–klient–ESP32"),
- em dash without spaces is flagged also next to Polish letters ("był—wtedy"),
- hyphen in a word range ("maj-czerwiec", "pon-pt") is flagged, hyphen in a compound word is not,
- date/number ranges glued to a letter ("SG90-30", "SG90 - 30") or inside a model name ("Llama-2-70B")
  are not flagged, plain ones still are and decimal ranges are flagged whole ("0.5-1.5"),
- TestGeneratedPdfs verifies full pipeline run (extraction -> analysis) on test PDFs
  built by different LaTeX compilers (pdflatex, xelatex, lualatex).

Run:
    uv run python -m unittest unit_tests/linguistics/dash_check/test_dash_check.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, WordInfo
from analysis.modules.linguistics.linguistics_types import Block_context
from analysis.modules.linguistics.dash_check import classify_dash, dash_check
from unit_tests.utils_generate_pdfs import LATEX_COMPILERS
from unit_tests.utils_test import pdf_to_blocks

PDF_DIR = Path(__file__).resolve().parent

MSG_COMPOUND_PL = "Półpauza zamiast dywizu w nazwie łączonej."
MSG_COMPOUND_EN = "En dash instead of hyphen in a compound word."
MSG_RANGE_PL = "Dywiz zamiast półpauzy w zakresie."
MSG_RANGE_EN = "Hyphen instead of en dash in a range."
MSG_EM_DASH_PL = "Brak spacji wokół myślnika we wtrąceniu, bądź półpauza zamiast dywizu w nazwie łączonej."
MSG_DATE_PL = "W polskich zakresach dat/liczb nie używa się spacji wokół myślnika."
MSG_DATE_EN = "English dates do not use spaces around en dashes (–)."


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


def run_check(text, language="pl"):
    return dash_check([make_block(text, language=language)])


def with_message(matches, message):
    return [m.content for m in matches if m.message == message]


def kind(pair):
    left, right = pair.split("-", 1)
    return classify_dash(left, right)


class TestClassifyDash(unittest.TestCase):

    def assert_kind(self, pairs, expected_kind, expected_reason=None):
        for pair in pairs:
            with self.subTest(pair=pair):
                result_kind, result_reason = kind(pair)
                self.assertEqual(result_kind, expected_kind)
                if expected_reason is not None:
                    self.assertEqual(result_reason, expected_reason)

    def test_adjectival_compound(self):
        # Morfeusz tags the first part as adja only when the whole hyphenated word is analysed
        self.assert_kind(["polsko-niemiecki", "biało-czerwoną", "społeczno-ekonomicznych", "Bielsko-Biała"],
                         "compound", "adjectival")

    def test_number_and_roman_suffix(self):
        self.assert_kind(["10-letni", "3-krotny", "XIX-wieczny"], "compound", "number_suffix")

    def test_identifiers(self):
        self.assert_kind(["COVID-19", "RS-232", "PA12-CF", "PA12-AL"], "compound", "identifier")

    def test_abbreviation_inflection(self):
        self.assert_kind(["PDF-a", "SMS-y", "SQL-owy"], "compound", "abbrev_inflection")

    def test_letter_prefix(self):
        self.assert_kind(["e-mail", "e-learning"], "compound", "letter_prefix")

    def test_preposition_prefix(self):
        self.assert_kind(["między-datasetowych"], "compound", "prep_prefix")

    def test_number_ranges(self):
        self.assert_kind(["1990-2000", "5-10"], "range", "number")
        self.assert_kind(["XIX-XX", "I-III"], "range", "roman")

    def test_month_ranges(self):
        self.assert_kind(["maj-czerwiec", "stycznia-marca", "May-June"], "range", "month")
        self.assert_kind(["sty-mar", "sier-wrz", "Jan-Mar", "Sept-Dec"], "range", "month_abbrev")

    def test_weekday_ranges(self):
        self.assert_kind(["poniedziałek-piątek", "piątku-soboty"], "range", "weekday")
        # "pt" is read by Morfeusz as piątek; abbreviations must still pair up with each other
        self.assert_kind(["pon-pt", "Mon-Fri"], "range", "weekday_abbrev")

    def test_unknown_relations(self):
        self.assert_kind(["serwer-klient", "człowiek-robot", "Warszawa-Kraków", "Kowalska-Nowak",
                          "przód-tył", "wysoko-nisko", "kilku-kilkunastu", "od-do", "Q1-Q4"], "unknown")

    def test_mixed_period_kinds_unknown(self):
        self.assert_kind(["sty-pt", "maj-piątek"], "unknown")

    def test_non_alphanumeric_unknown(self):
        self.assertEqual(classify_dash("", "abc")[0], "unknown")
        self.assertEqual(classify_dash("a_b", "c")[0], "unknown")


class TestEnDashWithoutSpaces(unittest.TestCase):

    def test_compound_word_flagged(self):
        matches = run_check("Na maszcie wisiała flaga biało–czerwona od rana.")
        self.assertEqual(with_message(matches, MSG_COMPOUND_PL), ["biało–czerwona"])

    def test_compound_word_error_covers_whole_word(self):
        text = "Pandemia COVID–19 zmieniła zajęcia."
        matches = [m for m in run_check(text) if m.message == MSG_COMPOUND_PL]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].offset, text.index("COVID"))
        self.assertEqual(matches[0].error_length, len("COVID–19"))
        self.assertEqual(matches[0].category, "PUNCTUATION")

    def test_english_message(self):
        matches = run_check("The black–white image was used.", language="en")
        # English words are not analysed by Morfeusz -> unknown, so use an identifier instead
        self.assertEqual(with_message(matches, MSG_COMPOUND_EN), [])
        matches = run_check("The COVID–19 pandemic changed teaching.", language="en")
        self.assertEqual(with_message(matches, MSG_COMPOUND_EN), ["COVID–19"])

    def test_ranges_and_relations_not_flagged(self):
        for text in ["System działa w architekturze serwer–klient od lat.",
                     "Interakcja człowiek–robot jest tematem pracy.",
                     "Badania trwały w okresie maj–czerwiec.",
                     "Dane zebrano w latach 1990–2000."]:
            with self.subTest(text=text):
                self.assertEqual(run_check(text), [])

    def test_chain_not_flagged(self):
        self.assertEqual(run_check("Komunikacja na odcinku serwer–klient–ESP32 działała."), [])
        self.assertEqual(run_check("Potok biało–czerwono–zielony był testowy."), [])


class TestEmDashWithoutSpaces(unittest.TestCase):

    def test_em_dash_next_to_polish_letters_flagged(self):
        # before the change the regex used [a-zA-Z] and missed "ł" / "ś"
        matches = run_check("Model był—jak wspomniano—szybki.")
        self.assertEqual(with_message(matches, MSG_EM_DASH_PL), ["ł—j", "o—s"])

    def test_em_dash_between_digits_not_flagged(self):
        self.assertEqual(with_message(run_check("W latach 1990—2000 dane zebrano."), MSG_EM_DASH_PL), [])


class TestHyphenInWordRange(unittest.TestCase):

    def test_month_range_flagged(self):
        matches = run_check("Badania trwały w okresie maj-czerwiec.")
        self.assertEqual(with_message(matches, MSG_RANGE_PL), ["maj-czerwiec"])

    def test_weekday_and_abbreviation_ranges_flagged(self):
        matches = run_check("Biuro jest czynne pon-pt oraz poniedziałek-piątek w sezonie.")
        self.assertEqual(with_message(matches, MSG_RANGE_PL), ["pon-pt", "poniedziałek-piątek"])

    def test_english_message(self):
        matches = run_check("The study ran May-June.", language="en")
        self.assertEqual(with_message(matches, MSG_RANGE_EN), ["May-June"])

    def test_compound_and_number_not_flagged(self):
        for text in ["Na maszcie wisiała flaga biało-czerwona od rana.",
                     "Architektura serwer-klient jest prosta.",
                     "Dane zebrano w latach 1990-2000."]:
            with self.subTest(text=text):
                self.assertEqual(with_message(run_check(text), MSG_RANGE_PL), [])

    def test_chain_not_flagged(self):
        self.assertEqual(with_message(run_check("Okres maj-czerwiec-lipiec był suchy."), MSG_RANGE_PL), [])


class TestDateRangeGluedToLetter(unittest.TestCase):

    def test_pl_model_name_not_flagged(self):
        matches = run_check("Użyto serwa SG90 - 30 sztuk zamówiono.")
        self.assertEqual(with_message(matches, MSG_DATE_PL), [])

    def test_pl_plain_range_with_spaces_flagged(self):
        matches = run_check("Dane zebrano w latach 1990 - 2000 w Polsce.")
        self.assertEqual(with_message(matches, MSG_DATE_PL), ["1990 - 2000"])

    def test_pl_model_size_not_flagged(self):
        # toci.pdf s.65: "InceptionV3 - 250 MB" was taken as a range "3 - 250"
        matches = run_check("Model sieci neuronowej InceptionV3 - 250 MB zajmuje dużo.")
        self.assertEqual(with_message(matches, MSG_DATE_PL), [])

    def test_en_model_name_not_flagged(self):
        for text in ["The SG90-30 servo was used.", "The MG996R-10 servo was used."]:
            with self.subTest(text=text):
                self.assertEqual(with_message(run_check(text, language="en"), MSG_DATE_EN), [])

    def test_en_plain_range_flagged(self):
        matches = run_check("Data were collected in 1990-2000 in Poland.", language="en")
        self.assertEqual(with_message(matches, MSG_DATE_EN), ["1990-2000"])

    def test_en_model_name_with_dashes_not_flagged(self):
        # before a2ab56a the regex took "2-70" and "5-7" out of the model names as ranges
        matches = run_check("We fine-tuned Llama-2-70B and Qwen-2.5-7B models.", language="en")
        self.assertEqual(with_message(matches, MSG_DATE_EN), [])

    def test_en_decimal_range_flagged_whole(self):
        # before a2ab56a only "5-1" was flagged, the error now covers the whole decimal range
        matches = run_check("The voltage was 0.5-1.5 V.", language="en")
        self.assertEqual(with_message(matches, MSG_DATE_EN), ["0.5-1.5"])


class TestGeneratedPdfs(unittest.TestCase):
    '''Full run extraction -> dash_check on PDFs compiled with different compilers.'''

    @classmethod
    def setUpClass(cls):
        def run(pdf_path):
            _, blocks = pdf_to_blocks(pdf_path)
            return [(m.content, m.message) for m in dash_check(blocks)]

        cls.run_pdf = staticmethod(run)

    def test_tp_compound_and_range(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                results = self.run_pdf(PDF_DIR / f"tp_dash_compound_and_range_{compiler}.pdf")
                self.assertIn(("biało–czerwona", MSG_COMPOUND_PL), results)
                self.assertIn(("polsko–niemieckie", MSG_COMPOUND_PL), results)
                self.assertIn(("COVID–19", MSG_COMPOUND_PL), results)
                self.assertIn(("maj-czerwiec", MSG_RANGE_PL), results)

    def test_fp_compound_and_range(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                results = self.run_pdf(PDF_DIR / f"fp_dash_compound_and_range_{compiler}.pdf")
                messages = {message for _, message in results}
                self.assertNotIn(MSG_COMPOUND_PL, messages)
                self.assertNotIn(MSG_RANGE_PL, messages)
                self.assertNotIn(MSG_DATE_PL, messages)
                self.assertNotIn(MSG_EM_DASH_PL, messages)


if __name__ == "__main__":
    unittest.main()
