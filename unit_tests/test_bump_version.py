'''
Tests of the automatic version number.

Run (from the repository root):
    .venv/bin/python -m unittest unit_tests.test_bump_version -v
'''
import subprocess
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

    def test_the_version_is_one_above_the_newest_release(self):
        self.assertEqual(bump_version.target_version("0.5.1", "0.5.1"), "0.5.2")

    def test_merges_before_the_release_share_one_version(self):
        self.assertEqual(bump_version.target_version("0.5.2", "0.5.1"), "0.5.2")

    def test_numbers_used_up_without_a_release_come_back(self):
        self.assertEqual(bump_version.target_version("0.5.4", "0.5.1"), "0.5.2")

    def test_a_version_for_a_full_build_waits_for_its_release(self):
        self.assertEqual(bump_version.target_version("0.6.0", "0.5.1"), "0.6.0")
        self.assertEqual(bump_version.target_version("1.0.0", "0.9.3"), "1.0.0")

    def test_nothing_is_written_when_the_version_is_right(self):
        root = self._project("0.5.2")
        self.assertIsNone(bump_version.bump("v0.5.1", root))
        self.assertIn('version = "0.5.2"', (root / "pyproject.toml").read_text(encoding="utf-8"))

    def test_every_place_gets_the_new_version(self):
        root = self._project()
        self.assertEqual(bump_version.bump("v0.4.9", root), "0.4.10")
        self.assertIn('APP_VERSION = "0.4.10"', (root / "src/common/version.py").read_text(encoding="utf-8"))
        self.assertIn('version = "0.4.10"', (root / "pyproject.toml").read_text(encoding="utf-8"))
        lock = (root / "uv.lock").read_text(encoding="utf-8")
        self.assertIn('name = "pdf-diploma-checker"\nversion = "0.4.10"', lock)
        self.assertIn('name = "packaging"\nversion = "26.3"', lock)

    def test_files_that_disagree_are_not_touched(self):
        root = self._project(lock_version="0.4.8")
        with self.assertRaises(SystemExit):
            bump_version.bump("v0.4.8", root)
        self.assertIn('version = "0.4.9"', (root / "pyproject.toml").read_text(encoding="utf-8"))

    def _commit(self, root, version):
        (root / "src/common/version.py").write_text(f'APP_VERSION = "{version}"\n', encoding="utf-8")
        env = ["-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", *env, "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", *env, "commit", "-qm", version], cwd=root, check=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()

    def test_a_version_set_in_the_merge_stays(self):
        root = self._project()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        first = self._commit(root, "0.4.9")
        (root / "x").write_text("code", encoding="utf-8")
        same = self._commit(root, "0.4.9")
        by_hand = self._commit(root, "0.5.0")
        self.assertFalse(bump_version.set_by_hand(first, same, root))
        self.assertTrue(bump_version.set_by_hand(same, by_hand, root))

    def test_an_unknown_commit_means_a_normal_bump(self):
        root = self._project()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        after = self._commit(root, "0.4.9")
        self.assertFalse(bump_version.set_by_hand("0" * 40, after, root))

    def test_the_real_project_can_be_read(self):
        for name, pattern in bump_version.PLACES.items():
            self.assertRegex((REPO_ROOT / name).read_text(encoding="utf-8"), "(?m)" + pattern)


if __name__ == "__main__":
    unittest.main()
