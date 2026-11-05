"""The findings in the results panel and the settings in plain words."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
except ImportError as error:    # e.g. a CI runner without the system libraries Qt needs (libEGL)
    raise unittest.SkipTest(f"Qt is not available: {error}")


class FindingsSectionTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def panel(self, errors, report_data=None, on_page=lambda index: None):
        from ui.report_panel import build_report_panel
        content, _ = build_report_panel({} if report_data is None else report_data, lambda: None, errors, on_page)
        return content

    def test_count_and_a_button_per_page_that_shows_it(self):
        shown = []
        content = self.panel([{"page": 4}, {"page": 4}, {"page": 0}], on_page=shown.append)
        texts = " | ".join(label.text() for label in content.findChildren(QLabel))
        self.assertIn("Uwagi: 3, strony: 2", texts)
        buttons = {b.text(): b for b in content.findChildren(QPushButton)}
        self.assertIn("str. 1 (1)", buttons)
        self.assertIn("str. 5 (2)", buttons)
        buttons["str. 5 (2)"].click()
        self.assertEqual(shown, [4])

    def test_no_findings_is_said_aloud(self):
        content = self.panel([])
        texts = " | ".join(label.text() for label in content.findChildren(QLabel))
        self.assertIn("Brak uwag w tekście", texts)

    def test_fast_mode_says_where_the_rest_comes_from(self):
        content = self.panel([])
        texts = " | ".join(label.text() for label in content.findChildren(QLabel))
        self.assertIn("Dostępne w trybie dokładnym", texts)

    def test_document_without_analysis_has_no_findings_section(self):
        from ui.report_panel import build_report_panel
        content, _ = build_report_panel(None, lambda: None, None)
        self.assertNotIn("Uwagi w tekście", " | ".join(label.text() for label in content.findChildren(QLabel)))


class SettingsDialogTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        from analysis.modules.llm import config
        self.config = config
        self.saved = {"device": "cuda", "n_gpu_layers": 12, "model_dir": "/m", "language": "en"}
        for patcher in (mock.patch.object(config, "load_config", lambda: dict(self.saved)),
                        mock.patch.object(config, "save_config", lambda data: self.saved.update(data)),
                        mock.patch.object(config, "reload_config", lambda: None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        from ui.settings import SettingsDialog
        self.dialog = SettingsDialog()

    def test_plain_names_on_screen_and_config_values_saved(self):
        self.assertEqual(self.dialog.combo_device.currentText(), "Karta graficzna (CUDA)")
        self.assertEqual(self.dialog.combo_language.currentText(), "English")
        with mock.patch("ui.settings.MessageBox"):
            self.dialog.save_config()
        self.assertEqual((self.saved["device"], self.saved["language"]), ("cuda", "en"))

    def test_layers_field_is_off_for_the_processor(self):
        self.dialog.combo_device.setCurrentIndex(self.dialog.combo_device.findData("cpu"))
        self.assertFalse(self.dialog.input_gpu_layers.isEnabled())

    def test_wrong_number_of_layers_is_not_saved(self):
        self.dialog.input_gpu_layers.setText("dużo")
        with mock.patch("ui.settings.MessageBox") as box:
            self.dialog.save_config()
        box.warning.assert_called_once()
        self.assertEqual(self.saved["n_gpu_layers"], 12)

    def test_dialog_is_never_higher_than_the_screen(self):
        self.assertLessEqual(self.dialog.height(), self.dialog.screen().availableGeometry().height())


if __name__ == "__main__":
    unittest.main()
