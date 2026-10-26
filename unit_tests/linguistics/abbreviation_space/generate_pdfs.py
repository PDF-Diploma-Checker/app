r'''
Generates test PDFs for checking missing space after abbreviations
with different LaTeX compilers (pdflatex, xelatex, lualatex).

File names describe the expected result:
- tp_missing_space_after_abbreviation_<compiler>.pdf - abbreviations with missing space, e.g. "tzw.krótkiej" (true positive),
- fp_correct_space_after_abbreviation_<compiler>.pdf - abbreviations with proper space, e.g. "tzw. krótkiej" (false positive).

Run:
    python unit_tests/linguistics/abbreviation_space/generate_pdfs.py
'''
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS, build_latex

OUTPUT_DIR = Path(__file__).resolve().parent

SENTENCES_TP = [
    r"W badaniach zastosowano tzw.krótkiej sprzedaży strategię rynkową.",
    r"Wybrano różne parametry, np.pierwszy z nich był najbardziej optymalny.",
    r"Zastosowano podejście tzn.drugi wariant rozwiązania zagadnienia.",
    r"Uwzględniono inne czynniki, itp.kolejne zmienne w modelu.",
]

SENTENCES_FP = [
    r"W badaniach zastosowano tzw. krótkiej sprzedaży strategię rynkową.",
    r"Wybrano różne parametry, np. pierwszy z nich był najbardziej optymalny.",
    r"Zastosowano podejście tzn. drugi wariant rozwiązania zagadnienia.",
    r"Uwzględniono inne czynniki, itp. kolejne zmienne w modelu.",
]

DOCUMENTS = {
    "tp_missing_space_after_abbreviation": SENTENCES_TP,
    "fp_correct_space_after_abbreviation": SENTENCES_FP,
}

LATEX_TEMPLATE = r'''\documentclass[12pt,a4paper]{article}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[T1]{fontenc}
  \usepackage[utf8]{inputenc}
  \usepackage{lmodern}
\else
  \usepackage{fontspec}
\fi
\usepackage{hyperref}
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for name, paragraphs in DOCUMENTS.items():
            for compiler in LATEX_COMPILERS:
                print(f"Building {name}_{compiler}.pdf ...")
                build_latex(name, paragraphs, compiler, tmp_path, LATEX_TEMPLATE, OUTPUT_DIR)
    print("Done generating abbreviation test PDFs.")


if __name__ == "__main__":
    main()
