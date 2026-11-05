import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import patch_ui


class PatchBuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src_ui = self.root / "src_ui"
        self.src_ui.mkdir()
        (self.src_ui / "panel.py").write_text("new = 1\n")
        self.version = self.root / "version.py"
        self.version.write_text('APP_VERSION = "0.4.2"\n')
        self.app = self.root / "DiplomaChecker"
        (self.app / "_internal" / "ui" / "assets").mkdir(parents=True)
        (self.app / "_internal" / "common").mkdir()
        (self.app / "_internal" / "ui" / "panel.py").write_text("old = 1\n")
        (self.app / "_internal" / "ui" / "removed.py").write_text("old = 1\n")
        (self.app / "_internal" / "ui" / "assets" / "logo.png").write_text("image")
        (self.app / "_internal" / "common" / "version.py").write_text('APP_VERSION = "0.4.1"\n')
        for name, value in (("SRC_UI", self.src_ui), ("VERSION_FILE", self.version)):
            patcher = mock.patch.object(patch_ui, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_code_and_version_change_and_the_rest_stays(self):
        patch_ui.patch_build(self.app, patch_ui.app_version())
        internal = self.app / "_internal"
        self.assertEqual((internal / "ui" / "panel.py").read_text(), "new = 1\n")
        self.assertFalse((internal / "ui" / "removed.py").exists())
        self.assertTrue((internal / "ui" / "assets" / "logo.png").exists())
        self.assertIn("0.4.2", (internal / "common" / "version.py").read_text())
        self.assertEqual((internal / "VERSION.txt").read_text(), "0.4.2")

    def test_build_without_plain_files_is_refused(self):
        (self.app / "_internal" / "common" / "version.py").unlink()
        with self.assertRaises(SystemExit):
            patch_ui.patch_build(self.app, "0.4.2")


class ChangedOutsideUiTest(unittest.TestCase):
    def test_only_changes_a_patch_cannot_carry_are_listed(self):
        changed = "src/ui/panel.py\nsrc/common/version.py\npyproject.toml\nsrc/analysis/x.py\nDiplomaChecker.spec\n"
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=changed)):
            self.assertEqual(patch_ui.changed_outside_ui("v0.4.1"), ["src/analysis/x.py", "DiplomaChecker.spec"])


if __name__ == "__main__":
    unittest.main()
