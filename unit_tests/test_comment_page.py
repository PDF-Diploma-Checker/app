"""A comment is drawn and exported on the page where it was made (it used to land on the next page)."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.select_text import page_index  # noqa: E402


class PageIndexTest(unittest.TestCase):
    def test_findings_use_page_from_zero(self):
        self.assertEqual(page_index({"page": 4, "category": "TYPOS"}), 4)

    def test_new_comments_carry_page_from_zero(self):
        self.assertEqual(page_index({"page": 2, "strona": 3, "tekst_komentarza": "x"}), 2)

    def test_old_comments_count_strona_from_one(self):
        self.assertEqual(page_index({"strona": 3, "tekst_komentarza": "x"}), 2)


if __name__ == "__main__":
    unittest.main()
