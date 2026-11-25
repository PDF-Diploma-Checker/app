"""A word hyphenated at the end of a line ("Ope-" / "nUSD") is one word ("OpenUSD"): one finding, highlighted on
both lines."""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

import fitz  # noqa: E402

from analysis.extraction.linguistics_conversion.schema import (  # noqa: E402
    WordInfo, is_bekart_func, is_widow_func, word_pieces,
)
from analysis.modules.linguistics.helpers import get_match_info  # noqa: E402


def w(index, text, start, page, line, x0, extra=()):
    return WordInfo(word_index=index, text=text, start_char=start, end_char=start + len(text), font="Times",
                    size=12, bold=False, italic=False, bbox=[x0, line * 20, x0 + 40, line * 20 + 10],
                    page_number=page, line=line, extra_boxes=list(extra))


class Block:
    def __init__(self, words):
        self.words = words


class FindingTest(unittest.TestCase):
    def test_a_finding_on_a_hyphenated_word_has_a_box_on_each_line(self):
        # "Ala OpenUSD ma": "Ope-" ends line 1, "nUSD" starts line 2
        words = [w(0, "Ala", 0, 0, 1, 400), w(1, "OpenUSD", 4, 0, 1, 450, [(0, 2, [85, 40, 110, 50])]),
                 w(2, "ma", 12, 0, 2, 120)]
        _, _, idxs, coords, _ = get_match_info(Block(words), 4, 7)
        self.assertEqual(idxs, [1])                         # one word
        self.assertEqual(len(coords), 2)                    # two highlights

    def test_both_parts_get_a_box_also_with_the_same_line_number(self):
        # a centred caption: its second line is another block of the PDF, so both parts have line 0
        words = [w(0, "srodowiskach,", 0, 0, 0, 500, [(0, 0, [146, 40, 181, 50])])]
        coords = get_match_info(Block(words), 0, 13)[3]
        self.assertEqual(len(coords), 2)
        self.assertLess(coords[0]["coordinates"][1], coords[1]["coordinates"][1])      # the first part first

    def test_a_word_without_a_line_break_has_one_box(self):
        words = [w(0, "Ala", 0, 0, 1, 400), w(1, "kot", 4, 0, 1, 450)]
        self.assertEqual(len(get_match_info(Block(words), 4, 3)[3]), 1)


class LinesTest(unittest.TestCase):
    def test_pieces_are_in_reading_order(self):
        words = [w(0, "konstrukcja.", 0, 0, 1, 450, [(0, 2, [85, 40, 130, 50])])]
        self.assertEqual([(p[0], p[1]) for p in word_pieces(words)], [(0, 1), (0, 2)])

    def test_the_rest_of_a_hyphenated_word_alone_on_the_last_line_is_a_widow(self):
        words = [w(i, f"s{i}", i * 3, 0, 1, 85 + i * 45) for i in range(8)]
        words.append(w(8, "konstrukcja.", 24, 0, 1, 445, [(0, 2, [85, 40, 130, 50])]))
        self.assertEqual(is_widow_func(words), 1)

    def test_the_rest_of_a_hyphenated_word_on_the_next_page_is_a_bastard(self):
        words = [w(i, f"s{i}", i * 3, 0, 1, 85 + i * 45) for i in range(8)]
        words.append(w(8, "konstrukcja.", 24, 0, 1, 445, [(1, 0, [85, 40, 130, 50])]))
        self.assertEqual(is_bekart_func(words), 1)


