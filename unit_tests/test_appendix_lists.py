import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.extraction.raw_extraction.front_and_back_matter import TableOfTablesExtractor
from analysis.extraction.raw_extraction.image_extractor import _box_of_figure
from analysis.modules.redaction.redaction_validator import _listed_caption_on_page


def _line(text, x0, y0):
    return NS(spans=[NS(text=text)], bbox=(x0, y0, x0 + 300, y0 + 10))


def _page(number, *lines):
    return NS(number=number, text_blocks=[NS(lines=[_line(*line) for line in lines])], height=842, width=595)


class ListBeforeAppendixTest(unittest.TestCase):
    def test_list_of_tables_stops_before_an_appendix_with_a_flowchart(self):
        pages = [
            _page(55, ("WYKAZ TABEL", 71, 103), ("2.1 Cechy widm drgań . . . 15", 88, 136), ("5.2 Budowa ramki . . . 44", 88, 305)),
            _page(56, ("DODATEK A: SCHEMATY BLOKOWE", 99, 103), ("A.1 Kontrola CRC Start crc = 0xFFFF i = 0", 293, 231)),
        ]
        tot = TableOfTablesExtractor().extract(pages, [])
        self.assertEqual(tot.page_nums, [55])
        self.assertEqual([entry.number for entry in tot.entries], ["2.1", "5.2"])

    def test_list_going_on_on_the_next_page_is_still_read(self):
        pages = [
            _page(5, ("SPIS TABEL", 71, 103), ("1.1 Pierwsza . . . 10", 88, 136), ("1.2 Druga . . . 12", 88, 150)),
            _page(6, ("1.3 Trzecia . . . 14", 88, 80), ("1.4 Czwarta . . . 20", 88, 95)),
        ]
        tot = TableOfTablesExtractor().extract(pages, [])
        self.assertEqual(tot.page_nums, [5, 6])
        self.assertEqual(len(tot.entries), 4)


class BoxOfFlowchartTest(unittest.TestCase):
    def test_box_without_a_caption_inside_a_flowchart_is_part_of_it(self):
        box = NS(bbox=(210, 414, 414, 442), description="")
        self.assertTrue(_box_of_figure(fitz.Rect(185, 178, 439, 640), box.bbox, [box]))

    def test_table_with_a_caption_is_kept(self):
        table = NS(bbox=(210, 414, 414, 442), description="Tabela 1. Wyniki")
        self.assertFalse(_box_of_figure(fitz.Rect(185, 178, 439, 640), table.bbox, [table]))

    def test_table_about_the_size_of_the_drawing_is_kept(self):
        table = NS(bbox=(100, 100, 400, 300), description="")
        self.assertFalse(_box_of_figure(fitz.Rect(95, 95, 405, 310), table.bbox, [table]))


class CaptionWithADotAfterTheWordTest(unittest.TestCase):
    def test_table_caption_written_tabela_dot_is_found(self):
        page = NS(images=[], tables=[NS(description="Tabela. 2.1. Charakterystyczne cechy widm drgań")], text_blocks=[])
        entry = NS(title="Charakterystyczne cechy widm drgań", number="2.1")
        self.assertTrue(_listed_caption_on_page(page, entry, "table"))

    def test_another_table_number_is_not_taken(self):
        page = NS(images=[], tables=[NS(description="Tabela. 2.2. Charakterystyczne cechy widm drgań")], text_blocks=[])
        entry = NS(title="Charakterystyczne cechy widm drgań", number="2.1")
        self.assertFalse(_listed_caption_on_page(page, entry, "table"))


if __name__ == "__main__":
    unittest.main()
