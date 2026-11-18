import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.extraction.raw_extraction.front_and_back_matter import TableOfFiguresExtractor


def _line(text, x0, y0, y1):
    return NS(spans=[NS(text=text)], bbox=(x0, y0, x0 + 300, y1))


class RaisedTitleTest(unittest.TestCase):
    def test_title_with_a_formula_raised_above_its_number_stays_one_entry(self):
        # LaTeX sets "sin(2π⋅50t)" a little higher, so the title starts 2 pt above its number and page
        lines = [
            _line("WYKAZ RYSUNKÓW", 71, 103, 115),
            _line("5.1.", 117, 482, 492), _line("Architektura oprogramowania . . . .", 142, 482, 492), _line("41", 513, 482, 492),
            _line("5.2.", 117, 498, 508), _line("Transformata FFT dla sin (2𝜋⋅50 𝑡) . . . .", 142, 496, 508), _line("44", 513, 498, 508),
            _line("6.1.", 117, 523, 533), _line("Symulacja niewyważenia wału . . . .", 143, 523, 533), _line("47", 513, 523, 533),
        ]
        page = NS(number=54, text_blocks=[NS(lines=lines)], height=842, width=595)
        tof = TableOfFiguresExtractor().extract([page], [])
        self.assertEqual([(entry.number, entry.page) for entry in tof.entries], [("5.1", 41), ("5.2", 44), ("6.1", 47)])
        self.assertEqual(tof.entries[2].title, "Symulacja niewyważenia wału")


if __name__ == "__main__":
    unittest.main()
