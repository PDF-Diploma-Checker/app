r'''
Generates test PDFs for checking acronyms written in math font and math expressions
with different compilers (pdflatex, xelatex, lualatex).


File names describe the expected result:
- tp_undefined_math_font_acronym_<compiler>.pdf - undefined acronyms in math font,
  which must be reported (true positive),
- fp_math_expressions_<compiler>.pdf - equations, Greek letters and math symbols,
  which must not be reported as acronyms (false positive),
- fp_defined_math_font_acronym_<compiler>.pdf - acronyms in math font defined before use,
  which must not be reported (false positive),
- fp_acronym_list_subscript_<compiler>.pdf - acronyms defined in the list of acronyms and used later
  as subscripts in equations, which must not be reported (false positive),
- tp_acronym_list_subscript_<compiler>.pdf - subscript acronyms missing from the list of acronyms
  or defined in the text only after use, which must be reported (true positive).

Run (from the repository root):
    python unit_tests/linguistics/acronyms/generate_pdfs.py
'''
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from unit_tests.utils_generate_pdfs import LATEX_COMPILERS, build_latex

OUTPUT_DIR = Path(__file__).resolve().parent

DOCUMENTS = {
    "tp_undefined_math_font_acronym": [
        r"Model $\mathbf{QXV}$ osiąga lepsze wyniki niż poprzednie podejścia.",
        r"Zastosowano metodę $\mathit{KXV}$ do wstępnego przetwarzania danych.",
        r"Dane zapisano w formacie $\mathsf{JXW}$ na serwerze uczelni.",
        r"Konfigurację przechowuje plik $\mathtt{YXV}$ w katalogu projektu.",
        r"Architektura $\symbf{VXW}$ składa się z trzech warstw.",
        r"Wariant $\symit{XWV}$ różni się sposobem uczenia.",
        r"Biblioteka $\symsf{KWX}$ udostępnia gotowe implementacje.",
        r"Narzędzie $\symtt{ZQX}$ służy do analizy logów.",
        r"Przestrzeń $\mathbb{GXW}$ zawiera wszystkie stany układu.",
        r"Rodzina $\mathcal{DXW}$ opisuje dopuszczalne rozwiązania.",
        r"Algebra $\mathfrak{WXJ}$ jest przemienna.",
        r"Zbiór $\mathbb{RXV}$ zawiera wszystkie wyniki pomiarów.",
        r"Klasa $\mathcal{HXW}$ grupuje podobne obiekty.",
        r"Struktura $\mathfrak{HXV}$ ma skończony wymiar.",
        r"Protokół TXV zapewnia szyfrowanie połączenia.",
    ],
    "fp_math_expressions": [
        r"W dalszej części pracy przyjęto, że dla każdego $\forall x \in \mathbb{R}$ zachodzi zależność "
        r"$f(x) = \sqrt{x^2 + \pi}$, co upraszcza dalsze rozważania dotyczące stabilności całego układu sterowania.",
        r"Wykazano również, że suma $\sum_{i=1}^{n} \alpha_i \leq \Omega$ pozostaje ograniczona, nawet gdy liczba "
        r"elementów rośnie, czyli dla $n \to \infty$, co potwierdzają przeprowadzone eksperymenty numeryczne.",
        r"Ponadto istnieje element $\exists y \notin \emptyset$ taki, że gradient $\nabla f(y) \neq 0$, dlatego "
        r"zastosowana metoda optymalizacji nie zatrzymuje się w punkcie początkowym.",
        r"Całka $\int_0^1 \partial_x g \, dx \approx \lambda \cdot \mu$ jest skończona, a jej wartość można "
        r"oszacować na podstawie wyników uzyskanych w poprzednim rozdziale niniejszej pracy.",
        r"Przyjęto oznaczenia $\Delta \Sigma = \Phi \times \Psi \pm \Gamma$ oraz $\Theta \Rightarrow \Lambda$, "
        r"które są zgodne z notacją stosowaną w literaturze przedmiotu.",
        r"Otrzymana wartość $\sqrt[3]{\Xi} \div \Pi$ wynosi około $\sigma^2$, co mieści się w przedziale "
        r"tolerancji określonym w wymaganiach projektowych.",
        r"Macierz $\symbf{A}\symbf{B}$ oraz wektor $\symbf{x}$ wyznaczono metodą najmniejszych kwadratów, "
        r"korzystając z danych zebranych podczas pomiarów laboratoryjnych.",
    ],
    "fp_defined_math_font_acronym": [
        r"Wektor $\mathbf{QXV}$ (ang. Quick Xray Vector) jest podstawą modelu.",
        r"Wyniki pokazują, że $\mathbf{QXV}$ poprawia dokładność o kilka punktów.",
        r"Metoda $\symsf{JXW}$ (ang. Joint Xray Weighting) wymaga kalibracji.",
        r"Porównano $\symsf{JXW}$ z innymi metodami.",
        r"Przestrzeń $\mathbb{GXW}$ (ang. Global Xray Wave) zawiera wszystkie stany układu.",
        r"Każdy stan należy do $\mathbb{GXW}$ dokładnie raz.",
        r"Rodzina $\mathcal{MXW}$ (ang. Multi Xray Weighting) opisuje dopuszczalne rozwiązania.",
        r"Każde rozwiązanie z $\mathcal{MXW}$ spełnia ograniczenia.",
    ],
    # List of acronyms on a separate page, the "Wstęp" heading ends the list
    "fp_acronym_list_subscript": [
        r"\section*{Wykaz skrótów}",
        r"\noindent QXV -- Quick Xray Vector \\ KXV -- Kernel Xray Variance \\ JXW -- Joint Xray Weighting \\ "
        r"$\mathbb{GXW}$ -- Global Xray Wave \\ $\mathcal{MXW}$ -- Multi Xray Weighting \\ YXV -- Yield Xray Value",
        r"\clearpage",
        r"\section{Wstęp}",
        # Every sentence has plenty of plain text, so that is_math does not treat lines with equations as a formula
        r"W trakcie wszystkich pomiarów przeprowadzonych w laboratorium zaobserwowano, że energia "
        r"$E_{\mathrm{QXV}} \in \mathbb{R}$ rośnie wraz z temperaturą otoczenia oraz z czasem trwania eksperymentu.",
        r"Na podstawie zebranych danych stwierdzono, że wariancja $\sigma_{\text{KXV}} = \sqrt{\lambda}$ zależy "
        r"przede wszystkim od liczby próbek zebranych w poszczególnych seriach eksperymentu.",
        # The line with \sum is dominated by math fonts and goes to page_artifacts together with the subscript
        r"W kolejnym kroku współczynnik $\lambda_{\symbf{JXW}} \leq \sum_{i=1}^{n} \alpha_i$ dobrano metodą "
        r"walidacji krzyżowej, porównując wyniki uzyskane dla kilku różnych podziałów zbioru danych.",
        r"Dla porównania w drugiej części badań wartość współczynnika $\lambda_{\symbf{JXW}} > 0$ ustalono "
        r"ręcznie, kierując się doświadczeniem zdobytym podczas wcześniejszych prób.",
        r"Przeprowadzone symulacje pokazały, że prawdopodobieństwo $P_{\mathbb{GXW}} \to 0$ maleje dla dużych "
        r"wartości parametru $\theta$, co jest zgodne z wynikami opisanymi w literaturze przedmiotu.",
        r"Przyjęto, że dla każdego $\forall x \in X$ wagę $w_{\mathcal{MXW}}(x) \neq 0$ wyznacza się na podstawie "
        r"danych treningowych, a następnie weryfikuje na niezależnym zbiorze testowym.",
        r"Otrzymana w ostatniej serii pomiarów wartość $T_{YXV} \approx \pi$ przekracza próg określony "
        r"w wymaganiach projektowych, dlatego konieczna była ponowna kalibracja urządzenia.",
    ],
    # Only QXV and KXV are in the list - the other subscript acronyms are undefined,
    # DXW is defined in the text only on the next page, after its use in a subscript
    "tp_acronym_list_subscript": [
        r"\section*{Wykaz skrótów}",
        r"\noindent QXV -- Quick Xray Vector \\ KXV -- Kernel Xray Variance",
        r"\clearpage",
        r"\section{Wstęp}",
        r"W trakcie wszystkich pomiarów przeprowadzonych w laboratorium zaobserwowano, że energia "
        r"$E_{\mathrm{VXW}} \in \mathbb{R}$ rośnie wraz z temperaturą otoczenia oraz z czasem trwania eksperymentu.",
        r"Na podstawie zebranych danych stwierdzono, że wariancja $\sigma_{\text{XWV}} = \sqrt{\lambda}$ zależy "
        r"przede wszystkim od liczby próbek zebranych w poszczególnych seriach eksperymentu.",
        r"Dla porównania w drugiej części badań wartość współczynnika $\lambda_{\symbf{KWX}} > 0$ ustalono "
        r"ręcznie, kierując się doświadczeniem zdobytym podczas wcześniejszych prób.",
        r"Przeprowadzone symulacje pokazały, że prawdopodobieństwo $P_{\mathbb{GXW}} \to 0$ maleje dla dużych "
        r"wartości parametru $\theta$, co jest zgodne z wynikami opisanymi w literaturze przedmiotu.",
        r"Przyjęto, że dla każdego $\forall x \in X$ wagę $w_{\mathcal{HXW}}(x) \neq 0$ wyznacza się na podstawie "
        r"danych treningowych, a następnie weryfikuje na niezależnym zbiorze testowym.",
        r"Otrzymana w ostatniej serii pomiarów wartość $T_{ZQX} \approx \pi$ przekracza próg określony "
        r"w wymaganiach projektowych, dlatego konieczna była ponowna kalibracja urządzenia.",
        r"Wyznaczony w pierwszej serii pomiarów błąd $\epsilon_{\mathrm{DXW}} \ll 1$ okazał się pomijalnie mały "
        r"w porównaniu z niepewnością wynikającą z rozdzielczości aparatury.",
        # Acronym from the list in a subscript - must not be reported
        r"Zgodnie z oczekiwaniami energia $E_{\mathrm{QXV}} \geq 0$ pozostawała nieujemna przez cały czas trwania "
        r"pomiarów, niezależnie od ustawień aparatury.",
        r"\clearpage",
        r"Metoda DXW (ang. Dense Xray Weighting) została szczegółowo opisana w kolejnym rozdziale pracy.",
    ],
}

LATEX_TEMPLATE = r'''\documentclass[12pt,a4paper]{article}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[T1]{fontenc}
  \usepackage[utf8]{inputenc}
  \usepackage{lmodern}
  \usepackage{amsmath,amssymb}
  \newcommand{\symbf}{\mathbf}
  \newcommand{\symit}{\mathit}
  \newcommand{\symsf}{\mathsf}
  \newcommand{\symtt}{\mathtt}
\else
  \usepackage{fontspec}
  \usepackage{amsmath}
  \usepackage{unicode-math}
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
