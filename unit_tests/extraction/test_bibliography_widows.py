import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from analysis.extraction.linguistics_conversion.schema import (
    ListBlock,
    ListItem,
    WordInfo,
    ends_with_link,
    is_widow_func,
)


def _words(*lines):
    return [
        SimpleNamespace(text=text, page_number=1, line=number, is_index=False)
        for number, line in enumerate(lines)
        for text in line.split()
    ]


def _flag(*lines):
    item = SimpleNamespace(words=_words(*lines), is_widow=0)
    mapper = PDFMapper.__new__(PDFMapper)
    mapper.logical_blocks = [SimpleNamespace(is_bibliography=True, items=[item])]
    mapper._flag_bibliography_widows()
    return item.is_widow


class BibliographyWidowTest(unittest.TestCase):
    def test_end_of_a_broken_url_is_not_a_widow(self):
        self.assertEqual(_flag("[1] J. Kowalski, Tytuł artykułu, https://example.com/sciezka/", "do-pliku.html"), 0)

    def test_end_of_a_broken_doi_is_not_a_widow(self):
        self.assertEqual(_flag("[2] J. Kowalski, Tytuł artykułu, doi: 10.1000/abc-", "def.2020"), 0)
        self.assertEqual(_flag("[3] J. Kowalski, Tytuł artykułu, https://doi.org/10.1000/", "abc-def"), 0)

    def test_url_broken_over_three_lines(self):
        self.assertEqual(_flag("[4] J. Kowalski, Tytuł, https://example.com/bardzo/", "dluga/sciezka/", "koniec"), 0)

    def test_whole_url_or_doi_on_the_last_line(self):
        self.assertEqual(_flag("[5] J. Kowalski, Tytuł artykułu w czasopiśmie,", "https://example.com/plik"), 0)
        self.assertEqual(_flag("[6] J. Kowalski, Tytuł artykułu w czasopiśmie,", "DOI: 10.1000/abc"), 0)

    def test_ordinary_short_last_line_is_still_a_widow(self):
        self.assertEqual(_flag("[7] J. Kowalski, Bardzo długi tytuł artykułu w czasopiśmie", "naukowym, 2020."), 2)

    def test_text_after_a_finished_link_is_still_a_widow(self):
        self.assertEqual(_flag("[8] J. Kowalski, Tytuł, https://example.com/plik,", "2020."), 1)

    def test_link_earlier_in_the_entry_does_not_excuse_a_widow(self):
        self.assertEqual(_flag("[9] https://example.com/plik, tytuł bardzo długiego artykułu", "naukowym, 2020."), 2)

    def test_paragraph_check_is_unchanged(self):
        words = _words("Na stronie https://example.com/sciezka/", "koniec")
        self.assertEqual(is_widow_func(words), 1)
        self.assertTrue(ends_with_link(words))


class WordAndLinkJoiningTest(unittest.TestCase):
    def test_same_line_and_multiline_url_joining(self):
        text = "AUTODESK. [data dostępu 2026-11-03]. Dostępne z: https : //www.autodesk.com/products/overview."
        words = [
            WordInfo(0, "54.", 0, 0, "ArialMT", 10.0, False, False, [99.0, 736.0, 113.0, 746.0], 1, 1),
            WordInfo(1, "AUTODESK.", 0, 9, "ArialMT", 10.0, False, False, [123.0, 736.0, 181.0, 746.0], 1, 1),
            WordInfo(2, "[data", 10, 15, "ArialMT", 10.0, False, False, [306.0, 736.0, 328.0, 746.0], 1, 1),
            WordInfo(3, "dostępu", 16, 23, "ArialMT", 10.0, False, False, [333.0, 736.0, 369.0, 746.0], 1, 1),
            WordInfo(4, "2026-11-03].", 24, 36, "ArialMT", 10.0, False, False, [373.0, 736.0, 430.0, 746.0], 1, 1),
            WordInfo(5, "Dostępne", 37, 45, "ArialMT", 10.0, False, False, [434.0, 736.0, 477.0, 746.0], 1, 1),
            WordInfo(6, "z:", 46, 48, "ArialMT", 10.0, False, False, [481.0, 736.0, 489.0, 746.0], 1, 1),
            WordInfo(7, "https", 49, 54, "LMMono10-Regular", 10.0, False, False, [494.0, 734.0, 520.2, 747.0], 1, 1),
            WordInfo(8, ":", 55, 56, "LMMono10-Regular", 10.0, False, False, [521.8, 734.0, 527.0, 747.0], 1, 1),
            WordInfo(9, "//www.autodesk.com/products/overview.", 57, 94, "LMMono10-Regular", 10.0, False, False, [122.5, 749.0, 371.0, 762.0], 1, 1),
        ]
        item = ListItem(item_id=0, marker_type="number_dot", text=text, bbox=[99.0, 734.0, 527.0, 762.0], words=list(words))
        block = ListBlock(block_id="list_1", content=text, bbox=item.bbox, is_bibliography=True, items=[item], words=list(words))
        mapper = PDFMapper()
        mapper.logical_blocks = [block]
        mapper._fix_offsets()

        self.assertEqual(
            item.text,
            "AUTODESK. [data dostępu 2026-11-03]. Dostępne z: https://www.autodesk.com/products/overview.",
        )
        self.assertEqual(item.words[-2].text, "https:")
        self.assertEqual(item.words[-1].text, "//www.autodesk.com/products/overview.")
        self.assertEqual(item.text[item.words[-2].start_char:item.words[-1].end_char], "https://www.autodesk.com/products/overview.")

    def test_cross_line_soft_hyphen_removed_in_list_item(self):
        text = "WIPO. [data do-stępu 2026-05-21]."
        words = [
            WordInfo(0, "29.", 0, 0, "ArialMT", 10.0, False, False, [76.0, 215.0, 90.0, 225.0], 1, 1),
            WordInfo(1, "WIPO.", 0, 5, "ArialMT", 10.0, False, False, [94.0, 215.0, 125.0, 225.0], 1, 1),
            WordInfo(2, "[data", 6, 11, "ArialMT", 10.0, False, False, [458.0, 215.0, 480.0, 225.0], 1, 1),
            WordInfo(3, "do-", 12, 15, "ArialMT", 10.0, False, False, [483.0, 215.0, 497.0, 225.0], 1, 1),
            WordInfo(4, "stępu", 15, 20, "ArialMT", 10.0, False, False, [94.0, 230.0, 119.0, 240.0], 1, 2),
            WordInfo(5, "2026-05-21].", 21, 33, "ArialMT", 10.0, False, False, [122.0, 230.0, 180.0, 240.0], 1, 2),
        ]
        item = ListItem(item_id=0, marker_type="number_dot", text=text, bbox=[76.0, 215.0, 497.0, 240.0], words=list(words))
        block = ListBlock(block_id="list_1", content=text, bbox=item.bbox, is_bibliography=True, items=[item], words=list(words))
        mapper = PDFMapper()
        mapper.logical_blocks = [block]
        mapper._fix_offsets()

        self.assertEqual(item.text, "WIPO. [data dostępu 2026-05-21].")
        self.assertEqual(item.text[item.words[3].start_char:item.words[3].end_char], "do")
        self.assertEqual(item.text[item.words[4].start_char:item.words[4].end_char], "stępu")
        self.assertEqual(item.text[item.words[5].start_char:item.words[5].end_char], "2026-05-21].")


if __name__ == "__main__":
    unittest.main()
