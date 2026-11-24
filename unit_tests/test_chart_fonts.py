"""The text inside figures and charts is not text of the thesis: its fonts and sizes do not count in the font checks."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.extraction.raw_extraction.bare_struct import (
    DocumentData, ImageInfo, PageData, TextBlock, TextLine, TextSpan,
)


def _block(text, font, size, bbox):
    span = TextSpan(span_id=0, text=text, font=font, size=size, color=0, bold=False, italic=False, bbox=bbox)
    return TextBlock(block_id=0, lines=[TextLine(spans=[span], bbox=bbox, baseline=0.0)], bbox=bbox)


def _page(blocks, images):
    return PageData(number=1, width=595, height=842, orientation="vertical", format="a4", margins={},
                    text_blocks=blocks, images=images)


def _image(bbox, kind="vector"):
    return ImageInfo(path="x.png", bbox=bbox, width=10, height=10, image_type=kind, description="")


class ChartFontsTest(unittest.TestCase):
    def test_chart_text_is_not_counted(self):
        body = [_block("Treść", "TimesNewRoman", 12.0, (72, 100, 300, 112)) for _ in range(3)]
        chart = [_block("Oś X", "DejaVuSans", 8.0, (100, 400, 140, 410)), _block("Oś Y", "DejaVuSans", 8.0, (80, 300, 90, 340))]
        document = DocumentData(metadata={}, pages=[_page(body + chart, [_image((70, 280, 500, 430))])])
        self.assertEqual(document.get_font_usage(), {"TimesNewRoman": 3})
        self.assertEqual(document.get_font_size_usage(), {12.0: 3})
        self.assertEqual((document.get_most_common_font(), document.get_most_common_font_size()), ("TimesNewRoman", 12.0))

    def test_raster_figures_too(self):
        chart = [_block("podpis na skanie", "Arial", 7.0, (100, 400, 140, 410))]
        body = [_block("Treść", "TimesNewRoman", 12.0, (72, 100, 300, 112))]
        document = DocumentData(metadata={}, pages=[_page(body + chart, [_image((70, 280, 500, 430), "raster")])])
        self.assertEqual(document.get_font_usage(), {"TimesNewRoman": 1})

    def test_text_next_to_a_chart_still_counts(self):
        caption = _block("Rysunek 1. Wykres", "TimesNewRoman", 10.0, (100, 440, 300, 450))     # below the chart
        document = DocumentData(metadata={}, pages=[_page([caption], [_image((70, 280, 500, 430))])])
        self.assertEqual(document.get_font_usage(), {"TimesNewRoman": 1})

    def test_a_drawing_that_covers_the_page_is_no_chart(self):
        body = [_block("Treść", "TimesNewRoman", 12.0, (72, 100, 300, 112))]
        document = DocumentData(metadata={}, pages=[_page(body, [_image((0, 0, 595, 842))])])       # a frame
        self.assertEqual(document.get_font_usage(), {"TimesNewRoman": 1})

    def test_page_without_figures_is_unchanged(self):
        body = [_block("A", "TimesNewRoman", 12.0, (72, 100, 300, 112)), _block("B", "Arial", 12.0, (72, 120, 300, 132))]
        document = DocumentData(metadata={}, pages=[_page(body, [])])
        self.assertEqual(document.get_font_usage(), {"TimesNewRoman": 1, "Arial": 1})


if __name__ == "__main__":
    unittest.main()
