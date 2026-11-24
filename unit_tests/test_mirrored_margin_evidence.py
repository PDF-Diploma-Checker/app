import unittest
from copy import deepcopy
from types import SimpleNamespace as NS
from analysis.modules.redaction.redaction_validator import RedactionValidator
from analysis.extraction.raw_extraction.bare_struct import DocumentData
from common.errors.error_struct import Module

class MirrorMarginsTest(unittest.TestCase):
    def page(self, n, left=None, right=None, short=False):
        left = (70 if n % 2 == 0 else 100) if left is None else left
        right = (100 if n % 2 == 0 else 70) if right is None else right
        end = left + 150 if short else 600-right
        lines = [NS(bbox=(left,100+i*15,end,110+i*15), spans=[NS(text='A paragraph with enough ordinary words for the margin measurement.')]) for i in range(5)]
        return NS(number=n,width=600,text_blocks=[NS(lines=lines)],margins={'left':left,'right':600-end,'top':80+n,'bottom':30})

    def validator(self):
        v=object.__new__(RedactionValidator)
        v.config=NS(margin_type='lustrzany');v.language='en';v.errors=[];v.module=Module.REDACTION
        v._get_next_id=lambda: len(v.errors)+1
        return v

    def test_short_symbol_list_and_vertical_whitespace_do_not_change_margins(self):
        d=DocumentData(metadata={},pages=[self.page(n) for n in range(8)]+[self.page(9,short=True)])
        old=deepcopy(d.get_margins());v=self.validator()
        self.assertTrue(v.check_margins(d));self.assertEqual(v.errors,[]);self.assertEqual(d.get_margins(),old)

    def test_real_shift_in_full_width_paragraphs_is_reported(self):
        d=DocumentData(metadata={},pages=[self.page(n) for n in range(8)]+[self.page(9,left=135,right=35)])
        v=self.validator();self.assertFalse(v.check_margins(d));self.assertEqual(len(v.errors),1)
        self.assertEqual(v.errors[0].category,'inconsistent_margins')
        self.assertEqual(__import__('json').loads(v.errors[0].text),{'pages':[9],'evaluated':9})

    def test_standard_margins_do_not_pass_as_mirrored(self):
        d=DocumentData(metadata={},pages=[self.page(n,left=100,right=70) for n in range(8)])
        v=self.validator();self.assertFalse(v.check_margins(d))
