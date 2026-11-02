r'''
Generates test PDFs for checking missing subject / verb detection (sentence_check)
with different LaTeX compilers (pdflatex, xelatex, lualatex).

File names describe the expected result:
- tp_missing_subject_or_verb_<compiler>.pdf - sentences without a verb and impersonal sentences, which must be
  reported as NO_VERB / NO_SUBJECT (true positive),
- fp_correct_sentences_<compiler>.pdf - correct sentences previously reported by mistake: initials and abbreviations,
  past tense with implicit subject, copula "to", verb tagged by spaCy as a proper noun (false positive).

Run:
    python unit_tests/linguistics/sentence_check/generate_pdfs.py
'''
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS, build_latex

OUTPUT_DIR = Path(__file__).resolve().parent

SENTENCES_TP = [
    r"Najbardziej popularny model emocji opracowany przez Paula Ekmana.",
    r"W przyszłości można spodziewać się dalszego wzrostu liczby użytkowników.",
    r"Wpływ temperatury dyszy na średnią rezystancję próbek.",
]

SENTENCES_FP = [
    r"Pracę tę wspierali m.in. A. Staniszewski i B. Gruchelski oraz J. Nowak.",
    r"Model opisany w pracy K. Dośpiał-Borysiak został rozszerzony o nowe warstwy.",
    r"W 2019 r. Komisja Europejska ogłosiła nowy plan działań.",
    r"Model przetestowano na nowym zbiorze danych. Wykazał też słabą zdolność adaptacji do zmian oświetlenia.",
    r"Ból to subiektywne doświadczenie zmysłowe i emocjonalne.",
    r"Zakotwicza on się w strukturze materiału kompozytowego.",
    r"Podczas walidacji i testów augmentacja nie była wykorzystywana.",
    r"Ze względu na odmienny zakres przewidywań wartości straty w obu zadaniach nie były bezpośrednio porównywane.",
]

DOCUMENTS = {
    "tp_missing_subject_or_verb": SENTENCES_TP,
    "fp_correct_sentences": SENTENCES_FP,
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
    print("Done generating sentence check test PDFs.")


if __name__ == "__main__":
    main()
