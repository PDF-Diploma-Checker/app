'''
Tests of the models folder saved in the settings by another copy of the app.

Run (from the repository root):
    .venv/bin/python -m unittest unit_tests.test_stale_model_dir -v
'''
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.llm import config  # noqa: E402


class StaleModelDirTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.settings = self.root / "app_config.json"
        current = self.root / "new-name" / "DiplomaChecker" / "models"
        for name, value in (("APP_CONFIG_PATH", self.settings), ("DEFAULT_MODEL_DIR", current), ("PORTABLE", True)):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _loaded(self, model_dir):
        self.settings.write_text(json.dumps({"model_dir": str(model_dir)}), encoding="utf-8")
        return config.load_config()["model_dir"]

    def test_missing_folder_of_another_copy_is_not_used(self):
        self.assertEqual(self._loaded(self.root / "old-name" / "DiplomaChecker" / "models"), "")
        self.assertFalse((self.root / "old-name").exists())

    def test_app_folder_itself_is_not_used(self):
        self.assertEqual(self._loaded(self.root / "old-name" / "DiplomaChecker"), "")

    def test_downloaded_models_of_another_copy_stay_in_use(self):
        folder = self.root / "old-name" / "DiplomaChecker" / "models"
        (folder / "gemma3_12b").mkdir(parents=True)
        (folder / "gemma3_12b" / config.GEMMA_FILE).write_bytes(b"x")
        self.assertEqual(self._loaded(folder), str(folder))

    def test_folder_chosen_by_the_user_stays(self):
        folder = self.root / "my-models"
        self.assertEqual(self._loaded(folder), str(folder))

    def test_run_from_source_keeps_the_setting(self):
        folder = self.root / "old-name" / "DiplomaChecker" / "models"
        with patch.object(config, "PORTABLE", False):
            self.assertEqual(self._loaded(folder), str(folder))


if __name__ == "__main__":
    unittest.main()
