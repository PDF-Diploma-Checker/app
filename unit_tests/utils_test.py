'''
Shared test helpers (unit_tests/**/test_*.py).

- pdf_to_blocks - PDF extraction and block preparation the same way as in src/app/pipeline.py,
- PDF_COMPILERS - compilers used by generate_pdfs.py to build the test PDFs.

Blocks built by hand (make_words / make_paragraph) live in each test file, because their positions
(page, bbox) depend on what the given tests check.

The name does not start with "test", so unittest discover does not treat the file as a test module.
'''
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS  # noqa: E402

PDF_COMPILERS = LATEX_COMPILERS + ("libreoffice_writer",)


def pdf_to_blocks(pdf_path, language="pl"):
    '''Extracts blocks from test pdfs.'''
    from analysis.extraction.main_extractor import extractPDF
    from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
    from analysis.modules.linguistics.helpers import get_context

    raw_blocks = PDFMapper().map_to_schema(extractPDF(str(pdf_path)))
    for block in raw_blocks.logical_blocks:
        block.language = language
    return raw_blocks, get_context(raw_blocks)
