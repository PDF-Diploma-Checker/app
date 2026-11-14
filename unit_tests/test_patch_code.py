import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import patch_code


class PatchBuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "src" / "analysis").mkdir(parents=True)
        (self.root / "src" / "ui").mkdir()
        (self.root / "src" / "analysis" / "new_module.py").write_text("added = 1\n")
        (self.root / "src" / "ui" / "panel.py").write_text("new = 1\n")
        self.internal = self.root / "DiplomaChecker" / "_internal"
        for package in patch_code.OWN_PACKAGES:
            (self.internal / package).mkdir(parents=True)
            (self.internal / package / "__init__.py").write_text("")
        (self.internal / "ui" / "panel.py").write_text("old = 1\n")
        (self.internal / "ui" / "removed.py").write_text("old = 1\n")
        (self.internal / "ui" / "untouched.py").write_text("same = 1\n")
        patcher = mock.patch.object(patch_code, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_the_changed_files_change(self):
        changes = [("M", "src/ui/panel.py"), ("D", "src/ui/removed.py"), ("A", "src/analysis/new_module.py"),
                   ("M", "pyproject.toml")]
        patch_code.patch_build(self.root / "DiplomaChecker", changes, "0.4.2")
        self.assertEqual((self.internal / "ui" / "panel.py").read_text(), "new = 1\n")
        self.assertFalse((self.internal / "ui" / "removed.py").exists())
        self.assertEqual((self.internal / "ui" / "untouched.py").read_text(), "same = 1\n")
        self.assertTrue((self.internal / "analysis" / "new_module.py").exists())
        self.assertEqual((self.internal / "VERSION.txt").read_text(), "0.4.2\n")

    def test_build_without_plain_files_is_refused(self):
        (self.internal / "analysis" / "__init__.py").unlink()
        with self.assertRaises(SystemExit):
            patch_code.patch_build(self.root / "DiplomaChecker", [], "0.4.2")


class NeedsFullBuildTest(unittest.TestCase):
    def reasons(self, changes, old="", new="", diff=""):
        def git(*args):
            if args[0] == "ls-tree":
                return "src/old.py\n"
            return diff if args[0] == "diff" else old

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(patch_code, "git", git), \
                mock.patch.object(patch_code, "ROOT", Path(tmp)):
            for status, path in changes:
                if status != "D":
                    (Path(tmp) / path).parent.mkdir(parents=True, exist_ok=True)
                    (Path(tmp) / path).write_text(new)
            return patch_code.needs_full_build("v0.4.1", changes)

    def test_code_alone_can_be_patched(self):
        self.assertEqual(self.reasons([("M", "src/ui/a.py"), ("M", "unit_tests/t.py")], "import os\n", "import os\n"), [])

    def test_standalone_dictionary_service_does_not_require_client_rebuild(self):
        changes = [("A", "dictionary_service/server.py"), ("M", "dictionary_service/admin.html")]
        self.assertEqual(self.reasons(changes, new="import unbundled_backend_dependency\n"), [])

    def test_import_of_our_code_can_be_patched(self):
        self.assertEqual(self.reasons([("A", "src/ui/a.py")], new="from analysis.modules import x\n"), [])

    def test_new_outside_import_needs_a_build(self):
        reasons = self.reasons([("M", "src/analysis/a.py")], "import os\n", "import os\ndef f():\n    import lxml.etree\n")
        self.assertIn("lxml.etree", reasons[0])

    def test_module_our_code_already_used_can_be_patched(self):
        self.assertEqual(self.reasons([("M", "src/ui/a.py")], "import collections\n", "import collections\n"), [])

    def test_module_built_into_python_can_be_patched(self):
        self.assertEqual(self.reasons([("A", "src/ui/a.py")], new="import itertools\n"), [])

    def test_changed_text_file_can_be_patched(self):
        self.assertEqual(self.reasons([("M", "src/analysis/modules/linguistics/word_whitelist.txt")]), [])

    def test_new_or_removed_text_file_needs_a_build(self):
        changes = [("A", "src/analysis/new.txt"), ("D", "src/analysis/old.txt")]
        self.assertEqual(len(self.reasons(changes)), 2)

    def test_build_and_data_files_need_a_build(self):
        changes = [("M", "DiplomaChecker.spec"), ("M", patch_code.LAUNCHER), ("A", "src/ui/assets/logo.png")]
        self.assertEqual(len(self.reasons(changes)), 3)

    def test_version_number_can_be_patched(self):
        diff = '--- a/pyproject.toml\n+++ b/pyproject.toml\n@@ -1 +1 @@\n-version = "0.4.1"\n+version = "0.4.2"\n'
        self.assertEqual(self.reasons([("M", "pyproject.toml")], diff=diff), [])

    def test_other_library_needs_a_build(self):
        diff = '--- a/uv.lock\n+++ b/uv.lock\n@@ -1 +1 @@\n-version = "1"\n+version = "2"\n+url = "x"\n'
        self.assertEqual(len(self.reasons([("M", "uv.lock")], diff=diff)), 1)


if __name__ == "__main__":
    unittest.main()
