'''
Generuje PDF-y testowe dla sprawdzania separatora dziesiętnego w różnych kompilatorach
(pdflatex, xelatex, lualatex) oraz w LibreOffice Writer (odpowiednik dokumentów z Worda).

Nazwy plików mówią, jakiego wyniku oczekujemy:
- fp_unnecessarily_detected_dot_<kompilator>.pdf - kropki, które NIE są separatorem dziesiętnym
  (odwołania do rozdziałów, rysunków, wersji), wcześniej niepotrzebnie wykrywane (false positive),
- tp_correctly_detected_dot_<kompilator>.pdf - kropki użyte jako separator dziesiętny w polskim tekście,
  które muszą zostać wykryte (true positive).

Uruchomienie (z katalogu głównego repozytorium):
    python unit_tests/linguistics/decimal_point/generate_pdfs.py
'''
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS, build_latex, build_writer  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent

# Akapity umieszczane na stronie z treścią. Strony 0 i 1 (tytułowa i oświadczenie) są pomijane przez analizę.
DOCUMENTS = {
    "fp_unnecessarily_detected_dot": [
        "Szczegółowe omówienie powyższego szacowania ceny aktywu znajduje się w kolejnym podrozdziale 3.1.",
        "Wyniki eksperymentów przedstawiono w sekcji 2.4 oraz w punkcie 1.2 niniejszej pracy.",
        "Zależność pokazano na rysunku 2.1, a dane zebrano w tabeli 2.1 i 2.2.",
        "Kod źródłowy aplikacji umieszczono w załączniku 1.3.",
        "Metodę opisaną w podrozdz. 4.2 zastosowano ponownie.",
        "Biblioteka w wersji 3.12 została zaktualizowana.",
    ],
    "tp_correctly_detected_dot": [
        "Średnia wartość portfela inwestora wyniosła 3.5 jednostki.",
        "Cena aktywu wzrosła o 2.75% w ciągu roku.",
        "Rozmiar to 4.2 metra.",
        "Dodatkowo 6.5 kilograma materiału zużyto w trakcie testów.",
        "Punktacja to 7.25 w skali dziesięciostopniowej.",
    ],
}

LATEX_TEMPLATE = r'''\documentclass[12pt,a4paper]{article}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[T1]{fontenc}
  \usepackage[utf8]{inputenc}
\else
  \usepackage{fontspec}
\fi
\usepackage{hyperref}
% Bez dzielenia wyrazów, żeby słowa kluczowe (np. "podrozdziale") nie były rozdzielane między linie
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
            # Akapity to zwykły tekst - "%" w LaTeX-u zaczyna komentarz
            latex_paragraphs = [p.replace("%", r"\%") for p in paragraphs]
            for compiler in LATEX_COMPILERS:
                build_latex(name, latex_paragraphs, compiler, workdir, LATEX_TEMPLATE, OUTPUT_DIR)
            build_writer(name, paragraphs, workdir, OUTPUT_DIR)


if __name__ == "__main__":
    main()
