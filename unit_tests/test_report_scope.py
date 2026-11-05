import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from ui.report_bug import ReportDialog
except ImportError as error:    # e.g. a CI runner without the system libraries Qt needs (libEGL)
    raise unittest.SkipTest(str(error))


class ReportScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_thesis_is_not_sent_by_default(self):
        dialog = ReportDialog("https://relay.test/report", "thesis.pdf")
        self.assertTrue(dialog.logs_only.isChecked())
        self.assertIsNone(dialog.selected_thesis())

    def test_thesis_sent_only_after_choosing_it(self):
        dialog = ReportDialog("https://relay.test/report", "thesis.pdf")
        dialog.with_thesis.setChecked(True)
        self.assertEqual(dialog.selected_thesis(), "thesis.pdf")

    def test_changing_the_scope_asks_for_consent_again(self):
        dialog = ReportDialog("https://relay.test/report", "thesis.pdf")
        dialog.consent.setChecked(True)
        dialog.with_thesis.setChecked(True)
        self.assertFalse(dialog.consent.isChecked())
        self.assertFalse(dialog.send_btn.isEnabled())

    def test_no_open_thesis_no_choice(self):
        dialog = ReportDialog("https://relay.test/report", None)
        self.assertFalse(dialog.with_thesis.isEnabled())
        self.assertIsNone(dialog.selected_thesis())


if __name__ == "__main__":
    unittest.main()
