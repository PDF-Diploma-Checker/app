"""A centred caption broken in a word at the line end: its second line is a block of its own in the PDF. The two are
one caption and the word is one word ("Tabela 9.1. ... na 32 środo-" / "wiskach, ..." on page 70 of a thesis)."""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

import fitz  # noqa: E402


def extract(build):
    from analysis.extraction.main_extractor import extractPDF
    from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "caption.pdf")
        doc = fitz.open()
        page = doc.new_page()
        build(page)
        doc.save(path)
        doc.close()
        return PDFMapper().map_to_schema(extractPDF(path))


class CaptionHyphenTest(unittest.TestCase):
    def test_a_caption_broken_in_a_word_is_one_text_and_the_word_one_word(self):
        def build(page):
            page.insert_textbox(fitz.Rect(72, 80, 523, 140), "Ordinary text of the thesis before the table, long enough "
                                "to be a paragraph of its own and nothing more.", fontsize=11, fontname="Times-Roman")
            page.insert_text((99, 200), "Tabela 9.1. Skladniki nagrody polityki. Polityka uczona byla na 32 srodo-",
                             fontsize=10, fontname="Times-Roman")
            page.insert_text((180, 214), "wiskach, z krokiem uczenia 0,0003.", fontsize=10, fontname="Times-Roman")
            page.insert_text((99, 400), "Tabela 9.2. Weryfikacja otwierania drzwi.", fontsize=10, fontname="Times-Roman")

        mapped = extract(build)
        captions = [b for b in mapped.logical_blocks if b.content.startswith("Tabela 9.1")]
        self.assertEqual(len(captions), 1)
        self.assertIn("32 srodowiskach, z krokiem", captions[0].content)
        word = next(w for w in captions[0].words if w.text.startswith("srodo"))
        self.assertEqual(word.text, "srodowiskach,")
        self.assertEqual(len(word.extra_boxes), 1)
        self.assertFalse(any(b.content.startswith("wiskach") for b in mapped.logical_blocks))
        # the next caption stays apart
        self.assertTrue(any(b.content.startswith("Tabela 9.2") for b in mapped.logical_blocks))

    def test_a_caption_ending_normally_is_closed(self):
        def build(page):
            page.insert_text((99, 200), "Tabela 1.1. Wyniki uczenia.", fontsize=10, fontname="Times-Roman")
            page.insert_textbox(fitz.Rect(72, 230, 523, 300), "the text after the caption is not part of it and starts "
                                "a paragraph of its own.", fontsize=11, fontname="Times-Roman")

        mapped = extract(build)
        caption = next(b for b in mapped.logical_blocks if b.content.startswith("Tabela 1.1"))
        self.assertEqual(caption.content.strip(), "Tabela 1.1. Wyniki uczenia.")


if __name__ == "__main__":
    unittest.main()
