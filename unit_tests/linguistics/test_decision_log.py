import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

from analysis.modules.linguistics import decision_log  # noqa: E402
from analysis.modules.linguistics.linguistics_types import Error_type  # noqa: E402


def match(content="kot", offset=4, category="TYPOS"):
    return Error_type(content=content, category=category, message="Możliwa literówka.", offset=offset,
                      error_length=len(content), block_id=7, page_start=3, page_end=3, word_idxs=[],
                      error_coordinate=[], rule="MORFOLOGIK", why="suggestions: ['kod']")


class DecisionLogTest(unittest.TestCase):
    def setUp(self):
        self.block = SimpleNamespace(contents="Ten kot działa.", language="pl",
                                     block=SimpleNamespace(block_id=7, type="paragraph"))

    def test_whole_sentence_is_given_with_the_finding_marked(self):
        text = "Pierwsze zdanie jest tu. Odczyt z dysku HDD trwał 120 ms, a zapis dłużej. Ostatnie zdanie jest tam."
        offset = text.index("HDD")
        self.assertEqual(decision_log.sentence_with_mark(text, offset, 3), "Odczyt z dysku «HDD» trwał 120 ms, a zapis dłużej.")

    def test_finding_over_a_whole_sentence_keeps_it_whole(self):
        text = "Pierwsze zdanie. Bez orzeczenia to. Trzecie zdanie."
        self.assertEqual(decision_log.sentence_with_mark(text, 17, 18), "«Bez orzeczenia to.»")

    def test_reported_line_holds_all_that_is_needed_to_judge_it(self):
        with self.assertLogs(decision_log.logger, "INFO") as logs:
            decision_log.report_sources([("language_tool", [found := match()])], [found], [self.block])
        line = logs.output[0]
        for part in ("[REPORTED]", "TYPOS", "source=language_tool", "rule=MORFOLOGIK", "page=3", "block=7/paragraph/pl",
                     "Możliwa literówka.", "suggestions", "found='kot'", "Ten «kot» działa."):
            self.assertIn(part, line)

    def test_finding_filtered_out_later_is_logged_with_the_reason(self):
        with self.assertLogs(decision_log.logger, "INFO") as logs:
            decision_log.report_sources([("dash_check", [match()])], [], [self.block])
        self.assertIn("[DROPPED]", logs.output[0])
        self.assertIn("inside an image", logs.output[0])

    def test_finding_with_a_word_number_for_offset_is_found_by_its_content(self):
        self.assertEqual(decision_log._match_context(match("działa", offset=2), self.block), "Ten kot «działa» .")

    def test_block_that_is_gone_does_not_break_the_log(self):
        with self.assertLogs(decision_log.logger, "INFO") as logs:
            decision_log.reported("list_check", match())
        self.assertIn("«kot»", logs.output[0])


if __name__ == "__main__":
    unittest.main()
