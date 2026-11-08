'''
Testy sprawdzania pozycjonowania podpisów dla obrazków i tabel.
Podpis obrazka powinien znajdować się pod nim (priorytet "below").
Podpis tabeli powinien znajdować się nad nią (priorytet "above").
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.raw_extraction.bare_struct import TextBlock, TextLine, TextSpan
from analysis.extraction.raw_extraction.image_extractor import find_image_description
from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from analysis.extraction.raw_extraction.table_extractor import find_table_description


def make_text_block(text: str, bbox: tuple, block_id: int = 1) -> TextBlock:
    '''Tworzy minimalny blok tekstu ze strukturą wymaganą przez funkcje szukające podpisów.'''
    span = TextSpan(
        span_id=1, text=text, font="Times", size=12.0, color=0,
        bold=False, italic=False, bbox=bbox
    )
    line = TextLine(spans=[span], bbox=bbox, baseline=bbox[3])
    return TextBlock(block_id=block_id, lines=[line], bbox=bbox)


class TestImageCaption(unittest.TestCase):
    '''Testy detekcji podpisów dla obrazków (oczekiwany podpis pod obrazkiem).'''

    def setUp(self):
        # Obrazek na współrzędnych Y od 100 do 200
        self.image_bbox = (100, 100, 300, 200)

    def test_caption_below_image(self):
        # Blok tekstu bezpośrednio pod obrazkiem (odległość < 40)
        blocks = [make_text_block("Rysunek 1. Przykładowy wykres", (100, 210, 300, 230))]
        desc, side = find_image_description(self.image_bbox, blocks)
        self.assertEqual(desc, "Rysunek 1. Przykładowy wykres")
        self.assertEqual(side, "below")

    def test_caption_above_image(self):
        # Blok tekstu nad obrazkiem - jako fallback, jeśli pod spodem nic nie ma
        blocks = [make_text_block("Rysunek 2. Inny wykres", (100, 70, 300, 90))]
        desc, side = find_image_description(self.image_bbox, blocks)
        self.assertEqual(desc, "Rysunek 2. Inny wykres")
        self.assertEqual(side, "above")

    def test_prefers_below_when_both_present(self):
        # Jeśli tekst jest z obu stron, domyślny priorytet (below) wygrywa
        blocks = [
            make_text_block("Rysunek 3. Fałszywy podpis", (100, 70, 300, 90)),
            make_text_block("Rysunek 4. Prawdziwy podpis", (100, 210, 300, 230))
        ]
        desc, side = find_image_description(self.image_bbox, blocks)
        self.assertEqual(desc, "Rysunek 4. Prawdziwy podpis")
        self.assertEqual(side, "below")


class TestTableCaption(unittest.TestCase):
    '''Testy detekcji podpisów dla tabel (oczekiwany podpis nad tabelą).'''

    def setUp(self):
        # Tabela na współrzędnych Y od 100 do 200
        self.table_bbox = (100, 100, 300, 200)

    def test_caption_above_table(self):
        # Blok tekstu bezpośrednio nad tabelą (odległość < 40)
        blocks = [make_text_block("Tabela 1. Wyniki badań", (100, 70, 300, 90))]
        desc, side = find_table_description(self.table_bbox, blocks)
        self.assertEqual(desc, "Tabela 1. Wyniki badań")
        self.assertEqual(side, "above")

    def test_caption_below_table(self):
        # Blok tekstu pod tabelą - jako fallback, jeśli nad nic nie ma
        blocks = [make_text_block("Tabela 2. Dodatkowe dane", (100, 210, 300, 230))]
        desc, side = find_table_description(self.table_bbox, blocks)
        self.assertEqual(desc, "Tabela 2. Dodatkowe dane")
        self.assertEqual(side, "below")

    def test_prefers_above_when_both_present(self):
        # Jeśli tekst jest z obu stron, domyślny priorytet (above) wygrywa
        blocks = [
            make_text_block("Tabela 3. Prawdziwy podpis", (100, 70, 300, 90)),
            make_text_block("Tabela 4. Fałszywy podpis", (100, 210, 300, 230))
        ]
        desc, side = find_table_description(self.table_bbox, blocks)
        self.assertEqual(desc, "Tabela 3. Prawdziwy podpis")
        self.assertEqual(side, "above")

    def test_paragraph_about_the_table_is_not_its_caption(self):
        # Akapit nad podpisem też zaczyna się od słowa "Tabela": podpisem jest blok najbliższy tabeli
        blocks = [
            make_text_block("Tabela 5 prezentuje wyniki pomiarów.", (100, 40, 300, 60), block_id=1),
            make_text_block("Tabela 5. Wyniki pomiarów", (100, 75, 300, 90), block_id=2)
        ]
        desc, side = find_table_description(self.table_bbox, blocks)
        self.assertEqual(desc, "Tabela 5. Wyniki pomiarów")
        self.assertEqual(side, "above")

    def test_caption_continued_in_the_next_block(self):
        blocks = [
            make_text_block("Tabela 6. Bardzo długi podpis", (100, 60, 300, 75), block_id=1),
            make_text_block("w dwóch blokach", (100, 80, 300, 95), block_id=2)
        ]
        desc, _ = find_table_description(self.table_bbox, blocks)
        self.assertEqual(desc, "Tabela 6. Bardzo długi podpis w dwóch blokach")


class TestTableCaptionPattern(unittest.TestCase):
    '''Podpis tabeli jest osobnym blokiem, także gdy po słowie "Tabela" stoi kropka.'''

    def test_caption_forms(self):
        for caption in ("Tabela 2.1. Wyniki", "Tabela. 2.1. Wyniki", "Tab. 2.1. Wyniki", "Table 1. Results", "Table. 1. Results"):
            self.assertTrue(PDFMapper.TAB_PATTERN.match(caption), caption)

    def test_ordinary_sentence(self):
        self.assertFalse(PDFMapper.TAB_PATTERN.match("Tabela przedstawia wyniki"))


if __name__ == "__main__":
    unittest.main()