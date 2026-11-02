r'''
Generates test PDFs for extraction of math accents (hat, bar, tilde...) with different LaTeX compilers
(pdflatex, xelatex, lualatex).

LuaTeX / XeTeX with unicode-math write a math accent to the PDF as a separate combining character (U+0302)
in the math font, BEFORE the symbol it decorates. The extraction used to glue it to the preceding word
of the text font ("Przez" + hat -> "Przeẑ").

File names describe the expected result:
- tp_math_accents_<compiler>.pdf - Polish words followed by a formula with an accent: after extraction the words
  must stay intact and no combining mark may be attached to them (true positive of the extraction),
- fp_accents_in_text_<compiler>.pdf - Polish letters and accents inside the text font, which must be kept as they are
  (false positive of a too broad fix).

Run:
    python unit_tests/extraction/math_accents/generate_pdfs.py
'''
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS, build_latex  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent

PARAGRAPHS_TP = [
    r"Przez $\hat{\mathbf{x}}_{k|j}$ oznaczono oszacowanie stanu w chwili $k$ uzyskane na podstawie notowań.",
    r"Oszacowanie $\hat{\mathbf{x}}_{k|k}$ pozwala wyznaczyć prognozy potrzebne w zadaniu optymalizacji.",
    r"Prognozę przyrostu ceny zapisujemy jako $\Delta\hat{S}_{k+1} = \hat{S}_{k+1} - S_k$ dla każdego dnia.",
]

PARAGRAPHS_FP = [
    r"Zażółć gęślą jaźń, a następnie pchnąć w tę łódź jeża lub ośm skrzyń fig oraz źdźbło trawy.",
    r"Wielkie litery to ĄĆĘŁŃÓŚŹŻ, a małe to ąćęłńóśźż, bez żadnych wzorów.",
    r"Wzór bez akcentu $x_{k|j}$ stoi tuż za słowem Przez oraz za słowem Oszacowanie.",
]

DOCUMENTS = {
    "tp_math_accents": PARAGRAPHS_TP,
    "fp_accents_in_text": PARAGRAPHS_FP,
}

LATEX_TEMPLATE = r'''\documentclass[12pt,a4paper]{article}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[T1]{fontenc}
  \usepackage[utf8]{inputenc}
  \usepackage{lmodern}
\else
  \usepackage{fontspec}
  \usepackage{unicode-math}
\fi
\usepackage{amsmath}
\usepackage{bm}
\hyphenpenalty=10000
\exhyphenpenalty=10000
\sloppy
\begin{document}
\begin{titlepage}
\centering Praca dyplomowa
\end{titlepage}
\newpage
Oświadczenie autora pracy.
\newpage
{paragraphs}
\end{document}
'''


def main():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for name, paragraphs in DOCUMENTS.items():
            for compiler in LATEX_COMPILERS:
                print(f"Building {name}_{compiler}.pdf ...")
                build_latex(name, paragraphs, compiler, tmp_path, LATEX_TEMPLATE, OUTPUT_DIR)
    print("Done generating math accent test PDFs.")


if __name__ == "__main__":
    main()
