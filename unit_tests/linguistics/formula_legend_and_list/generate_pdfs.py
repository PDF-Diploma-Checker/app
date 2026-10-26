r'''
Generates test PDFs for formula legends under 'gdzie:' and list coherence checks
with different LaTeX compilers (pdflatex, xelatex, lualatex).

File names describe the expected result:
- fp_formula_legend_<compiler>.pdf - formula legend with 'gdzie:' and symbol items with consistent endings (commas/period),
  which must NOT be reported as list coherence errors (false positive check),
- tp_inconsistent_list_<compiler>.pdf - a regular list with inconsistent endings (none, period, semicolon),
  which MUST be reported as a LIST_ENDING error (true positive check).

Run:
    python unit_tests/linguistics/formula_legend_and_list/generate_pdfs.py
'''
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS, build_latex

OUTPUT_DIR = Path(__file__).resolve().parent

PARAGRAPHS_FP = [
    r"Obliczenie podobieństwa wykonuje się za pomocą wzoru matematycznego.",
    r"\begin{equation}" "\n"
    r"\mathrm{sim}(d_1, d_2) = \cos \theta" "\n"
    r"\end{equation}",
    r"gdzie:",
    r"\begin{itemize}" "\n"
    r"\item $\mathrm{sim}(d_1, d_2)$ -- miara podobieństwa kosinusowego między dokumentami," "\n"
    r"\item $\cos \theta$ -- kosinus kąta między dwoma wektorami cech," "\n"
    r"\item $v(d)$ -- wektory cech reprezentujące dokumenty tekstowe." "\n"
    r"\end{itemize}",
    r"Należy pamiętać, że porównywane wektory muszą mieć ten sam wymiar.",
]

PARAGRAPHS_TP = [
    r"Wyróżnia się następujące etapy przetwarzania danych tekstowych w systemie:",
    r"\begin{itemize}" "\n"
    r"\item pierwszy etap analizy bez interpunkcji na końcu" "\n"
    r"\item drugi etap analizy zakończony kropką." "\n"
    r"\item trzeci etap analizy zakończony średnikiem;" "\n"
    r"\end{itemize}",
    r"Każdy z powyższych etapów ma kluczowe znaczenie dla końcowej jakości.",
]

DOCUMENTS = {
    "fp_formula_legend": PARAGRAPHS_FP,
    "tp_inconsistent_list": PARAGRAPHS_TP,
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
\usepackage{amsmath,amssymb}
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
    print("Done generating formula legend and list test PDFs.")


if __name__ == "__main__":
    main()
