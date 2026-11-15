"""Included PDF charts must remain complete figures, not ordinary thesis text."""
import os
from pathlib import Path
import sys
import tempfile
import shutil
import subprocess
from types import SimpleNamespace
import unittest

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from analysis.extraction.main_extractor import extractPDF
from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from analysis.modules.llm.image_analysis.figures import collect_figures
from analysis.modules.redaction.redaction_validator import RedactionValidator


def chart_pdf(grid=False, text_only=False):
    source = fitz.open()
    page = source.new_page(width=300, height=160)
    if not text_only:
        page.draw_rect(fitz.Rect(30, 20, 280, 125), color=(0, 0, 0))
        if grid:
            for x in (80, 130, 180, 230):
                page.draw_line((x, 20), (x, 125))
            for y in (45, 70, 95):
                page.draw_line((30, y), (280, y))
        else:
            page.draw_polyline([(35, 110), (90, 60), (180, 90), (270, 30)], color=(0, .3, .8))
    page.insert_text((35, 145), 'A long chart legend outside the path bounds', fontsize=9)
    return source


class EmbeddedPdfFiguresTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.directory.name)

    def tearDown(self):
        os.chdir(self.cwd)
        self.directory.cleanup()

    def extract(self, source, caption='Rysunek 1. Wyniki pomiarow', rotate=0):
        with fitz.open() as thesis:
            page = thesis.new_page()
            page.show_pdf_page(fitz.Rect(80, 100, 500, 330), source, 0, rotate=rotate)
            page.insert_text((80, 355), caption, fontsize=11)
            page.insert_text((80, 400), 'A real body paragraph outside the figure.', fontsize=11)
            thesis.save('thesis.pdf')
        return extractPDF('thesis.pdf')

    def test_pdf_only_figure_includes_legend_and_keeps_caption_outside(self):
        with chart_pdf() as source:
            data = self.extract(source)
        images = data.pages[0].images
        self.assertEqual(len(images), 1)
        image = images[0]
        self.assertTrue(image.description.startswith('Rysunek 1.'))
        self.assertGreater(image.bbox[3], 320)
        self.assertLess(image.bbox[3], 340)
        self.assertLess(image.bbox[0], 90)
        self.assertEqual(image.image_type, 'vector')
        self.assertTrue(Path(image.path).is_file())
        self.assertEqual(len(collect_figures(data)), 1)

    def test_paths_outside_form_clip_do_not_become_a_second_figure(self):
        with chart_pdf() as source:
            source[0].draw_rect(fitz.Rect(150, 30, 600, 110),
                                fill=(.5, .2, .2), color=(0, 0, 0))
            data = self.extract(source)
        self.assertEqual(len(data.pages[0].images), 1)
        self.assertEqual(data.pages[0].tables, [])
        self.assertLess(data.pages[0].images[0].bbox[2], 501)

    def test_text_only_included_pdf_is_found_without_raster_or_paths(self):
        with chart_pdf(text_only=True) as source:
            data = self.extract(source)
        self.assertEqual(len(data.pages[0].images), 1)

    def test_pdf_grid_is_not_reclassified_as_a_table(self):
        with chart_pdf(grid=True) as source:
            data = self.extract(source)
        self.assertEqual(len(data.pages[0].images), 1)
        self.assertEqual(data.pages[0].tables, [])

    def test_nested_and_rotated_pdf_is_one_figure(self):
        with chart_pdf() as source, fitz.open() as nested:
            nested.new_page(width=300, height=160).show_pdf_page(fitz.Rect(0, 0, 300, 160), source, 0)
            data = self.extract(nested, rotate=90)
        self.assertEqual(len(data.pages[0].images), 1)
        self.assertLess(data.pages[0].images[0].bbox[3], 340)

    def test_content_stream_transform_is_used_for_pdf_placement(self):
        with chart_pdf(text_only=True) as source, fitz.open() as thesis:
            page = thesis.new_page()
            page.show_pdf_page(fitz.Rect(80, 100, 500, 330), source, 0)
            xref, name, _, _ = next(form for form in page.get_xobjects() if form[2] == 0)
            matrix = thesis.xref_get_key(xref, 'Matrix')[1][1:-1]
            thesis.xref_set_key(xref, 'Matrix', '[1 0 0 1 0 0]')
            for content in page.get_contents():
                stream = thesis.xref_stream(content)
                thesis.update_stream(content, stream.replace(f'/{name} Do'.encode(), f'{matrix} cm /{name} Do'.encode()))
            page.insert_text((80, 355), 'Figure 1. An externally transformed PDF')
            thesis.save('thesis.pdf')
        data = extractPDF('thesis.pdf')
        self.assertEqual(len(data.pages[0].images), 1)
        self.assertAlmostEqual(data.pages[0].images[0].bbox[0], 80, places=1)
        self.assertAlmostEqual(data.pages[0].images[0].bbox[3], 327, places=1)

    @unittest.skipUnless(shutil.which('pdflatex'), 'pdflatex is optional for this integration fixture')
    def test_actual_latex_includegraphics_keeps_the_complete_figure(self):
        with chart_pdf(text_only=True) as source:
            source.save('chart.pdf')
        Path('main.tex').write_text(r"""\documentclass{article}
\usepackage{graphicx}
\begin{document}
This body paragraph discusses Figure 1.
\begin{figure}[h]
\centering
\includegraphics[width=.8\textwidth]{chart.pdf}
\caption{A separately exported PDF chart}
\end{figure}
\end{document}
""")
        subprocess.run(['pdflatex', '-no-shell-escape', '-interaction=batchmode', '-halt-on-error', 'main.tex'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=30)
        data = extractPDF('main.pdf')
        self.assertEqual(len(data.pages[0].images), 1)
        image = data.pages[0].images[0]
        self.assertTrue(image.description.startswith('Figure 1'))
        self.assertLess(image.bbox[1], 180)
        self.assertGreater(image.bbox[3], 290)
        mapped = PDFMapper().map_to_schema(data)
        self.assertNotIn('long chart legend', ' '.join(getattr(b, 'content', '') for b in mapped.logical_blocks))

    def test_reused_form_placements_are_distinct_and_unused_resources_ignored(self):
        with chart_pdf(text_only=True) as source, fitz.open() as thesis:
            page = thesis.new_page()
            page.show_pdf_page(fitz.Rect(50, 100, 270, 260), source, 0)
            page.show_pdf_page(fitz.Rect(320, 100, 540, 260), source, 0)
            forms = [item for item in page.get_xobjects() if item[2] == 0]
            matrices = [thesis.xref_get_key(item[0], 'Matrix')[1][1:-1] for item in forms]
            xref, name = forms[0][:2]
            thesis.xref_set_key(xref, 'Matrix', '[1 0 0 1 0 0]')
            content = page.get_contents()[0]
            thesis.update_stream(content, (' '.join(f'q {matrix} cm /{name} Do Q' for matrix in matrices)).encode())
            page.set_contents(content)
            page.insert_text((50, 265), 'Figure 1. Left chart', fontsize=10)
            page.insert_text((320, 265), 'Figure 2. Right chart', fontsize=10)
            thesis.save('thesis.pdf')
        data = extractPDF('thesis.pdf')
        images = data.pages[0].images
        self.assertEqual(len(images), 2)
        self.assertNotEqual(images[0].path, images[1].path)
        self.assertEqual({f['id'] for f in collect_figures(data)}, {'Figure 1', 'Figure 2'})

    def test_side_by_side_pdfs_keep_their_own_captions(self):
        with chart_pdf() as source, fitz.open() as thesis:
            page = thesis.new_page()
            page.show_pdf_page(fitz.Rect(50, 100, 270, 260), source, 0)
            page.show_pdf_page(fitz.Rect(320, 100, 540, 260), source, 0)
            # Actual included rectangles are aspect-fitted to y=121..239.
            page.insert_text((50, 265), 'Figure 1. Left chart', fontsize=10)
            page.insert_text((320, 265), 'Figure 2. Right chart', fontsize=10)
            thesis.save('thesis.pdf')
        data = extractPDF('thesis.pdf')
        self.assertEqual(len(data.pages[0].images), 2)
        self.assertEqual({f['id'] for f in collect_figures(data)}, {'Figure 1', 'Figure 2'})
        self.assertTrue(next(i for i in data.pages[0].images if i.bbox[0] < 100).description.startswith('Figure 1'))

    def test_long_multiline_caption_is_not_truncated(self):
        with chart_pdf() as source, fitz.open() as thesis:
            page = thesis.new_page()
            page.show_pdf_page(fitz.Rect(80, 100, 500, 330), source, 0)
            page.insert_text((80, 355), 'Rysunek 1. First caption line\nSecond caption line\nThird caption line\nFourth caption line\nLast caption line', fontsize=11)
            thesis.save('thesis.pdf')
        data = extractPDF('thesis.pdf')
        self.assertIn('Last caption line', data.pages[0].images[0].description)

    def test_full_imported_thesis_page_is_not_one_ignored_figure(self):
        with fitz.open() as source, fitz.open() as thesis:
            page = source.new_page()
            page.insert_text((80, 150), 'An ordinary paragraph in an imported page.')
            page.insert_text((80, 600), 'Rysunek 1. A mention without a chart object')
            thesis.new_page().show_pdf_page(page.rect, source, 0)
            thesis.save('thesis.pdf')
        data = extractPDF('thesis.pdf')
        self.assertEqual(data.pages[0].images, [])

    def test_captionless_form_does_not_hide_body_text(self):
        with chart_pdf(text_only=True) as source:
            data = self.extract(source, caption='A regular paragraph below the object.')
        self.assertEqual(data.pages[0].images, [])

    def test_discussion_sentence_is_not_used_as_a_caption(self):
        with chart_pdf(text_only=True) as source:
            data = self.extract(source, caption='Rysunek 1 pokazuje poprawe wynikow pomiarow.')
        self.assertEqual(data.pages[0].images, [])

    def test_chart_legend_is_not_checked_as_prose(self):
        with chart_pdf() as source:
            data = self.extract(source, caption='Wykres 1. Wyniki pomiarow')
        mapped = PDFMapper().map_to_schema(data)
        prose = " ".join(getattr(block, 'content', '') for block in mapped.logical_blocks)
        self.assertNotIn('long chart legend', prose)
        self.assertIn('real body paragraph', prose)
        self.assertTrue(any(getattr(block, 'type', '') == 'image_description' and 'Wykres 1' in getattr(block, 'content', '') for block in mapped.logical_blocks))

    def test_chart_widow_is_removed_but_caption_and_body_widows_remain(self):
        with chart_pdf() as source:
            data = self.extract(source)
        validator = RedactionValidator(data, None)
        inside = SimpleNamespace(category='widow', page_number=0, bounding_box=(130, 300, 400, 315))
        caption = SimpleNamespace(category='widow', page_number=0, bounding_box=(80, 345, 220, 358))
        body = SimpleNamespace(category='widow', page_number=0, bounding_box=(80, 390, 220, 402))
        validator.errors = [inside, caption, body]
        validator.remove_errors_from_images()
        self.assertEqual(validator.errors, [caption, body])


if __name__ == '__main__':
    unittest.main()
