"""A caption shared by a text block and a figure produces one finding."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from analysis.modules.redaction.redaction_validator import RedactionValidator


class CaptionSourceDuplicatesTest(unittest.TestCase):
    def check(self, blocks, visuals):
        validator = NS(language='pl', module='redaction', errors=[],
                       _get_next_id=lambda: 0,
                       document_data_linguistics=NS(logical_blocks=blocks,
                           floating_elements=NS(visual_elements=visuals)))
        RedactionValidator.check_caption_sources(validator)
        return validator.errors

    def visual(self, page=39, caption='Rysunek 5.1. Skan terenu.'):
        return NS(type='image', incorrect_caption=1, caption={'text': caption},
                  page_number=page, bbox=(100, 400, 520, 600))

    def test_caption_text_and_image_are_one_finding_at_caption(self):
        block = NS(incorrect_caption=1, content='Rysunek 5.1. Skan terenu.',
                   words=[NS(bbox=(100, 610, 520, 630), page_number=39)])
        errors = self.check([block], [self.visual()])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].bounding_box, (100, 610, 520, 630))

    def test_repeated_caption_text_is_reported_once(self):
        block = NS(incorrect_caption=1, content='Rysunek 5.1. Skan terenu.',
                   words=[NS(bbox=(100, 610, 520, 630), page_number=39)])
        self.assertEqual(len(self.check([block, block], [self.visual()])), 1)

    def test_shared_caption_without_text_block_is_reported_once(self):
        self.assertEqual(len(self.check([], [self.visual(), self.visual()])), 1)

    def test_distinct_captions_and_pages_are_preserved(self):
        errors = self.check([], [self.visual(), self.visual(page=40),
                                self.visual(caption='Rysunek 5.2. Inny rysunek.')])
        self.assertEqual(len(errors), 3)

    def test_valid_caption_is_not_reported(self):
        visual = self.visual()
        visual.incorrect_caption = 0
        self.assertEqual(self.check([], [visual]), [])
