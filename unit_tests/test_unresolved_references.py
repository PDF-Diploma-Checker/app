"""Cross-references and citations that LaTeX could not resolve ("??", "[?]") are reported by the redaction module.

Thesis from 2026-11-24: "opisano go w podrozdziale ??." was not reported by any check.

Run:
    uv run python -m unittest unit_tests/test_unresolved_references.py -v
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.redaction.redaction_validator import RedactionValidator


def _words(text, page=5):
    words, pos = [], 0
    for i, part in enumerate(text.split(" ")):
        words.append(NS(text=part, start_char=pos, end_char=pos + len(part), page_number=page,
                        bbox=(10.0 * i, 100.0, 10.0 * i + 8, 112.0)))
        pos += len(part) + 1
    return words


def _paragraph(text, block_type="paragraph", page=5):
    return NS(type=block_type, content=text, words=_words(text, page), is_bibliography=False)


def _errors(*blocks, language="pl"):
    validator = RedactionValidator(document_data=None, document_data_linguistics=NS(logical_blocks=list(blocks)),
                                   language=language)
    validator.check_unresolved_references()
    return validator.errors


def _found(text, **kwargs):
    return [(e.category, e.text) for e in _errors(_paragraph(text, **kwargs))]


class UnresolvedReferenceTest(unittest.TestCase):
    def test_ref_reported(self):
        errors = _errors(_paragraph("Zbiór opisano go w podrozdziale ??. Zbiór obejmuje strony."))
        self.assertEqual([(e.category, e.text) for e in errors], [("unresolved_reference", "??")])
        self.assertEqual(errors[0].page_number, 5)
        self.assertEqual(errors[0].bounding_box, [50.0, 100.0, 58.0, 112.0])   # the word "??."
        self.assertIn("Niewygenerowane odwołanie", errors[0].comments)

    def test_several_refs(self):
        self.assertEqual(_found("Pokazano na rysunku ?? (tabela ??)."),
                         [("unresolved_reference", "??"), ("unresolved_reference", "??")])

    def test_english_comment(self):
        errors = _errors(_paragraph("As shown in Section ??, it works."), language="en")
        self.assertTrue(errors[0].comments.startswith("Unresolved reference"))

    def test_question_marks_not_reported(self):
        for text in ["Czy to działa? Tak.", "Naprawdę?! Nie wierzę.", "Co dalej???"]:
            with self.subTest(text=text):
                self.assertEqual(_found(text), [])


class UnresolvedCitationTest(unittest.TestCase):
    def test_citations_reported(self):
        self.assertEqual(_found("Opisano w [?] oraz w [3, ?] i [?; ?]."),
                         [("unresolved_citation", "[?]"), ("unresolved_citation", "[3, ?]"),
                          ("unresolved_citation", "[?; ?]")])

    def test_resolved_citations_not_reported(self):
        self.assertEqual(_found("Opisano w [12], [3, 5] oraz [6–9]."), [])


class SkippedBlocksTest(unittest.TestCase):
    def test_math_and_bibliography_skipped(self):
        bibliography = _paragraph("Autor [?] tytuł ??")
        bibliography.is_bibliography = True
        self.assertEqual(_errors(_paragraph("x ?? y", block_type="math"), bibliography), [])

    def test_list_items_checked(self):
        item = NS(text="opis w rozdziale ??", words=_words("opis w rozdziale ??"))
        block = NS(type="list", items=[item], is_bibliography=False)
        self.assertEqual([e.text for e in _errors(block)], ["??"])


if __name__ == "__main__":
    unittest.main()
