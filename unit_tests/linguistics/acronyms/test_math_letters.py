'''
Tests for math font letters (e.g. "𝐒𝐕𝐌") and Greek letters in the acronym checks.

Run (from the repository root):
    .venv/Scripts/python.exe -m unittest discover -s unit_tests -t . -v

- normalize_math_letters / has_math_characters / is_latin_word / is_math_font - helper functions from helpers.py,
- check_if_was_defined - acronyms in math font are reported, Greek letters and math expressions are not,
- check_position_if_new / check_first_definition - definitions of acronyms in math font are recognized,
- TestGeneratedPdfs - full run on the PDFs from generate_pdfs.py. File names describe the expected result:
  tp_* - all acronyms must be reported, fp_* - nothing may be reported.
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import AcronymItem, ListBlock, ListItem, ParagraphBlock, WordInfo
from analysis.modules.linguistics.linguistics_types import Block_context
from analysis.modules.linguistics.helpers import has_math_characters, is_latin_word, is_math_font, normalize_math_letters
from analysis.modules.linguistics.check_acronym import check_if_was_defined
from analysis.modules.linguistics.first_definition import check_first_definition, check_position_if_new
from unit_tests.utils_generate_pdfs import LATEX_COMPILERS
from unit_tests.utils_test import pdf_to_blocks

PDF_DIR = Path(__file__).resolve().parent

# Words lie on one line at y=100; definitions "defined earlier" in the tests use y=50 (higher on the same page),
# because check_if_was_defined compares positions as (page, y, x)
LINE_Y = 100.0
DEFINED_ABOVE = [0.0, LINE_Y - 50, 10.0, LINE_Y - 40]


def make_words(content, page=1, italic=False):
    '''Splits the text on spaces into WordInfo objects with correct start_char/end_char.
    Each word has a distinct bbox (shifted horizontally by 10), so check_position_if_new results can be checked.'''
    words = []
    pos = 0
    for i, text in enumerate(content.split(" ")):
        words.append(WordInfo(word_index=i, text=text, start_char=pos, end_char=pos + len(text),
                              font="Times", size=12.0, bold=False, italic=italic,
                              bbox=[10.0 * i, LINE_Y, 10.0 * i + 8, LINE_Y + 12], page_number=page))
        pos += len(text) + 1
    return words


def make_paragraph(content, block_id=0, page=1, italic=False, language="pl"):
    block = ParagraphBlock(block_id=block_id, content=content, words=make_words(content, page, italic))
    # As in pipeline.py - each block gets the language chosen in the GUI
    block.language = language
    return Block_context(contents=content, language=language, block=block)


class TestNormalizeMathLetters(unittest.TestCase):
    '''Math font letters and digits are replaced with plain ones, the rest of the text is unchanged.'''

    def test_math_letters_and_digits(self):
        self.assertEqual(normalize_math_letters("𝐒𝐕𝐌"), "SVM")
        self.assertEqual(normalize_math_letters("𝑥+𝟏"), "x+1")

    def test_math_greek_letters(self):
        self.assertEqual(normalize_math_letters("𝜶𝛽"), "αβ")

    def test_characters_outside_math_block_unchanged(self):
        # NFKC would change the ligature and the superscript, but they are not math letters
        for text in ("ﬁ²", "Zażółć gęślą jaźń", ""):
            with self.subTest(text=text):
                self.assertEqual(normalize_math_letters(text), text)

    def test_length_preserved(self):
        # Word start_char must still point to the same place in the normalized block content
        text = "Model 𝐒𝐕𝐌 działa"
        self.assertEqual(len(normalize_math_letters(text)), len(text))


class TestHasMathCharacters(unittest.TestCase):
    '''Detection of math font letters and math symbols (Unicode category Sm).'''

    def test_math_characters(self):
        for text in ("𝐀", "A≤B", "A⊂B", "a+b"):
            with self.subTest(text=text):
                self.assertTrue(has_math_characters(text))

    def test_plain_text(self):
        # Greek letters and the hyphen are not math symbols
        for text in ("ABC", "a-b", "α", ""):
            with self.subTest(text=text):
                self.assertFalse(has_math_characters(text))


class TestIsLatinWord(unittest.TestCase):
    '''All letters of the word must belong to the Latin alphabet, other characters are ignored.'''

    def test_latin_words(self):
        for text in ("ABC", "Zażółć", "AB1", "A-B", ""):
            with self.subTest(text=text):
                self.assertTrue(is_latin_word(text))

    def test_greek_words(self):
        for text in ("ΣΔ", "Aα"):
            with self.subTest(text=text):
                self.assertFalse(is_latin_word(text))


class TestUndefinedAcronymDetected(unittest.TestCase):
    '''Acronyms in math font without an earlier definition must be reported.'''

    def test_math_font_acronym(self):
        matches, proper_names = check_if_was_defined([make_paragraph("Model 𝐒𝐕𝐌 działa")], {}, [])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].content, "𝐒𝐕𝐌")
        self.assertEqual(matches[0].word_idxs, [1])
        self.assertIn(("SVM", "SVM"), proper_names)

    def test_math_font_and_plain_acronym_reported_once(self):
        blocks = [make_paragraph("Model 𝐒𝐕𝐌 działa", block_id=0), make_paragraph("Model SVM działa", block_id=1)]
        matches, _ = check_if_was_defined(blocks, {}, [])
        self.assertEqual(len(matches), 1)

    def test_italic_math_font_acronym_as_first_word(self):
        # The first word is its own prev_word - the comparison must use the normalized text
        matches, _ = check_if_was_defined([make_paragraph("𝐒𝐕𝐌", italic=True)], {}, [])
        self.assertEqual(len(matches), 1)


class TestUndefinedAcronymNotDetected(unittest.TestCase):
    '''Defined acronyms, Greek letters and math expressions must not be reported.'''

    def test_math_font_acronym_defined_earlier(self):
        defined = {"SVM": ("Support Vector Machine", 0, 1, DEFINED_ABOVE)}
        matches, _ = check_if_was_defined([make_paragraph("Model 𝐒𝐕𝐌 działa")], defined, [])
        self.assertEqual(matches, [])

    def test_greek_letters(self):
        for content in ("Wartość ΣΔ rośnie", "Wartość 𝚺𝚫 rośnie"):
            with self.subTest(content=content):
                matches, _ = check_if_was_defined([make_paragraph(content)], {}, [])
                self.assertEqual(matches, [])

    def test_math_expressions(self):
        for expression in ("A⊂B", "𝐴≤𝐵", "𝐗+𝐘"):
            with self.subTest(expression=expression):
                matches, _ = check_if_was_defined([make_paragraph(f"Zbiór {expression} jest")], {}, [])
                self.assertEqual(matches, [])

    def test_math_font_definition_without_closing_parenthesis(self):
        content = "𝐒𝐕𝐌 (ang. support vector machine, klasyfikator) działa"
        matches, _ = check_if_was_defined([make_paragraph(content)], {}, [])
        self.assertEqual(matches, [])


class TestMathFontDefinitionFound(unittest.TestCase):
    '''Definitions of acronyms written in math font are stored in acronyms_with_definitions under the plain name.'''

    def test_position_of_math_font_word(self):
        words = make_words("Model 𝐒𝐕𝐌, działa", page=3)
        result = check_position_if_new("SVM", "Support Vector Machine", words, 5, {})
        self.assertEqual(result["SVM"], ("Support Vector Machine", 5, 3, words[1].bbox))

    def test_position_of_math_font_word_by_prefix(self):
        words = make_words("Model 𝐒𝐕𝐌-ach działa", page=2)
        result = check_position_if_new("SVM", "Support Vector Machine", words, 1, {})
        self.assertEqual(result["SVM"][3], words[1].bbox)

    def test_official_acronym_list(self):
        item = AcronymItem(acronym="𝐒𝐕𝐌", definition="Support Vector Machine", pages="1", words=make_words("𝐒𝐕𝐌"))
        definitions, _, _ = check_first_definition([], [], [item])
        self.assertNotIn("𝐒𝐕𝐌", definitions)
        self.assertEqual(definitions["SVM"][:2], ("Support Vector Machine", "official_list"))

    def test_list_item(self):
        text = "𝐂𝐍𝐍 – Convolutional Neural Network"
        item = ListItem(item_id=0, marker_type="bullet", text=text, bbox=[0, 0, 0, 0], words=make_words(text, page=4))
        block = ListBlock(block_id="list_2", content=text, bbox=[0, 0, 0, 0], items=[item], words=make_words(text, page=4))
        block.language = "en"
        definitions, _, _ = check_first_definition([Block_context(text, "en", block)], [], [])
        self.assertEqual(definitions["CNN"][1:3], ("list_2", 4))

    def test_paragraph(self):
        content = "Klasyfikator 𝐒𝐕𝐌 (ang. Support Vector Machine) jest skuteczny"
        definitions, _, _ = check_first_definition([make_paragraph(content, block_id=6, page=2)], [], [])
        self.assertEqual(definitions["SVM"][1:3], (6, 2))


# "QXV" is not in the dictionaries (typo_check returns False), so it is not skipped as a regular word
MATH_FONT_QXV = {
    "bold": "𝐐𝐗𝐕",
    "italic": "𝑄𝑋𝑉",
    "bold italic": "𝑸𝑿𝑽",
    "sans-serif": "𝖰𝖷𝖵",
    "monospace": "𝚀𝚇𝚅",
    "bold fraktur": "𝕼𝖃𝖁",
    "script": "𝒬𝒳𝒱",
    # ℚ is in the Letterlike Symbols block, not in the math block
    "double-struck": "ℚ𝕏𝕍",
}

# Acronyms containing math alphabet letters from the Letterlike Symbols block (ℳ, ℌ, ℝ)
LETTERLIKE_ACRONYMS = {"script": ("ℳ𝒳𝒲", "MXW"), "fraktur": ("ℌ𝔛𝔚", "HXW"), "double-struck": ("ℝ𝕏𝕍", "RXV")}


class TestNormalizeMathLettersEdgeCases(unittest.TestCase):
    '''Different math font styles, digits and symbols in equations.'''

    def test_math_alphabets(self):
        for font, text in MATH_FONT_QXV.items():
            with self.subTest(font=font):
                self.assertEqual(normalize_math_letters(text), "QXV")

    def test_double_struck_letters_inside_math_block(self):
        self.assertEqual(normalize_math_letters("𝔸𝔹𝕏"), "ABX")

    def test_math_digits(self):
        self.assertEqual(normalize_math_letters("𝟎𝟏𝟐𝟙𝟿"), "01219")

    def test_math_nabla_and_partial(self):
        # Bold nabla and partial differential are in the math block and become plain symbols
        self.assertEqual(normalize_math_letters("𝛁𝛛"), "∇∂")

    def test_equation(self):
        self.assertEqual(normalize_math_letters("𝑓(𝑥)=𝑥²+𝜋"), "f(x)=x²+π")

    def test_symbols_outside_math_block_unchanged(self):
        for text in ("∈", "∀", "√2", "∑", "∫", "∞", "≠", "±", "→", "°", "µ", "Ω"):
            with self.subTest(text=text):
                self.assertEqual(normalize_math_letters(text), text)

    def test_letterlike_math_letters(self):
        # Math alphabet letters encoded in the Letterlike Symbols block - the math block has holes in their place
        letters = {"double-struck": ("ℂℍℕℙℚℝℤ", "CHNPQRZ"), "script": ("ℬℰℱℋℐℒℳℛℯℊℴ", "BEFHILMRego"),
                   "fraktur": ("ℭℌℑℜℨ", "CHIRZ"), "italic": ("ℎ", "h")}
        for font, (text, expected) in letters.items():
            with self.subTest(font=font):
                self.assertEqual(normalize_math_letters(text), expected)

    def test_letterlike_acronyms(self):
        for font, (text, expected) in LETTERLIKE_ACRONYMS.items():
            with self.subTest(font=font):
                self.assertEqual(normalize_math_letters(text), expected)

    def test_other_letterlike_symbols_unchanged(self):
        # NFKC would change them (e.g. ℃ -> °C), which would shift word start_char relative to the block content
        for name, text in {"stopnie Celsjusza": "℃", "znak towarowy": "™", "numero": "№", "om": "Ω",
                           "kelwin": "K", "litr": "ℓ", "angstrem": "Å"}.items():
            with self.subTest(name=name):
                self.assertEqual(normalize_math_letters(text), text)

    def test_letters_in_equation(self):
        self.assertEqual(normalize_math_letters("∀𝑥∈ℝ"), "∀x∈R")
        self.assertEqual(normalize_math_letters("ℝⁿ"), "Rⁿ")
        self.assertEqual(normalize_math_letters("𝑥ℎ"), "xh")


class TestHasMathCharactersEdgeCases(unittest.TestCase):
    '''Math symbols (category Sm) as single characters and in equations.'''

    def test_math_symbols(self):
        symbols = {
            "należy": "∈", "nie należy": "∉", "dla każdego": "∀", "istnieje": "∃",
            "pierwiastek": "√", "pierwiastek sześcienny": "∛", "suma": "∑", "iloczyn": "∏",
            "całka": "∫", "nieskończoność": "∞", "pochodna cząstkowa": "∂", "nabla": "∇",
            "różne": "≠", "w przybliżeniu": "≈", "plus-minus": "±", "razy": "×", "dzielenie": "÷",
            "strzałka": "→", "implikacja": "⇒", "równoważność": "⇔", "zbiór pusty": "∅",
            "złożenie": "∘", "iloczyn skalarny": "⋅",
        }
        for name, symbol in symbols.items():
            with self.subTest(name=name):
                self.assertTrue(has_math_characters(symbol))

    def test_equations(self):
        for text in ("∀𝑥∈ℝ", "𝑓(𝑥)=𝑥²", "√2", "a≠b", "n→∞", "∑𝑥ᵢ"):
            with self.subTest(text=text):
                self.assertTrue(has_math_characters(text))

    def test_not_math_symbols(self):
        # Characters outside category Sm and outside the math block, including number set letters from the Letterlike block
        for name, text in {"stopień": "°", "prim": "′", "kropka środkowa": "·", "indeks górny": "²",
                           "liczby rzeczywiste": "ℝ", "liczby naturalne": "ℕ", "pi": "π", "omega": "Ω",
                           "mikro": "µ"}.items():
            with self.subTest(name=name):
                self.assertFalse(has_math_characters(text))


class TestIsLatinWordEdgeCases(unittest.TestCase):
    '''Greek letters, unit signs and number set letters are not Latin letters.'''

    def test_latin_with_diacritics(self):
        for text in ("Łódź", "Straße", "ÆØÅ", "f(x)=x²"):
            with self.subTest(text=text):
                self.assertTrue(is_latin_word(text))

    def test_greek_letters(self):
        for text in ("π", "λ", "Δ", "ΣΩ", "ΔQXV", "QXΔ", "QXV-Δ", "πr²"):
            with self.subTest(text=text):
                self.assertFalse(is_latin_word(text))

    def test_letterlike_symbols(self):
        # The micro sign and number set letters have Unicode names without "LATIN"
        for text in ("µA", "ℝ", "ℕ", "ℤ", "ℝⁿ"):
            with self.subTest(text=text):
                self.assertFalse(is_latin_word(text))


class TestMathFontAcronymEdgeCasesDetected(unittest.TestCase):
    '''Acronyms in every math font style and with punctuation must be reported.'''

    def test_all_math_alphabets(self):
        for font, text in MATH_FONT_QXV.items():
            with self.subTest(font=font):
                matches, _ = check_if_was_defined([make_paragraph(f"Wzór {text} jest")], {}, [])
                self.assertEqual([m.content for m in matches], [text])

    def test_letterlike_letters_in_acronym(self):
        # Previously e.g. "ℳ𝒳𝒲" was normalized to "ℳXW" and skipped by is_latin_word
        for font, (text, _) in LETTERLIKE_ACRONYMS.items():
            with self.subTest(font=font):
                matches, _ = check_if_was_defined([make_paragraph(f"Wzór {text} jest")], {}, [])
                self.assertEqual([m.content for m in matches], [text])

    def test_punctuation_around_acronym(self):
        for text in ("(𝐐𝐗𝐕)", "𝐐𝐗𝐕,", "𝐐𝐗𝐕:"):
            with self.subTest(text=text):
                matches, _ = check_if_was_defined([make_paragraph(f"Wzór {text} jest")], {}, [])
                self.assertEqual(len(matches), 1)

    def test_acronym_next_to_equation(self):
        # An equation split by spaces must not block reporting an acronym in the same sentence
        content = "Błąd 𝐐𝐗𝐕 spełnia ∑ 𝑒ᵢ ≤ 𝜀 dla ∀ 𝑖 ∈ ℕ"
        matches, _ = check_if_was_defined([make_paragraph(content)], {}, [])
        self.assertEqual([m.content for m in matches], ["𝐐𝐗𝐕"])
        self.assertEqual(matches[0].word_idxs, [1])


class TestMathFontAcronymEdgeCasesNotDetected(unittest.TestCase):
    '''Math expressions, Greek letters and Roman numerals must not be reported as acronyms.'''

    def assert_not_reported(self, words):
        for word in words:
            with self.subTest(word=word):
                matches, _ = check_if_was_defined([make_paragraph(f"Wzór {word} jest")], {}, [])
                self.assertEqual(matches, [])

    def test_acronym_letters_glued_to_math_symbols(self):
        self.assert_not_reported(("√𝐐𝐗𝐕", "∀𝐐𝐗𝐕", "𝐐𝐗𝐕∈ℝ", "∑𝐐𝐗𝐕", "𝐐𝐗𝐕→𝐐𝐗", "𝐐𝐗𝐕×𝐐𝐗", "QXV±",
                                  "∇QX", "𝛁𝐐𝐗", "∂QX", "NP≠P"))

    def test_greek_letters(self):
        self.assert_not_reported(("ΣΩ", "𝚺𝛀", "ΔQXV", "QXΔ", "QXV-Δ", "µQX", "Ωm"))

    def test_digits_and_superscripts(self):
        self.assert_not_reported(("𝐐𝐗𝐕²", "𝐐𝐗𝐕𝟐", "O(n²)"))

    def test_math_font_roman_numerals(self):
        self.assert_not_reported(("XIV", "𝐗𝐈𝐕", "𝑋𝐼𝑉"))

    def test_whole_equation_split_into_words(self):
        content = "Dla ∀ 𝑥 ∈ ℝ zachodzi 𝑓(𝑥) = √𝑥² + 𝜋 oraz ∫ 𝑓 𝑑𝑥 < ∞"
        matches, _ = check_if_was_defined([make_paragraph(content)], {}, [])
        self.assertEqual(matches, [])

    def test_math_block_skipped(self):
        block = make_paragraph("𝐐𝐗𝐕 = ∑ 𝑥ᵢ")
        block.block.type = "math"
        matches, _ = check_if_was_defined([block], {}, [])
        self.assertEqual(matches, [])

    def test_defined_in_other_math_font(self):
        # A definition in one font style covers uses in the others
        defined = {"QXV": ("Quick Xray Vector", 0, 1, DEFINED_ABOVE)}
        for font, text in MATH_FONT_QXV.items():
            with self.subTest(font=font):
                matches, _ = check_if_was_defined([make_paragraph(f"Wzór {text} jest")], defined, [])
                self.assertEqual(matches, [])


class TestIsMathFont(unittest.TestCase):
    '''Fonts used for typesetting math (pdflatex, unicode-math, Word) and text fonts.'''

    def test_math_fonts(self):
        for font in ("LMMathItalic12-Regular", "LMMathItalic8-Regular", "LMMathSymbols10-Regular",
                     "LMMathExtension10-Regular", "LatinModernMath-Regular", "CMMI10", "CMSY10", "CMEX10",
                     "MSBM10", "MSAM10", "EUFM10", "CambriaMath", "Cambria Math", "STIXTwoMath-Regular"):
            with self.subTest(font=font):
                self.assertTrue(is_math_font(font))

    def test_text_fonts(self):
        # Text italic fonts from the 18 test theses and LaTeX text fonts
        for font in ("LMRoman12-Italic", "LMRoman12-Regular", "TimesNewRomanPS-ItalicMT", "TeXGyreHeros-Italic",
                     "NimbusSanL-ReguItal", "CMTI10", "CMR10", "Times", ""):
            with self.subTest(font=font):
                self.assertFalse(is_math_font(font))


class TestAcronymAfterItalicWord(unittest.TestCase):
    '''Acronym after a word with the italic flag: text italic blocks reporting, a math variable does not.'''

    def run_check(self, prev_font):
        block = make_paragraph("Dla próbki x QXV działa")
        block.block.words[2].italic = True
        block.block.words[2].font = prev_font
        matches, _ = check_if_was_defined([block], {}, [])
        return [m.content for m in matches]

    def test_math_variable_before_acronym(self):
        # pdflatex: "$x$ QXV" and subscripts "$t_{\mathrm{QXV}}$" - the variable has an LMMathItalic font with the italic flag
        for font in ("LMMathItalic12-Regular", "LMMathSymbols10-Regular", "CMMI10"):
            with self.subTest(font=font):
                self.assertEqual(self.run_check(font), ["QXV"])

    def test_text_italic_before_acronym(self):
        # Acronym inside a foreign phrase written in italic, e.g. "(Conditional DPT)"
        for font in ("TeXGyreHeros-Italic", "LMRoman12-Italic"):
            with self.subTest(font=font):
                self.assertEqual(self.run_check(font), [])


class TestMathFontDefinitionEdgeCases(unittest.TestCase):
    '''Acronym definitions in different math font styles.'''

    def test_position_of_word_in_parenthesis(self):
        words = make_words("Wektor (𝑄𝑋𝑉) jest", page=5)
        result = check_position_if_new("QXV", "Quick Xray Vector", words, 2, {})
        self.assertEqual(result["QXV"][2:], (5, words[1].bbox))

    def test_official_acronym_list_in_all_math_alphabets(self):
        for font, text in MATH_FONT_QXV.items():
            with self.subTest(font=font):
                item = AcronymItem(acronym=text, definition="Quick Xray Vector", pages="1", words=make_words(text))
                definitions, _, _ = check_first_definition([], [], [item])
                self.assertEqual(list(definitions), ["QXV"])

    def test_letterlike_acronym_defined_in_paragraph(self):
        content = "Rodzina ℳ𝒳𝒲 (ang. Multi Xray Weighting) opisuje rozwiązania, a ℳ𝒳𝒲 jest skończona"
        definitions, proper_names, _ = check_first_definition([make_paragraph(content, block_id=4)], [], [])
        self.assertEqual(definitions["MXW"][:2], ("Multi Xray Weighting", 4))
        matches, _ = check_if_was_defined([make_paragraph(content, block_id=4)], definitions, proper_names)
        self.assertEqual(matches, [])

    def test_list_item_in_all_math_alphabets(self):
        for font, acronym in MATH_FONT_QXV.items():
            with self.subTest(font=font):
                text = f"{acronym} – Quick Xray Vector"
                item = ListItem(item_id=0, marker_type="bullet", text=text, bbox=[0, 0, 0, 0], words=make_words(text))
                block = ListBlock(block_id="list_0", content=text, bbox=[0, 0, 0, 0], items=[item], words=make_words(text))
                block.language = "en"
                definitions, _, _ = check_first_definition([Block_context(text, "en", block)], [], [])
                self.assertIn("QXV", definitions)

    def test_definition_next_to_equation(self):
        content = "Wektor 𝑸𝑿𝑽 (ang. Quick Xray Vector) spełnia ‖𝑥‖ ≤ √𝑛"
        definitions, _, _ = check_first_definition([make_paragraph(content, block_id=3)], [], [])
        self.assertEqual(definitions["QXV"][:2], ("Quick Xray Vector", 3))


class TestGeneratedPdfs(unittest.TestCase):
    '''Full run extraction -> definitions -> undefined acronyms on PDFs from different compilers.'''

    @classmethod
    def setUpClass(cls):
        from analysis.modules.linguistics.proper_names import get_proper_names

        def run(pdf_path):
            raw_blocks, blocks = pdf_to_blocks(pdf_path)
            # Same order as in run_linguistics
            proper_names, _ = get_proper_names(blocks)
            definitions, proper_names, _ = check_first_definition(blocks, proper_names, raw_blocks.reference_sections.acronyms)
            matches, _ = check_if_was_defined(blocks, definitions, proper_names)
            return blocks, definitions, [normalize_math_letters(m.content) for m in matches]

        cls.run_pdf = staticmethod(run)

    def test_tp_undefined_math_font_acronym(self):
        expected = ["QXV", "KXV", "JXW", "YXV", "VXW", "XWV", "KWX", "ZQX", "GXW", "DXW", "WXJ", "RXV", "HXW", "HXV", "TXV"]
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                _, _, reported = self.run_pdf(PDF_DIR / f"tp_undefined_math_font_acronym_{compiler}.pdf")
                self.assertEqual(reported, expected)

    def test_fp_math_expressions(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                blocks, _, reported = self.run_pdf(PDF_DIR / f"fp_math_expressions_{compiler}.pdf")
                # Paragraphs with equations must reach the analysis, otherwise the test would pass trivially
                self.assertTrue(any(has_math_characters(w.text) for b in blocks for w in b.block.words))
                self.assertEqual(reported, [])

    def test_fp_defined_math_font_acronym(self):
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                _, definitions, reported = self.run_pdf(PDF_DIR / f"fp_defined_math_font_acronym_{compiler}.pdf")
                self.assertLessEqual({"QXV", "JXW", "GXW", "MXW"}, set(definitions))
                self.assertEqual(reported, [])

    def test_fp_acronym_list_subscript(self):
        acronyms = {"QXV", "KXV", "JXW", "GXW", "MXW", "YXV"}
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                blocks, definitions, reported = self.run_pdf(PDF_DIR / f"fp_acronym_list_subscript_{compiler}.pdf")
                self.assertLessEqual(acronyms, set(definitions))
                # Subscripts must reach the analysis (page 3 - after the list of acronyms), otherwise the test would pass trivially.
                # pdflatex loses "Y" from a math italic subscript ($T_{YXV}$ -> "T", "XV")
                subscripts = {normalize_math_letters(w.text) for b in blocks for w in b.block.words if w.page_number == 3}
                expected = acronyms - {"YXV"} if compiler == "pdflatex" else acronyms
                self.assertLessEqual(expected, subscripts)
                self.assertEqual(reported, [])

    # Subscript acronyms missing from the list and DXW defined in the text only after use; QXV from the list is not reported
    TP_SUBSCRIPTS = ["VXW", "XWV", "KWX", "GXW", "HXW", "ZQX", "DXW"]

    def test_tp_acronym_list_subscript(self):
        # In pdflatex the variable before the subscript (E, σ, ...) has an LMMathItalic font with the italic flag - it must not block reporting
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                _, definitions, reported = self.run_pdf(PDF_DIR / f"tp_acronym_list_subscript_{compiler}.pdf")
                self.assertLessEqual({"QXV", "KXV", "DXW"}, set(definitions))
                self.assertEqual(reported, self.TP_SUBSCRIPTS)


if __name__ == "__main__":
    unittest.main()
