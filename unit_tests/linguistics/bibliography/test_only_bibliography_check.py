'''
W bloku bibliografii (is_bibliography=True) wyświetlane są tylko błędy z bibliography_check.

- moduł językowy (keep_only_bibliography_check_in_bibliography): błędy innych źródeł w bloku bibliografii są
  odrzucane, błędy bibliography_check i błędy spoza bibliografii zostają,
- moduł redakcyjny (remove_errors_from_bibliography): błędy leżące w obszarze słów bibliografii na danej stronie
  (np. wdowa "modelVersionId=2617751." z rozbitego URL-a) są odrzucane; błędy poza tym obszarem, na innej
  stronie i bez miejsca na stronie (bbox 0, np. podsumowanie bibliografii) zostają.

Uruchomienie (z katalogu app/):
    .venv/Scripts/python.exe -m unittest unit_tests.linguistics.bibliography.test_only_bibliography_check -v
'''
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics.run_linguistics import keep_only_bibliography_check_in_bibliography
from analysis.modules.redaction.redaction_validator import RedactionValidator

BIB_TEXT = "MONKEYFOREVER. Realistic Snapshot [online]. 2026. https://civitai.com/models/2268008?modelVersionId=2617751."
PARAGRAPH_TEXT = "Dane przesyłane są z częstotliwością 3200 Hz."


def context_block(block_id, text, is_bibliography):
    '''A block as run_linguistics sees it (get_context): the schema block in .block, the text in .contents.'''
    return NS(block=NS(block_id=block_id, type="list" if is_bibliography else "paragraph", is_bibliography=is_bibliography),
              contents=text, language="pl")


def match(block_id, content, text):
    return NS(block_id=block_id, content=content, offset=text.index(content), category="PUNCTUATION", rule="RULE")


class TestLinguisticsInBibliography(unittest.TestCase):
    def setUp(self):
        self.blocks = [context_block("list_1", BIB_TEXT, True), context_block(2, PARAGRAPH_TEXT, False)]

    def kept(self, sources):
        return {source: matches for source, matches in keep_only_bibliography_check_in_bibliography(sources, self.blocks)}

    def test_other_sources_dropped_in_bibliography(self):
        for source in ("language_tool", "sentence_check", "dash_check", "decimal_check", "list_check", "acronym_check"):
            with self.subTest(source=source):
                kept = self.kept([(source, [match("list_1", "Realistic Snapshot", BIB_TEXT)])])
                self.assertEqual(kept[source], [])

    def test_bibliography_check_kept_in_bibliography(self):
        finding = match("list_1", "MONKEYFOREVER", BIB_TEXT)
        self.assertEqual(self.kept([("bibliography_check", [finding])])["bibliography_check"], [finding])

    def test_findings_outside_bibliography_kept(self):
        finding = match(2, "3200 Hz", PARAGRAPH_TEXT)
        self.assertEqual(self.kept([("language_tool", [finding])])["language_tool"], [finding])

    def test_mixed_source_keeps_only_paragraph_findings(self):
        in_bib, in_text = match("list_1", "Realistic Snapshot", BIB_TEXT), match(2, "3200 Hz", PARAGRAPH_TEXT)
        self.assertEqual(self.kept([("language_tool", [in_bib, in_text])])["language_tool"], [in_text])

    def test_sources_order_preserved(self):
        sources = [("language_tool", []), ("bibliography_check", []), ("first_definition", [])]
        self.assertEqual([s for s, _ in keep_only_bibliography_check_in_bibliography(sources, self.blocks)],
                         ["language_tool", "bibliography_check", "first_definition"])


def word(text, bbox, page):
    return NS(text=text, bbox=bbox, page_number=page)


def error(category, page, bbox, text="x"):
    return NS(category=category, page_number=page, bounding_box=bbox, text=text)


class TestRedactionInBibliography(unittest.TestCase):
    def remaining(self, errors, blocks):
        validator = NS(errors=list(errors), document_data_linguistics=NS(logical_blocks=blocks))
        RedactionValidator.remove_errors_from_bibliography(validator)
        return validator.errors

    def bibliography(self):
        # wpis rozbity na dwie strony: koniec URL-a na stronie 62 w osobnym wierszu
        item_1 = NS(words=[word("HO,", (70, 100, 90, 112), 61), word("Models.", (400, 300, 450, 312), 61)])
        item_2 = NS(words=[word("MONKEYFOREVER.", (70, 80, 160, 92), 62),
                           word("modelVersionId=2617751.", (70, 96, 200, 108), 62)])
        return NS(is_bibliography=True, items=[item_1, item_2], words=[])

    def paragraph(self):
        return NS(is_bibliography=False, words=[word("Wstęp", (70, 100, 500, 400), 5)])

    def test_widow_in_bibliography_removed(self):
        widow = error("widow", 62, (70, 96, 200, 108), "modelVersionId=2617751.")
        self.assertEqual(self.remaining([widow], [self.bibliography()]), [])

    def test_any_category_inside_bibliography_removed(self):
        errors = [error(c, 61, (75, 150, 120, 162)) for c in ("orphan", "bastard", "shoe_maker", "justification")]
        self.assertEqual(self.remaining(errors, [self.bibliography()]), [])

    def test_error_on_other_page_kept(self):
        widow = error("widow", 5, (70, 96, 200, 108))
        self.assertEqual(self.remaining([widow], [self.bibliography(), self.paragraph()]), [widow])

    def test_error_outside_bibliography_area_kept(self):
        footer = error("footer", 62, (280, 780, 320, 795))           # numer strony pod bibliografią
        self.assertEqual(self.remaining([footer], [self.bibliography()]), [footer])

    def test_global_error_kept(self):
        summary = error("bibliography_summary", 62, (0, 0, 0, 0))
        self.assertEqual(self.remaining([summary], [self.bibliography()]), [summary])

    def test_area_is_per_page(self):
        # obszar strony 62 kończy się na y=108; to samo miejsce na stronie 61 też należy do bibliografii (do y=312)
        self.assertEqual(len(self.remaining([error("orphan", 62, (70, 250, 100, 262))], [self.bibliography()])), 1)
        self.assertEqual(self.remaining([error("orphan", 61, (70, 250, 100, 262))], [self.bibliography()]), [])

    def test_no_bibliography_keeps_everything(self):
        errors = [error("widow", 5, (70, 380, 120, 392))]
        self.assertEqual(self.remaining(errors, [self.paragraph()]), errors)


if __name__ == "__main__":
    unittest.main()
