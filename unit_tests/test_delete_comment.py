"""The user can delete a comment they added: its marker and box go away and it is removed from the saved index."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui import styles  # noqa: E402
from ui.saving_files import SavingFiles  # noqa: E402
from ui.select_text import SelectablePdfView  # noqa: E402

app = QApplication.instance() or QApplication([])


def comment(text, w=0):
    coords = {"x": 10, "y": 20, "w": w, "h": 12} if w else {"x": 10, "y": 20}
    return {"page": 0, "strona": 1, "wspolrzedne": coords, "tekst_komentarza": text, "znaleziony_tekst": "Ala"}


class SavedCommentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = SavingFiles(Path(self.tmp.name) / "index.json")
        self.manager.add_document("praca.pdf", "/x/praca.pdf", "PDF")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_the_deleted_comment_is_removed_and_saved(self):
        first, second = comment("pierwszy"), comment("drugi")
        self.manager.save_comment("/x/praca.pdf", first)
        self.manager.save_comment("/x/praca.pdf", second)
        self.assertTrue(self.manager.delete_comment("/x/praca.pdf", dict(first)))     # an equal copy is enough
        self.assertEqual(self.manager.get_comments("/x/praca.pdf"), [second])
        reloaded = SavingFiles(Path(self.tmp.name) / "index.json")
        self.assertEqual(reloaded.get_comments("/x/praca.pdf"), [second])

    def test_unknown_comment_changes_nothing(self):
        self.manager.save_comment("/x/praca.pdf", comment("jest"))
        self.assertFalse(self.manager.delete_comment("/x/praca.pdf", comment("nie ma")))
        self.assertEqual(len(self.manager.get_comments("/x/praca.pdf")), 1)


class ViewTest(unittest.TestCase):
    def test_deleting_removes_the_marker_and_its_box(self):
        view = SelectablePdfView()
        kept = view.add_comment_marker(comment("zostaje", w=30), styles.HIGHLIGHT_BOX_COMMENT)
        gone = view.add_comment_marker(comment("do usunięcia", w=30), styles.HIGHLIGHT_BOX_COMMENT)
        deleted = []
        view.commentDeleted.connect(deleted.append)
        self.assertTrue(view.delete_comment(gone, confirm=False))
        self.assertEqual(view.comment_markers, [kept])
        self.assertEqual([box.data for box in view.highlight_boxes], [kept.data])
        self.assertEqual(deleted, [gone.data])


if __name__ == "__main__":
    unittest.main()
