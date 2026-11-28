import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from analysis.modules.linguistics.abstract_language import apply_abstract_languages
from analysis.extraction.linguistics_conversion.schema import ParagraphBlock


def block(text, kind='paragraph', language='pl', page=2):
    return ParagraphBlock(block_id=1, type=kind, content=text, language=language,
                          words=[NS(page_number=page)])


class AbstractLanguageTest(unittest.TestCase):
    def test_english_abstract_uses_english_until_next_heading(self):
        blocks = [block('ABSTRACT', 'heading'), block('Short technical terms'),
                  block('Keywords: robot'), block('1. WSTĘP', 'heading'), block('Tekst polski')]
        apply_abstract_languages(NS(logical_blocks=blocks))
        self.assertEqual([b.language for b in blocks], ['en', 'en', 'en', 'pl', 'pl'])

    def test_polish_abstract_in_english_document_uses_polish(self):
        blocks = [block('STRESZCZENIE', 'heading', 'en'), block('Streszczenie pracy', language='en')]
        apply_abstract_languages(NS(logical_blocks=blocks))
        self.assertEqual([b.language for b in blocks], ['pl', 'pl'])

    def test_abstrakt_heading_uses_polish(self):
        blocks = [block('ABSTRAKT', 'heading', 'en'), block('Tekst abstraktu', language='en')]
        apply_abstract_languages(NS(logical_blocks=blocks))
        self.assertEqual([b.language for b in blocks], ['pl', 'pl'])

    def test_abstract_on_second_page_is_not_skipped_or_redetected_as_polish(self):
        from analysis.modules.linguistics.helpers import get_context
        document = NS(logical_blocks=[block('ABSTRACT', 'heading', page=1),
                                     block('The robot works.', page=1)])
        apply_abstract_languages(document)
        with patch('analysis.modules.linguistics.helpers.language', return_value='pl'):
            context = get_context(document)
        self.assertEqual([b.language for b in context], ['en', 'en'])

    def test_word_abstract_inside_a_paragraph_does_not_switch_language(self):
        document = NS(logical_blocks=[block('abstract')])
        apply_abstract_languages(document)
        self.assertEqual(document.logical_blocks[0].language, 'pl')
