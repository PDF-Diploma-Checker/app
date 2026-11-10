'''
Tests for lists whose items end with a line containing inline math, and for the hyphen in definitions
that is read as a list marker.

Checks that:
- a continuation line of running text with numbers in a math font ("wynosić 6,00 mm,") is not cut off
  as a formula (PDFMapper.is_math), which made list items look like they end mid-sentence (false LIST_ENDING),
- a hyphen cut off as a single-item list marker ("USB" / "- Uniwersalna ...") is still seen by dash_check.

Run:
    uv run python -m unittest unit_tests/linguistics/list_inline_math/test_list_inline_math.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, ListBlock, ListItem, WordInfo
from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from analysis.extraction.raw_extraction.text_extractor import TextLine, TextSpan
from analysis.modules.linguistics.dash_check import dash_check
from analysis.modules.linguistics.list_check import check_coherence_in_list
from analysis.modules.linguistics.linguistics_types import Block_context


def word(text, font="ArialMT", index=0, start=0):
    return WordInfo(
        word_index=index, text=text, start_char=start, end_char=start + len(text), font=font, size=10.0,
        bold=False, italic=False, bbox=[10.0 * index, 100.0, 10.0 * index + 8, 112.0], page_number=1,
    )


class TestIsMath(unittest.TestCase):

    def test_continuation_line_with_inline_math_is_not_a_formula(self):
        for texts in (["wynosić", "6,", "00", "mm,"], ["0,", "40", "mm", "do", "0,", "48", "mm."]):
            with self.subTest(texts=texts):
                words = [word(t, "CMR10" if t[0].isdigit() else "ArialMT", i) for i, t in enumerate(texts)]
                self.assertEqual(PDFMapper.is_math(words), 0)

    def test_pure_formula_is_still_math(self):
        words = [word(t, "CMMI10", i) for i, t in enumerate(["E", "=", "m", "c", "2"])]
        self.assertGreater(PDFMapper.is_math(words), 0)


class TestMarkerHyphen(unittest.TestCase):

    def test_hyphen_marker_is_kept_for_dash_check(self):
        words = [word("-", index=0), word("Uniwersalna", index=1, start=0), word("magistrala", index=2, start=12)]
        words[0].start_char = words[0].end_char = 0
        item = ListItem(item_id=1, marker_type="dash", text="Uniwersalna magistrala", bbox=[0, 0, 1, 1], words=words)
        block = PDFMapper()._item_to_paragraph({"item": item, "block_id": 1})
        block.type = "acronyms"
        block.language = "pl"
        self.assertEqual([w.text for w in block.words], ["Uniwersalna", "magistrala"])
        context = Block_context(block=block, contents=block.content, language="pl")
        matches = dash_check([context])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].content, "-")

    def test_standalone_hyphen_span_preserves_trailing_space_on_short_line(self):
        mapper = PDFMapper()
        spans = [
            TextSpan(span_id=1, text="•", font="Symbol", size=11.0, bold=False, italic=False, color=0, bbox=[70.0, 200.0, 74.0, 211.0]),
            TextSpan(span_id=2, text="data", font="Arial", size=11.0, bold=False, italic=False, color=0, bbox=[85.0, 200.0, 105.0, 211.0]),
            TextSpan(span_id=3, text="-", font="Arial", size=11.0, bold=False, italic=False, color=0, bbox=[109.0, 200.0, 113.0, 211.0]),
            TextSpan(span_id=4, text="bufor", font="Arial", size=11.0, bold=False, italic=False, color=0, bbox=[117.0, 200.0, 140.0, 211.0]),
            TextSpan(span_id=5, text="wejściowy", font="Arial", size=11.0, bold=False, italic=False, color=0, bbox=[144.0, 200.0, 190.0, 211.0]),
        ]
        line = TextLine(bbox=[70.0, 200.0, 190.0, 211.0], baseline=210.0, spans=spans)
        full_text, _, _ = mapper._extract_words_with_spacing(line, "", [], 27, 0, spans[-1].bbox[2])
        self.assertIn("data - bufor wejściowy", full_text)

    def test_glued_hyphen_suffix_after_math_symbol_has_no_space(self):
        mapper = PDFMapper()
        spans = [
            TextSpan(span_id=1, text="Transformatą", font="LMREgular", size=11.0, bold=False, italic=False, color=0, bbox=[70.0, 300.0, 135.0, 311.0]),
            TextSpan(span_id=2, text="Fouriera", font="LMRegular", size=11.0, bold=False, italic=False, color=0, bbox=[139.0, 300.0, 180.0, 311.0]),
            TextSpan(span_id=3, text="(𝔽", font="MSBM10", size=11.0, bold=False, italic=False, color=0, bbox=[184.0, 300.0, 196.0, 311.0]),
            TextSpan(span_id=4, text="-transformatą)", font="LMRegular", size=11.0, bold=False, italic=False, color=0, bbox=[196.2, 300.0, 265.0, 311.0]),
        ]
        line = TextLine(bbox=[70.0, 300.0, 265.0, 311.0], baseline=310.0, spans=spans)
        full_text, words_info, _ = mapper._extract_words_with_spacing(line, "", [], 15, 0, spans[-1].bbox[2])
        self.assertIn("(𝔽-transformatą)", full_text)
        block = ParagraphBlock(block_id=1, content=full_text, words=words_info)
        block.language = "pl"
        ctx = Block_context(block=block, contents=block.content, language="pl")
        self.assertEqual(dash_check([ctx]), [])

    def test_definition_list_with_glued_hyphen_and_formula_ending_item(self):
        def make_item(idx, text, marker="bullet", ends_with_formula=False):
            ws = []
            pos = 0
            for wi, tok in enumerate(text.split(" ")):
                ws.append(word(tok, index=wi, start=pos))
                pos += len(tok) + 1
            return ListItem(
                item_id=idx, marker_type=marker, text=text,
                bbox=[70.0, 200.0 + idx * 15, 250.0, 212.0 + idx * 15],
                words=ws, ends_with_formula=ends_with_formula,
            )

        # Case 1: Definition list where one item has a glued hyphen ("data -bufor wejściowy")
        def_items = [
            make_item(0, "crc - rejestr wynikowy"),
            make_item(1, "i - iteracja po każdym bajcie"),
            make_item(2, "data -bufor wejściowy"),
            make_item(3, "length - długość bufora"),
            make_item(4, "j - iteracja po bitach"),
        ]
        def_block = ListBlock(
            block_id="list_def", content="\n".join(it.text for it in def_items),
            bbox=[70.0, 200.0, 250.0, 280.0], items=def_items,
            words=[w for it in def_items for w in it.words], type="list"
        )
        def_block.language = "pl"
        ctx1 = Block_context(block=def_block, contents=def_block.content, language="pl")
        self.assertEqual(check_coherence_in_list([ctx1], proper_names=[], acronyms={}), [])

        # Case 2: Numbered list where item 2 ends with a display math formula
        math_items = [
            make_item(0, "f jest funkcją przedziałami monotoniczną, tzn. przedział (a, b) można podzielić na skończoną liczbę podprzedziałów takich, że wewnątrz każdego z nich f jest monotoniczna,", marker="number_dot"),
            make_item(1, "f jest funkcją ciągłą na przedziale (a, b) z wyjątkiem skończonej liczby punktów nieciągłości pierwszego rodzaju, przy czym jeżeli t 0 jest takim punktem, to", marker="number_dot", ends_with_formula=True),
            make_item(2, "jest bezwzględnie całkowalna na przedziale (-∞; +∞), tzn. dla t ∈ R funkcję f można przedstawić następująco:", marker="number_dot"),
        ]
        math_block = ListBlock(
            block_id="list_math", content="\n".join(it.text for it in math_items),
            bbox=[70.0, 300.0, 450.0, 420.0], items=math_items,
            words=[w for it in math_items for w in it.words], type="list"
        )
        math_block.language = "pl"
        ctx2 = Block_context(block=math_block, contents=math_block.content, language="pl")
        matches = check_coherence_in_list([ctx2], proper_names=[], acronyms={})
        self.assertEqual([m for m in matches if m.category == "LIST_ENDING"], [])


if __name__ == "__main__":
    unittest.main()
