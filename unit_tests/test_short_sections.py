"""A section with (almost) no text is not summarised: the model would make a summary up."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.extraction.helper_llm.get_subtitles import MIN_SECTION_CHARS, has_enough_text  # noqa: E402


class EnoughTextTest(unittest.TestCase):
    def test_headings_and_garbled_lines_are_not_enough(self):
        self.assertFalse(has_enough_text(""))
        self.assertFalse(has_enough_text(None))
        self.assertFalse(has_enough_text("PRZEGL ˛ AD ISTNIEJ ˛ ACYCH ROZWI ˛ AZA ´ N"))
        self.assertFalse(has_enough_text("   " + "x" * (MIN_SECTION_CHARS - 1) + "   "))

    def test_a_short_but_real_section_is_enough(self):
        text = "Ta sekcja jest krótka, ale zawiera trzy pełne zdania. Opisuje cel badania. Wskazuje metodę pracy."
        self.assertGreaterEqual(len(text), MIN_SECTION_CHARS)
        self.assertTrue(has_enough_text(text))


class SummariesTest(unittest.TestCase):
    """get_summaries needs the AI libraries (llama_cpp); the build of the CI has none, so these tests skip there."""

    def setUp(self):
        try:
            from analysis.modules.llm import get_summary
        except Exception as error:
            self.skipTest(f"AI libraries are not available: {error}")
        self.get_summary = get_summary

    def test_sections_without_text_are_marked_and_never_given_to_the_model(self):
        subtitles = [
            {"number": "1.1", "title": "Wstęp", "content": "Pierwsza sekcja ma wystarczająco dużo tekstu. " * 6},
            {"number": "1.4", "title": "Plan pracy", "content": "PRZEGL ˛ AD ISTNIEJ ˛ ACYCH ROZWI ˛ AZA ´ N"},
            {"number": "1.5", "title": "Pusta", "content": ""},
        ]
        with mock.patch.object(self.get_summary, "get_summary", side_effect=lambda text, lang: "Streszczenie.") as model:
            items = self.get_summary.get_summaries(subtitles, "pl")
        self.assertEqual([item["summary"] for item in items],
                         ["Streszczenie.", "[BRAK TREŚCI W SEKCJI]", "[BRAK TREŚCI W SEKCJI]"])
        self.assertEqual(model.call_count, 1)


if __name__ == "__main__":
    unittest.main()
