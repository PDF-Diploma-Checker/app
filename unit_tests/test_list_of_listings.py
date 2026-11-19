import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.extraction.raw_extraction.front_and_back_matter import TableOfFiguresExtractor, TableOfTablesExtractor


def _line(text, y0):
    return NS(spans=[NS(text=text)], bbox=(88, y0, 500, y0 + 10))


def _page(number, *lines):
    return NS(number=number, text_blocks=[NS(lines=[_line(text, y) for text, y in lines])], height=842, width=595)


class ListOfListingsTest(unittest.TestCase):
    def test_list_of_listings_on_the_next_page_is_not_read_as_tables(self):
        pages = [
            _page(80, ("WYKAZ TABEL", 103), ("4.1 Parametry serwomechanizmu . . . 44", 136), ("5.1 Wyniki pomiarów . . . 60", 150)),
            _page(81, ("WYKAZ LISTINGÓW", 103), ("4.1 Konfiguracja projektu oprogramowania . . . 45", 136),
                  ("4.2 Uproszczona funkcja apply_masks() . . . 61", 150)),
        ]
        tot = TableOfTablesExtractor().extract(pages, [])
        self.assertEqual(tot.page_nums, [80])
        self.assertEqual([entry.title for entry in tot.entries], ["Parametry serwomechanizmu", "Wyniki pomiarów"])

    def test_list_of_listings_on_the_same_page_ends_the_list_of_figures(self):
        pages = [_page(79, ("SPIS RYSUNKÓW", 103), ("1.1 Schemat . . . 10", 136), ("1.2 Model . . . 12", 150),
                       ("SPIS LISTINGÓW", 300), ("1.1 Konfiguracja . . . 11", 330), ("1.2 Funkcja main . . . 13", 345))]
        tof = TableOfFiguresExtractor().extract(pages, [])
        self.assertEqual([entry.title for entry in tof.entries], ["Schemat", "Model"])


if __name__ == "__main__":
    unittest.main()
