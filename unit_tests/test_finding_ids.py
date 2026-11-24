import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.findings import assign_finding_ids, finding_label


def _err(page, y, x=10, **extra):
    return dict({"category": "TYPOS", "comment": "c", "page": page, "coords": {"x": x, "y": y, "w": 5, "h": 5}}, **extra)


class FindingIdsTest(unittest.TestCase):
    def test_numbers_follow_the_reading_order_not_the_stored_order(self):
        late, early, same_page_low = _err(7, 50), _err(2, 300), _err(2, 100)
        numbered = assign_finding_ids([late, early, same_page_low])
        self.assertEqual([e["finding_id"] for e in numbered], [3, 2, 1])
        self.assertNotIn("finding_id", late)         # the stored findings stay as they were

    def test_same_numbers_for_a_reordered_copy_of_the_list(self):
        errors = [_err(3, 10), _err(1, 20), _err(1, 5), _err(9, 1)]
        first = [e["finding_id"] for e in assign_finding_ids(errors)]
        again = [e["finding_id"] for e in assign_finding_ids(list(reversed(errors)))]
        self.assertEqual(first, list(reversed(again)))

    def test_findings_of_the_whole_document_come_after_those_of_the_pages(self):
        global_error = {"category": "No_footer", "comment": "g", "scope": "global"}
        page_error = _err(40, 10)
        numbered = assign_finding_ids([global_error, page_error])
        self.assertEqual([e["finding_id"] for e in numbered], [2, 1])

    def test_label(self):
        self.assertEqual(finding_label({"finding_id": 7}), "#7")
        self.assertEqual(finding_label({}), "")
        self.assertEqual(finding_label(None), "")

    def test_none_and_junk_are_tolerated(self):
        self.assertEqual(assign_finding_ids(None), [])
        self.assertEqual(assign_finding_ids([None, "x"]), [None, "x"])


if __name__ == "__main__":
    unittest.main()
