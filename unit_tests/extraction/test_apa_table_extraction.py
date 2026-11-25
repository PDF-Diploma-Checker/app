"""APA (booktabs) tables with standard LaTeX 12pt column gaps are extracted completely,
so their rows never leak into paragraphs as false-positive widows."""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

import fitz

from analysis.extraction.linguistics_conversion.converter_linguistics_clean import (
    PDFMapper,
)
from analysis.extraction.main_extractor import extractPDF


def _draw_apa_table(page, x0, y0, x1, caption, rows, col_xs):
    page.insert_text((85, y0 - 14), caption, fontsize=9, fontname="helv")
    page.draw_line((x0, y0), (x1, y0), width=0.8)
    header_y = y0 + 13
    for cx, text in zip(col_xs, rows[0]):
        page.insert_text((cx, header_y), text, fontsize=9, fontname="helv")
    midrule_y = y0 + 20
    page.draw_line((x0, midrule_y), (x1, midrule_y), width=0.5)
    y = midrule_y + 13
    for row in rows[1:]:
        for cx, text in zip(col_xs, row):
            page.insert_text((cx, y), text, fontsize=9, fontname="helv")
        y += 14
    page.draw_line((x0, y - 4), (x1, y - 4), width=0.8)
    return y


class ApaTableExtractionTest(unittest.TestCase):
    def test_booktabs_table_with_12pt_column_gaps_has_no_widow_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "apa_12pt.pdf")
            doc = fitz.open()
            page = doc.new_page()
            # 12pt gaps between column headers (standard LaTeX 2*\tabcolsep)
            _draw_apa_table(
                page,
                x0=102.8,
                y0=235.3,
                x1=492.5,
                caption="Tabela 6.10. Etapy z przeszkodami.",
                rows=[
                    ["Etap", "Maks. poziom", "Prog", "Iteracje", "Pula terenow"],
                    ["E6", "0,30", "0,40", "436", "przeszkody 64%, plaski 9%, pozostale po 4,5%"],
                    ["E7", "1,00", "-", "33 050", "przeszkody 40%, mieszany 20%, pozostale po 6,7%"],
                ],
                col_xs=[108.8, 139.2, 206.4, 237.3, 278.7],
            )
            doc.save(path)
            doc.close()

            dd = extractPDF(path)
            self.assertEqual(len(dd.pages[0].tables), 1)
            table = dd.pages[0].tables[0]
            self.assertEqual(table.table_type, "apa")
            self.assertEqual(table.row_count, 3)

            mapped = PDFMapper().map_to_schema(dd)
            widows = [b for b in mapped.logical_blocks if getattr(b, "is_widow", 0) > 0]
            self.assertEqual(widows, [])

    def test_two_apa_tables_separated_by_caption_stay_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "two_apa.pdf")
            doc = fitz.open()
            page = doc.new_page()
            _draw_apa_table(
                page,
                x0=101.4,
                y0=92.2,
                x1=493.8,
                caption="Tabela 5.1. Parametry.",
                rows=[["Parametr", "Wartosc"], ["Krok", "0,02"], ["Gamma", "0,99"]],
                col_xs=[108.0, 220.0],
            )
            page.insert_text((85, 310), "Akapit opisujacy druga tabele na tej samej stronie.", fontsize=10, fontname="helv")
            _draw_apa_table(
                page,
                x0=97.3,
                y0=360.0,
                x1=498.0,
                caption="Tabela 5.2. Kody modeli.",
                rows=[["Kod", "Opis"], ["P10", "Model bazowy"], ["E7", "Model z przeszkodami"]],
                col_xs=[103.3, 180.0],
            )
            doc.save(path)
            doc.close()

            dd = extractPDF(path)
            apa_tables = [t for t in dd.pages[0].tables if t.table_type == "apa"]
            self.assertEqual(len(apa_tables), 2)
            self.assertEqual([t.row_count for t in apa_tables], [3, 3])


if __name__ == "__main__":
    unittest.main()
