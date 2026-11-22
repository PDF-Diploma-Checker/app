import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.extraction.helper_llm.converter_linguistics_llm import block_text
from analysis.extraction.helper_llm.ending_fragment import extract_ending_fragment
from analysis.extraction.helper_llm.get_subtitles import collect_section_text, next_heading_index

APPENDIX = "Dodatek B: Podsumowanie audytu dostępności aplikacji Dnia 30.09.2026 firma przeprowadziła audyt aplikacji."
FILLER = "Opis prototypu i wyników badań. " * 5


def _paragraph(text):
    return NS(type="paragraph", content=text)


def _list(*items):
    return NS(type="list", content="\n".join(items), items=[NS(text=item) for item in items])


class EndingFragmentTest(unittest.TestCase):
    def test_numbered_chapter_is_the_end_not_the_appendix(self):
        text = (f"5.1. Wnioski z pomiarów {FILLER} 7. PODSUMOWANIE 7.1. Realizacja celu pracy Cel został osiągnięty. {FILLER * 4} "
                f"Wykaz literatury 1. Kowalski. Wykaz rysunków {APPENDIX}")
        fragment = extract_ending_fragment(text)
        self.assertTrue(fragment.startswith("7. PODSUMOWANIE"))
        self.assertIn("Cel został osiągnięty", fragment)
        self.assertNotIn("audytu", fragment)

    def test_fragment_stops_before_the_bibliography(self):
        text = f"{FILLER} 7. PODSUMOWANIE 7.1. Realizacja celu pracy {FILLER * 3} Wykaz literatury 1. Kowalski. Wykaz rysunków"
        fragment = extract_ending_fragment(text)
        self.assertIn("Realizacja celu pracy", fragment)
        self.assertNotIn("Kowalski", fragment)

    def test_subsection_of_conclusions_is_not_the_end(self):
        text = f"3.9.2. Wnioski z analizy {FILLER} 7. Podsumowanie 7.1. Realizacja celu {FILLER}"
        self.assertTrue(extract_ending_fragment(text).startswith("7. Podsumowanie"))

    def test_unnumbered_chapter_is_found_and_a_longer_title_is_not(self):
        text = f"{FILLER} PODSUMOWANIE Celem pracy było zbudowanie urządzenia. Cel osiągnięto. {FILLER} {APPENDIX}"
        fragment = extract_ending_fragment(text)
        self.assertTrue(fragment.startswith("PODSUMOWANIE Celem pracy"))

    def test_phrase_inside_a_sentence_is_not_a_heading(self):
        text = "Rozdział siódmy zawiera podsumowanie pracy i wnioski z badań. " + FILLER * 20
        fragment = extract_ending_fragment(text)
        self.assertFalse(fragment.startswith("podsumowanie"))
        self.assertTrue(text.strip().endswith(fragment))

    def test_thesis_without_any_heading_uses_its_tail(self):
        text = "x" * 20000
        self.assertEqual(len(extract_ending_fragment(text)), 9000)


class SectionTextTest(unittest.TestCase):
    def test_list_items_are_part_of_the_section(self):
        blocks = [_paragraph("7.3. Wnioski"),
                  _paragraph("Sformułowano następujące wnioski:"),
                  _list("serwomechanizmy pozwalają zbudować tanie urządzenie,", "niezawodność ruchu wymaga poprawy."),
                  _paragraph("7.4. Kierunki rozwoju")]
        text = collect_section_text(blocks, 0, 3)
        self.assertIn("Sformułowano następujące wnioski:", text)
        self.assertIn("serwomechanizmy pozwalają zbudować tanie urządzenie; niezawodność ruchu wymaga poprawy.", text)

    def test_captions_are_not(self):
        blocks = [_paragraph("7.3. Wnioski"), NS(type="img_decription", content="Rys. 7.1. Schemat"),
                  _paragraph("Treść sekcji.")]
        self.assertEqual(collect_section_text(blocks, 0, 3), "Treść sekcji.")

    def test_last_section_ends_at_the_bibliography(self):
        blocks = [_paragraph("7.4.4. Badania"), _paragraph("Treść sekcji."), _paragraph("Wykaz literatury"),
                  _list("1. Kowalski. Tytuł.")]
        end = next_heading_index(blocks, 0, 3)
        self.assertEqual(end, 2)
        self.assertEqual(collect_section_text(blocks, 0, end), "Treść sekcji.")


class BlockTextTest(unittest.TestCase):
    def test_items_do_not_run_together_and_keep_no_stray_punctuation(self):
        self.assertEqual(block_text(_list("lepsze pasowanie,", "wyraźniejsza różnica,", "oznaczenie przodu.")),
                         "lepsze pasowanie; wyraźniejsza różnica; oznaczenie przodu.")

    def test_list_without_final_stop_gets_one(self):
        self.assertEqual(block_text(_list("jeden", "dwa")), "jeden; dwa.")

    def test_table_of_contents_is_not_text_of_the_thesis(self):
        toc = _list("Wstęp . . . . . . . . . . . . 6", "Cel pracy . . . . . . . . . . . . 7", "2.3 Model urządzenia 49")
        self.assertEqual(block_text(toc), "")

    def test_item_of_a_toc_list_is_dropped_but_the_rest_stays(self):
        self.assertEqual(block_text(_list("Wstęp . . . . . . . . 6", "pierwszy punkt,", "drugi punkt.")), "pierwszy punkt; drugi punkt.")

    def test_paragraph_is_unchanged(self):
        self.assertEqual(block_text(_paragraph("Zwykły  akapit.")), "Zwykły akapit.")


if __name__ == "__main__":
    unittest.main()
