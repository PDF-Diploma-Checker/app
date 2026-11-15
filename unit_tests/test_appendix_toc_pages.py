"""Exercise real PDF extraction without running NLP models or using a GPU."""
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from analysis.extraction.main_extractor import extractPDF
from analysis.modules.redaction.redaction_validator import RedactionValidator
from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from unit_tests.test_list_titles import _entry, _page, _validator


@contextmanager
def extracted_document(*, bookmarks=False, appendix_footer=('1', '2'), wrong=False, missing=False):
    # extractPDF clears cwd/images. Never run it in the user's working directory.
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.chdir(directory)
            doc = fitz.open()
            titles = ['Thesis', 'Contents', '1. Introduction', '2. Methods',
                      '3. Results', '4. Discussion', 'Bibliography',
                      'A. Survey', 'B. Data']
            footers = ['', 'ii', '1', '2', '3', '4', '5', *appendix_footer]
            for index, (title, footer) in enumerate(zip(titles, footers)):
                page = doc.new_page(width=595, height=842)
                page.insert_text((65, 80), 'Other material' if missing and index == 8 else title,
                                 fontsize=16, fontname='hebo')
                page.insert_text((65, 150), 'Supporting material for the thesis.', fontsize=11)
                if index == 1 and not bookmarks:
                    entries = ['1. Introduction .... 1', '2. Methods .... 2',
                               'Bibliography .... 5', f'A. Survey .... {appendix_footer[0]}',
                               f'B. Data .... {1 if wrong else appendix_footer[1]}']
                    for y, text in enumerate(entries):
                        page.insert_text((65, 210 + y * 25), text, fontsize=11)
                if footer:
                    page.insert_text((290, 814), footer, fontsize=11)
            if bookmarks:
                # Explicit A/B PDF labels do not change bookmark destinations.
                doc.set_page_labels([{'startpage': 0, 'style': 'r'},
                                     {'startpage': 2, 'style': 'D'},
                                     {'startpage': 7, 'style': 'A'}])
                doc.set_toc([[1, 'A. Survey', 8], [1, 'B. Data', 8 if wrong else 9]])
            doc.save('appendices.pdf')
            doc.close()
            yield extractPDF('appendices.pdf')
        finally:
            os.chdir(previous)


def validator(document):
    errors = []
    return NS(document_data=document, errors=errors, language='en',
              module='redaction', _get_next_id=lambda: len(errors))


class AppendixTocPagesTest(unittest.TestCase):
    def test_restart_after_bibliography(self):
        with extracted_document() as document:
            self.assertEqual([(e.title, e.page) for e in document.toc.entries][-2:],
                             [('A Survey', 1), ('B Data', 2)])
            check = validator(document)
            self.assertEqual(RedactionValidator.check_toc(check), ([], True))
            self.assertEqual(check.errors, [])
            RedactionValidator.check_footers(check)
            self.assertIn('Wrong_page_number', [e.category for e in check.errors])

    def test_wrong_page_and_missing_heading_remain_errors(self):
        for options in ({'wrong': True}, {'missing': True}):
            with self.subTest(options=options), extracted_document(**options) as document:
                check = validator(document)
                RedactionValidator.check_toc(check)
                self.assertEqual([(e.category, e.text) for e in check.errors],
                                 [('TOC_mismatch', 'B Data')])

    def test_continuous_arabic_footers(self):
        with extracted_document(appendix_footer=('6', '7')) as document:
            check = validator(document)
            RedactionValidator.check_toc(check)
            self.assertEqual(check.errors, [])

    def test_bookmarks_ignore_roman_footers_and_letter_page_labels(self):
        for footers in (('vi', 'vii'), ('6', '7')):
            with self.subTest(footers=footers), extracted_document(bookmarks=True, appendix_footer=footers) as document:
                self.assertEqual([e.src_page for e in document.toc.entries], [-1, -1])
                check = validator(document)
                RedactionValidator.check_toc(check)
                self.assertEqual(check.errors, [])

    def test_bad_bookmark_and_missing_heading_remain_errors(self):
        for options in ({'wrong': True}, {'missing': True}):
            with self.subTest(options=options), extracted_document(bookmarks=True, **options) as document:
                check = validator(document)
                RedactionValidator.check_toc(check)
                self.assertEqual([(e.category, e.text) for e in check.errors],
                                 [('TOC_mismatch', 'B. Data')])

    def test_lettered_appendix_ends_bibliography_classification(self):
        for heading in ('A. Appendix', 'B. Załącznik', 'A. Dodatek'):
            self.assertTrue(PDFMapper._is_after_bib_heading_line(heading), heading)

    def test_missing_footer_uses_dominant_offset(self):
        check, errors = _validator(
            [_page(2, footer=1), _page(3, footer=2), _page(4, 'A. Survey')],
            toc=[_entry('A Survey', 3)])
        RedactionValidator.check_toc(check)
        self.assertEqual(errors, [])

    def test_conflicting_footer_is_not_overridden_by_offset(self):
        check, errors = _validator(
            [_page(2, footer=1), _page(3, footer=2), _page(4, 'A. Survey', footer=99)],
            toc=[_entry('A Survey', 3)])
        RedactionValidator.check_toc(check)
        self.assertEqual([e.category for e in errors], ['TOC_mismatch'])

    def test_contents_cannot_validate_its_own_entry(self):
        check, errors = _validator(
            [_page(1, 'B. Missing .... 1', footer=1), _page(2, 'Other material', footer=2)],
            toc=[_entry('B Missing', 1)])
        check.document_data.toc.page_nums = [1]
        RedactionValidator.check_toc(check)
        self.assertEqual([e.category for e in errors], ['TOC_mismatch'])


if __name__ == '__main__':
    unittest.main()
