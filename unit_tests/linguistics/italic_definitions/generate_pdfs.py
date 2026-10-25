r'''
Generates test PDFs for checking that foreign language definitions are written in italic
with different compilers (pdflatex, xelatex, lualatex).

File names describe the expected result:
- tp_foreign_definition_not_italic_<compiler>.pdf - foreign language definitions in "(ang. ...)" etc.
  written in upright font, which must be reported (true positive),
- fp_foreign_definition_italic_<compiler>.pdf - the same definitions written in italic (\textit, \emph),
  which must not be reported (false positive).

Run (from the repository root):
    python unit_tests/linguistics/italic_definitions/generate_pdfs.py
'''
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS, build_latex

OUTPUT_DIR = Path(__file__).resolve().parent

# The same sentences in both documents, only the font of the definition differs
DEFINITIONS = [
    (r"Do klasyfikacji obrazów zastosowano sieć konwolucyjną CNN (ang. {}), która osiąga wysoką dokładność.",
     "Convolutional Neural Network"),
    (r"Model wykorzystuje mechanizm uwagi (ang. {}), dzięki któremu poprawia się jakość tłumaczenia.",
     "attention mechanism"),
    (r"Przetwarzanie brzegowe (ang. {}) polega na wykonywaniu obliczeń blisko źródła danych.",
     "edge computing"),
    (r"Badania przeprowadzono w warunkach naturalnych (łac. {}) na grupie kilkudziesięciu osób.",
     "in vivo"),
]

DOCUMENTS = {
    "tp_foreign_definition_not_italic": [sentence.format(definition) for sentence, definition in DEFINITIONS],
    "fp_foreign_definition_italic": [
        sentence.format((r"\emph{{{}}}" if i % 2 else r"\textit{{{}}}").format(definition))
        for i, (sentence, definition) in enumerate(DEFINITIONS)
    ],
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
Oświadczenie autora pracy.
\clearpage
{paragraphs}
\end{document}
'''


def main():
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for name, paragraphs in DOCUMENTS.items():
            for compiler in LATEX_COMPILERS:
                build_latex(name, paragraphs, compiler, workdir, LATEX_TEMPLATE, OUTPUT_DIR)


if __name__ == "__main__":
    main()
