"""A bracket before a change of font ("DAgger (" + italic "Dataset Aggregation" + ")") is extracted once.

PyMuPDF's word "(Dataset" holds the bracket that ends the regular span; the bracket used to be added to the last word
of that span as well, "DAgger( (Dataset", and the contents entry no longer matched its heading (TOC_mismatch)."""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

import fitz  # noqa: E402

from analysis.extraction.main_extractor import extractPDF  # noqa: E402


def make_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    x, y, size = 72.0, 100.0, 11
    for text, font in (("Algorytm DAgger (", "helv"), ("Dataset Aggregation", "heit"), (")", "helv")):
        page.insert_text((x, y), text, fontname=font, fontsize=size)
        x += fitz.get_text_length(text, fontname=font, fontsize=size)
    doc.save(path)


class BracketBeforeItalicTest(unittest.TestCase):
    def test_the_bracket_is_not_doubled(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "bracket.pdf")
            make_pdf(path)
            doc = extractPDF(path)
        lines = [" ".join(span.text for span in line.spans)
                 for page in doc.pages for block in page.text_blocks for line in block.lines]
        text = " ".join(lines)
        self.assertIn("DAgger (Dataset Aggregation)", text)
        self.assertNotIn("DAgger(", text)


if __name__ == "__main__":
    unittest.main()
