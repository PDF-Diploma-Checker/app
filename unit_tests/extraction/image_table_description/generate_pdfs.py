'''
Generuje PDF-y testowe dla sprawdzania pozycjonowania podpisów tabel i obrazków.
Uwzględnia skróty (tab., rys., fot.), wzory matematyczne w podpisach oraz
przypadki False Positive (np. zwykły tekst udający podpis).

Uruchomienie (z katalogu głównego repozytorium):
    python unit_tests/extraction/captions/generate_pdfs.py
'''
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS, build_latex  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent

LATEX_TEMPLATE = r'''\documentclass[12pt,a4paper]{article}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[T1]{fontenc}
  \usepackage[utf8]{inputenc}
\else
  \usepackage{fontspec}
\fi
\usepackage{xcolor}
\usepackage{amsmath}
\setlength{\parindent}{0pt}
\begin{document}
\begin{titlepage}
\centering Praca dyplomowa
\end{titlepage}
Oświadczenie autora pracy.
\clearpage
{paragraphs}
\end{document}
'''

DOCUMENTS = {
    "tp_captions": [
        r"Tab. 1. Prawidłowy podpis nad tabelą z użyciem skrótu",
        r"\begin{tabular}{|c|c|} \hline X & Y \\ \hline 1 & 2 \\ \hline \end{tabular}",
        r"\vspace{1.5cm}",

        r"\noindent\textcolor{blue}{\rule{5cm}{3cm}}",
        r"Rys. 1. Zależność energii od masy wyrażona wzorem $E=mc^2$ w próżni",
        r"\vspace{1.5cm}",

        r"\noindent\textcolor{red}{\rule{5cm}{3cm}}",
        r"Fot. 2. Zjawisko dyfrakcji dla $\lambda = 500$ nm",
    ],
    "fp_captions": [
        r"\begin{tabular}{|c|c|} \hline A & B \\ \hline 3 & 4 \\ \hline \end{tabular}",
        r"Jak widać w powyższej tabeli, wyniki są zadowalające. To nie jest podpis (nie zaczyna się od słowa kluczowego).",
        r"\vspace{1.5cm}",

        r"\noindent\textcolor{green}{\rule{5cm}{3cm}}",
        r"Wykres widoczny powyżej przedstawia błąd pomiarowy. Wartość odchylenia to $3\%$.",
        r"\vspace{1.5cm}",
        
        r"\noindent\textcolor{black}{\rule{5cm}{3cm}}",
        r"\vspace{3.5cm}",
        r"Rys. 3. Podpis umieszczony zbyt daleko (FP ze względu na dystans)",
    ]
}

def main():
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        
        for name, paragraphs in DOCUMENTS.items():
            for compiler in LATEX_COMPILERS:
                build_latex(name, paragraphs, compiler, workdir, LATEX_TEMPLATE, OUTPUT_DIR)

if __name__ == "__main__":
    main()