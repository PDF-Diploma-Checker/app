'''
Tests of the automatic version number.

Run (from the repository root):
    .venv/bin/python -m unittest unit_tests.test_bump_version -v
'''
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import bump_version  # noqa: E402


class BumpVersionTest(unittest.TestCase):
    def _project(self, version="0.4.9", lock_version=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "src/common").mkdir(parents=True)
        (root / "src/common/version.py").write_text(f'"""Doc."""\n\nAPP_VERSION = "{version}"\n', encoding="utf-8")
        (root / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8")
        (root / "uv.lock").write_text(
            '[[package]]\nname = "packaging"\nversion = "26.3"\n\n'
            f'[[package]]\nname = "pdf-diploma-checker"\nversion = "{lock_version or version}"\n', encoding="utf-8")
        return root

    def test_only_the_last_number_changes(self):
        self.assertEqual(bump_version.next_version("0.4.9"), "0.4.10")

    def test_every_place_gets_the_new_version(self):
        root = self._project()
        self.assertEqual(bump_version.bump(root), "0.4.10")
        self.assertIn('APP_VERSION = "0.4.10"', (root / "src/common/version.py").read_text(encoding="utf-8"))
        self.assertIn('version = "0.4.10"', (root / "pyproject.toml").read_text(encoding="utf-8"))
        lock = (root / "uv.lock").read_text(encoding="utf-8")
        self.assertIn('name = "pdf-diploma-checker"\nversion = "0.4.10"', lock)
        self.assertIn('name = "packaging"\nversion = "26.3"', lock)

    def test_files_that_disagree_are_not_touched(self):
        root = self._project(lock_version="0.4.8")
        with self.assertRaises(SystemExit):
            bump_version.bump(root)
        self.assertIn('version = "0.4.9"', (root / "pyproject.toml").read_text(encoding="utf-8"))

    def test_the_real_project_can_be_read(self):
        for name, pattern in bump_version.PLACES.items():
            self.assertRegex((REPO_ROOT / name).read_text(encoding="utf-8"), "(?m)" + pattern)


if __name__ == "__main__":
    unittest.main()
