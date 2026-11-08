r'''
Generates test PDFs for telling a compound word (hyphen) from a range/relation (en dash) in dash_check.py,
with different LaTeX compilers (pdflatex, xelatex, lualatex).

File names describe the expected result:
- tp_dash_compound_and_range_<compiler>.pdf - en dash in compound words ("biało–czerwona", "COVID–19"),
  hyphen in a word range ("maj-czerwiec") (true positive),
- fp_dash_compound_and_range_<compiler>.pdf - correct en dash in ranges/relations ("serwer–klient",
  "1990–2000"), hyphen in compound words ("biało-czerwona") and model names ("SG90 - 30") (false positive).

Run:
    python unit_tests/linguistics/dash_check/generate_pdfs.py
'''
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS, build_latex

OUTPUT_DIR = Path(__file__).resolve().parent

SENTENCES_TP = [
    r"Na maszcie powiewała flaga biało–czerwona przez cały dzień.",
    r"Stosunki polsko–niemieckie były tematem tej konferencji.",
    r"Pandemia COVID–19 zmieniła sposób prowadzenia zajęć.",
    r"Badania prowadzono w okresie maj-czerwiec na terenie kampusu.",
]

SENTENCES_FP = [
    r"Na maszcie powiewała flaga biało-czerwona przez cały dzień.",
    r"System zbudowano w architekturze serwer–klient z jednym serwerem.",
    r"Badania prowadzono w okresie maj–czerwiec na terenie kampusu.",
    r"Dane zebrano w latach 1990–2000 w trzech miastach.",
    r"Do napędu użyto serwomechanizmu SG90 - 30 sztuk zamówiono od razu.",
]

DOCUMENTS = {
    "tp_dash_compound_and_range": SENTENCES_TP,
    "fp_dash_compound_and_range": SENTENCES_FP,
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
    print("Done generating dash test PDFs.")


if __name__ == "__main__":
    main()
