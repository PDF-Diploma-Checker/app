'''
Tests for formula symbol legend handling under 'gdzie:' and list coherence checks.

Checks that:
- formula symbol lists and stubs following 'gdzie:' are retagged to 'acronyms' by PDFMapper._tag_formula_legends,
- formula symbol lists (having consistent endings e.g. commas or period) produce no false positive errors in check_coherence_in_list,
- regular lists with inconsistent endings are properly flagged with LIST_ENDING errors,
- PDFMapper._formula_regions excludes 'gdzie:' / 'where:' so the legend introduction line is preserved in logical blocks,
- TestGeneratedPdfs verifies full pipeline run (extraction -> analysis) on test PDFs
  built by different LaTeX compilers (pdflatex, xelatex, lualatex).

Run:
    uv run python -m unittest unit_tests/linguistics/formula_legend_and_list/test_formula_legend_and_list.py -v
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.schema import ParagraphBlock, ListBlock, ListItem, WordInfo
from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from analysis.modules.linguistics.linguistics_types import Block_context
from analysis.modules.linguistics.list_check import check_coherence_in_list
from unit_tests.utils_generate_pdfs import LATEX_COMPILERS
from unit_tests.utils_test import pdf_to_blocks

PDF_DIR = Path(__file__).resolve().parent


def make_words(content, page=1):
    words = []
    pos = 0
    for i, text in enumerate(content.split(" ")):
        words.append(WordInfo(
            word_index=i, text=text, start_char=pos, end_char=pos + len(text),
            font="Arial", size=10.0, bold=False, italic=False,
            bbox=[10.0 * i, 100.0, 10.0 * i + 8, 112.0], page_number=page
        ))
        pos += len(text) + 1
    return words


def make_paragraph(content, block_id=1, language="pl"):
    p = ParagraphBlock(block_id=block_id, content=content, words=make_words(content))
    p.language = language
    return p


def make_list_block(items_data, block_id="list_1", language="pl"):
    items = []
    for i, (text, marker) in enumerate(items_data):
        items.append(ListItem(
            item_id=i, marker_type=marker, text=text,
            bbox=[0.0, 0.0, 100.0, 10.0], words=make_words(text)
        ))
    content = "\n".join(t for t, _ in items_data)
    lb = ListBlock(block_id=block_id, content=content, bbox=[0.0, 0.0, 100.0, 50.0],
                   items=items, words=make_words(content), type="list")
    lb.language = language
    return lb


class TestFormulaLegendAndListCheck(unittest.TestCase):

    def test_tag_formula_legends_retags_list_and_stubs(self):
        mapper = PDFMapper()
        p_intro = make_paragraph("gdzie:", block_id=1)
        p_stub = make_paragraph("sim (d1, d2)", block_id=2)
        legend_items = [
            ("miara podobieństwa kosinusowego między dokumentami,", "dash"),
            ("kosinus kąta między wektorami,", "dash"),
            ("wektory cech reprezentujące dokumenty.", "dash"),
        ]
        list_block = make_list_block(legend_items, block_id="list_3")

        mapper.logical_blocks = [p_intro, p_stub, list_block]
        mapper._tag_formula_legends()

        self.assertEqual(p_stub.type, "acronyms")
        self.assertEqual(list_block.type, "acronyms")

    def test_formula_legend_not_flagged_by_list_check(self):
        legend_items = [
            ("x - pierwsza współrzędna wektora,", "dash"),
            ("y - druga współrzędna wektora.", "dash"),
        ]
        list_block = make_list_block(legend_items, block_id="list_legend")
        list_block.type = "acronyms"

        block_ctx = Block_context(contents=list_block.content, language="pl", block=list_block)
        matches = check_coherence_in_list([block_ctx], proper_names=[], acronyms={})

        self.assertEqual(len(matches), 0)

    def test_regular_list_checked_for_inconsistent_endings(self):
        items = [
            ("pierwszy punkt wyliczenia bez interpunkcji", "dash"),
            ("drugi punkt wyliczenia zakończony kropką.", "dash"),
            ("trzeci punkt zakończony średnikiem;", "dash"),
        ]
        regular_list = make_list_block(items, block_id="list_regular")
        block_ctx = Block_context(contents=regular_list.content, language="pl", block=regular_list)

        matches = check_coherence_in_list([block_ctx], proper_names=[], acronyms={})
        ending_errors = [m for m in matches if m.category == "LIST_ENDING"]
        self.assertGreater(len(ending_errors), 0)

    def test_formula_regions_excludes_gdzie(self):
        mapper = PDFMapper()
        self.assertTrue(mapper.LEGEND_START_RE.match("gdzie:"))
        self.assertTrue(mapper.LEGEND_START_RE.match("gdzie"))
        self.assertTrue(mapper.LEGEND_START_RE.match("where:"))
        self.assertFalse(mapper.LEGEND_START_RE.match("x + y = z"))


class TestGeneratedPdfs(unittest.TestCase):
    '''Full run extraction -> check_coherence_in_list on PDFs built by different compilers.'''

    @classmethod
    def setUpClass(cls):
        def run(pdf_path):
            _, blocks = pdf_to_blocks(pdf_path)
            return check_coherence_in_list(blocks, proper_names=[], acronyms={})

        cls.run_pdf = staticmethod(run)

    def test_fp_formula_legend(self):
        # Formula legend with consistent endings under 'gdzie:' must NOT produce list coherence errors
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                matches = self.run_pdf(PDF_DIR / f"fp_formula_legend_{compiler}.pdf")
                self.assertEqual(len(matches), 0)

    def test_tp_inconsistent_list(self):
        # Regular list with inconsistent endings MUST produce LIST_ENDING errors
        for compiler in LATEX_COMPILERS:
            with self.subTest(compiler=compiler):
                matches = self.run_pdf(PDF_DIR / f"tp_inconsistent_list_{compiler}.pdf")
                ending_errors = [m for m in matches if m.category == "LIST_ENDING"]
                self.assertGreater(len(ending_errors), 0)


if __name__ == "__main__":
    unittest.main()
