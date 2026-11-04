'''A highlight over a word of the caption must not make the figure swallow its caption.'''
import os
import sys
import tempfile
import unittest
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.main_extractor import extractPDF


def _thesis(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i, height in enumerate((120, 80, 150, 60)):     # a chart made of paths
        page.draw_rect(fitz.Rect(150 + i * 70, 260 - height, 200 + i * 70, 260), fill=(0.2, 0.4, 0.7), color=(0.2, 0.4, 0.7))
    page.insert_text((150, 290), "Rysunek 1: Wyniki ankiety przedstawione w tabeli", fontsize=11)
    page.insert_text((70, 330), "Na rysunku 1 przedstawiono wyniki ankiety, a dalej znajduje się opis.", fontsize=11)
    for rect in (fitz.Rect(360, 280, 385, 293), fitz.Rect(100, 320, 150, 333)):     # highlights left by a reviewer
        page.draw_rect(rect, fill=(1, 1, 0), color=None, overlay=False)
    doc.save(path)


class HighlightedCaptionTest(unittest.TestCase):
    def test_caption_stays_outside_the_figure(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                _thesis("thesis.pdf")
                images = extractPDF("thesis.pdf").pages[0].images
            finally:
                os.chdir(cwd)
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].description.startswith("Rysunek 1"))
        self.assertLess(images[0].bbox[3], 285)


if __name__ == "__main__":
    unittest.main()
