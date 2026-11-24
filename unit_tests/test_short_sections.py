"""A section with (almost) no text is not summarised: the model would make a summary up."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.llm import get_summary  # noqa: E402


class ShortSectionsTest(unittest.TestCase):
    def test_sections_without_text_are_marked_and_never_given_to_the_model(self):
        subtitles = [
            {"number": "1.1", "title": "Wstęp", "content": "Pierwsza sekcja ma wystarczająco dużo tekstu. " * 6},
            {"number": "1.4", "title": "Plan pracy", "content": "PRZEGL ˛ AD ISTNIEJ ˛ ACYCH ROZWI ˛ AZA ´ N"},
            {"number": "1.5", "title": "Pusta", "content": ""},
        ]
        with mock.patch.object(get_summary, "get_summary", side_effect=lambda text, lang: "Streszczenie.") as model:
            items = get_summary.get_summaries(subtitles, "pl")
        self.assertEqual([item["summary"] for item in items],
                         ["Streszczenie.", "[BRAK TREŚCI W SEKCJI]", "[BRAK TREŚCI W SEKCJI]"])
        self.assertEqual(model.call_count, 1)

    def test_a_short_but_real_section_is_still_summarised(self):
        text = "Ta sekcja jest krótka, ale zawiera trzy pełne zdania. Opisuje cel badania. Wskazuje metodę pracy."
        self.assertGreaterEqual(len(text), get_summary.MIN_SECTION_CHARS)
        with mock.patch.object(get_summary, "get_summary", return_value="Streszczenie.") as model:
            get_summary.get_summaries([{"number": "2", "title": "T", "content": text}], "pl")
        self.assertEqual(model.call_count, 1)


if __name__ == "__main__":
    unittest.main()
