import unittest
from types import SimpleNamespace

from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from analysis.extraction.linguistics_conversion.schema import ends_with_link, is_widow_func


def _words(*lines):
    return [
        SimpleNamespace(text=text, page_number=1, line=number, is_index=False)
        for number, line in enumerate(lines)
        for text in line.split()
    ]


def _flag(*lines):
    item = SimpleNamespace(words=_words(*lines), is_widow=0)
    mapper = PDFMapper.__new__(PDFMapper)
    mapper.logical_blocks = [SimpleNamespace(is_bibliography=True, items=[item])]
    mapper._flag_bibliography_widows()
    return item.is_widow


class BibliographyWidowTest(unittest.TestCase):
    def test_end_of_a_broken_url_is_not_a_widow(self):
        self.assertEqual(_flag("[1] J. Kowalski, Tytuł artykułu, https://example.com/sciezka/", "do-pliku.html"), 0)

    def test_end_of_a_broken_doi_is_not_a_widow(self):
        self.assertEqual(_flag("[2] J. Kowalski, Tytuł artykułu, doi: 10.1000/abc-", "def.2020"), 0)
        self.assertEqual(_flag("[3] J. Kowalski, Tytuł artykułu, https://doi.org/10.1000/", "abc-def"), 0)

    def test_url_broken_over_three_lines(self):
        self.assertEqual(_flag("[4] J. Kowalski, Tytuł, https://example.com/bardzo/", "dluga/sciezka/", "koniec"), 0)

    def test_whole_url_or_doi_on_the_last_line(self):
        self.assertEqual(_flag("[5] J. Kowalski, Tytuł artykułu w czasopiśmie,", "https://example.com/plik"), 0)
        self.assertEqual(_flag("[6] J. Kowalski, Tytuł artykułu w czasopiśmie,", "DOI: 10.1000/abc"), 0)

    def test_ordinary_short_last_line_is_still_a_widow(self):
        self.assertEqual(_flag("[7] J. Kowalski, Bardzo długi tytuł artykułu w czasopiśmie", "naukowym, 2020."), 2)

    def test_text_after_a_finished_link_is_still_a_widow(self):
        self.assertEqual(_flag("[8] J. Kowalski, Tytuł, https://example.com/plik,", "2020."), 1)

    def test_link_earlier_in_the_entry_does_not_excuse_a_widow(self):
        self.assertEqual(_flag("[9] https://example.com/plik, tytuł bardzo długiego artykułu", "naukowym, 2020."), 2)

    def test_paragraph_check_is_unchanged(self):
        words = _words("Na stronie https://example.com/sciezka/", "koniec")
        self.assertEqual(is_widow_func(words), 1)
        self.assertTrue(ends_with_link(words))


if __name__ == "__main__":
    unittest.main()
