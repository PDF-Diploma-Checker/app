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
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

OUTPUT_DIR = Path(__file__).resolve().parent

LATEX_COMPILERS = ("pdflatex", "xelatex", "lualatex")

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

FODT_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.3" office:mimetype="application/vnd.oasis.opendocument.text">
 <office:automatic-styles>
  <style:style style:name="Body" style:family="paragraph">
   <style:paragraph-properties fo:text-align="justify"/>
   <style:text-properties fo:font-size="12pt"/>
  </style:style>
  <style:style style:name="NewPage" style:family="paragraph" style:parent-style-name="Body">
   <style:paragraph-properties fo:break-before="page"/>
  </style:style>
 </office:automatic-styles>
 <office:body><office:text>
  <text:p text:style-name="Body">Praca dyplomowa</text:p>
  <text:p text:style-name="NewPage">Oświadczenie autora pracy.</text:p>
{paragraphs}
 </office:text></office:body>
</office:document>
'''


def build_latex(name, paragraphs, compiler, workdir):
    tex_path = workdir / f"{name}_{compiler}.tex"
    tex_path.write_text(LATEX_TEMPLATE.replace("{paragraphs}", "\n\n".join(p.replace("%", r"\%") for p in paragraphs)), encoding="utf-8")
    subprocess.run(
        [compiler, "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
        cwd=workdir, check=True, stdout=subprocess.DEVNULL,
    )
    shutil.copy(tex_path.with_suffix(".pdf"), OUTPUT_DIR / tex_path.with_suffix(".pdf").name)


def build_writer(name, paragraphs, workdir):
    fodt_path = workdir / f"{name}_libreoffice_writer.fodt"
    body = "\n".join(
        f'  <text:p text:style-name="{"NewPage" if i == 0 else "Body"}">{escape(p)}</text:p>'
        for i, p in enumerate(paragraphs)
    )
    fodt_path.write_text(FODT_TEMPLATE.replace("{paragraphs}", body), encoding="utf-8")
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(workdir), str(fodt_path)],
        check=True, stdout=subprocess.DEVNULL,
    )
    shutil.copy(fodt_path.with_suffix(".pdf"), OUTPUT_DIR / fodt_path.with_suffix(".pdf").name)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for name, paragraphs in DOCUMENTS.items():
            for compiler in LATEX_COMPILERS:
                build_latex(name, paragraphs, compiler, workdir)
            build_writer(name, paragraphs, workdir)


if __name__ == "__main__":
    main()
