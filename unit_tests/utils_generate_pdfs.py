'''
Shared functions of the test PDF generators (unit_tests/**/generate_pdfs.py).

- build_latex - builds a document from a LaTeX template with pdflatex, xelatex or lualatex,
- build_writer - builds a document in LibreOffice Writer (equivalent of documents made in Word).

Both create a title page and a statement page (skipped by the analysis) and put the paragraphs on the next page.
'''
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

LATEX_COMPILERS = ("pdflatex", "xelatex", "lualatex")

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


def build_latex(name, paragraphs, compiler, workdir, template, output_dir):
    '''Inserts the paragraphs (LaTeX code, not escaped) in place of {paragraphs} in the template, compiles it
    and copies <name>_<compiler>.pdf to output_dir.'''
    tex_path = workdir / f"{name}_{compiler}.tex"
    tex_path.write_text(template.replace("{paragraphs}", "\n\n".join(paragraphs)), encoding="utf-8")
    subprocess.run(
        [compiler, "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
        cwd=workdir, check=True, stdout=subprocess.DEVNULL,
    )
    shutil.copy(tex_path.with_suffix(".pdf"), Path(output_dir) / tex_path.with_suffix(".pdf").name)


def build_writer(name, paragraphs, workdir, output_dir):
    '''Writes the paragraphs (plain text) to a .fodt file, converts it to PDF in LibreOffice (soffice)
    and copies <name>_libreoffice_writer.pdf to output_dir.'''
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
    shutil.copy(fodt_path.with_suffix(".pdf"), Path(output_dir) / fodt_path.with_suffix(".pdf").name)
