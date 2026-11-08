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

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, ListItem, WordInfo
from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from analysis.modules.linguistics.dash_check import dash_check
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


if __name__ == "__main__":
    unittest.main()