class ExtractionTest(unittest.TestCase):
    def test_the_parts_are_joined_into_one_word(self):
        from analysis.extraction.main_extractor import extractPDF
        from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
        # the base fonts of PyMuPDF have no Polish letters, so the text is English
        text = ("This paragraph describes a scene that was saved in the format called Ope-\n"
                "nUSD and then it simply goes on with ordinary text across several\n"
                "lines so that it looks like a real paragraph of a thesis written by someone.")
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "hyphen.pdf")
            doc = fitz.open()
            page = doc.new_page()
            page.insert_textbox(fitz.Rect(72, 90, 523, 200), text, fontsize=11, fontname="Times-Roman", align=3)
            doc.save(path)
            doc.close()
            mapped = PDFMapper().map_to_schema(extractPDF(path))
        words = [word for block in mapped.logical_blocks for word in getattr(block, "words", None) or []]
        texts = [word.text for word in words]
        self.assertIn("OpenUSD", texts)
        self.assertNotIn("nUSD", texts)
        joined = words[texts.index("OpenUSD")]
        self.assertEqual(len(joined.extra_boxes), 1)
        page_number, line, bbox = joined.extra_boxes[0]
        self.assertGreater(bbox[1], joined.bbox[3] - 1)     # the second part is on the next line
        self.assertLess(bbox[0], joined.bbox[0])


class SameRowInlineMathMergeTest(unittest.TestCase):
    def test_merges_tail_block_with_hyphenated_word_even_when_sorted_first(self):
        from analysis.extraction.raw_extraction.bare_struct import TextBlock, TextLine, TextSpan
        from analysis.extraction.raw_extraction.text_extractor import merge_same_row_inline_math_blocks

        tail = TextBlock(
            block_id=21,
            lines=[
                TextLine(
                    spans=[TextSpan(1, "𝑡", "LatinModernMath-Regular", 7.0, 0, False, False, (458.2, 468.7, 461.2, 475.6))],
                    bbox=(458.2, 468.7, 461.2, 475.6),
                    baseline=475.6,
                ),
                TextLine(
                    spans=[TextSpan(2, "defi-", "ArialMT", 10.0, 0, False, False, (492.5, 464.1, 511.9, 474.0))],
                    bbox=(492.5, 464.1, 511.9, 474.0),
                    baseline=474.0,
                ),
            ],
            bbox=(458.2, 464.1, 511.9, 475.6),
        )
        main = TextBlock(
            block_id=22,
            lines=[
                TextLine(
                    spans=[
                        TextSpan(3, "Estymator", "ArialMT", 10.0, 0, False, False, (403.1, 463.7, 448.0, 474.0)),
                        TextSpan(4, "𝐴̂", "LatinModernMath-Regular", 10.0, 0, False, False, (450.7, 463.7, 458.2, 473.7)),
                        TextSpan(5, "GAE", "ArialMT", 7.0, 0, False, False, (458.2, 461.2, 472.9, 468.2)),
                        TextSpan(6, "(𝛾, 𝜆)", "LatinModernMath-Regular", 7.0, 0, False, False, (472.9, 461.0, 489.2, 468.0)),
                    ],
                    bbox=(85.0, 461.0, 489.2, 476.5),
                    baseline=474.0,
                ),
            ],
            bbox=(85.0, 461.0, 489.2, 476.5),
        )

        merged = merge_same_row_inline_math_blocks([tail, main])
        self.assertEqual(len(merged), 1)
        texts = [s.text for s in merged[0].lines[0].spans]
        self.assertEqual(texts[0], "Estymator")
        self.assertEqual(texts[-1], "defi-")

    def test_does_not_merge_separated_columns(self):
        from analysis.extraction.raw_extraction.bare_struct import TextBlock, TextLine, TextSpan
        from analysis.extraction.raw_extraction.text_extractor import merge_same_row_inline_math_blocks

        col1 = TextBlock(
            block_id=1,
            lines=[TextLine([TextSpan(1, "Etap", "ArialMT", 9.0, 0, False, False, (108.8, 242.1, 127.2, 251.1))],
                            (108.8, 242.1, 127.2, 251.1), 251.1)],
            bbox=(108.8, 242.1, 127.2, 251.1),
        )
        col2 = TextBlock(
            block_id=2,
            lines=[TextLine([TextSpan(2, "Maks. poziom", "ArialMT", 9.0, 0, False, False, (139.2, 242.1, 194.5, 251.1))],
                            (139.2, 242.1, 194.5, 251.1), 251.1)],
            bbox=(139.2, 242.1, 194.5, 251.1),
        )

        merged = merge_same_row_inline_math_blocks([col1, col2])
        self.assertEqual(len(merged), 2)


if __name__ == "__main__":
    unittest.main()
