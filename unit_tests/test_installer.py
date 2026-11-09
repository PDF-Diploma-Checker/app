'''
What the installer decides and how it replaces the files. No network and no window.
'''
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools" / "installer"),
                str(Path(__file__).resolve().parents[1] / "src")]

import install_core as core  # noqa: E402
from common.update_errors import UpdateError  # noqa: E402


class VariantTest(unittest.TestCase):
    def test_an_nvidia_card_means_gpu(self):
        self.assertEqual(core.recommended_variant([{"name": "RTX", "vram_gb": 16.0}]), "gpu")
        self.assertEqual(core.recommended_variant([{"name": "GTX", "vram_gb": 4.0}]), "gpu")

    def test_no_card_means_cpu(self):
        self.assertEqual(core.recommended_variant([]), "cpu")

    def test_sizes_add_up_the_parts_of_an_archive(self):
        assets = [
            {"name": "DiplomaChecker-linux-gpu.manifest.json", "size": 5},
            {"name": "DiplomaChecker-linux-gpu.tar.gz.001", "size": 100},
            {"name": "DiplomaChecker-linux-gpu.tar.gz.002", "size": 20},
            {"name": "DiplomaChecker-linux-gpu.tar.gz.sha256", "size": 9},
            {"name": "DiplomaChecker-linux-base.manifest.json", "size": 5},
            {"name": "DiplomaChecker-linux-base.tar.gz", "size": 7},
            {"name": "DiplomaChecker-linux-cpu.tar.gz", "size": 8},          # no manifest: cannot be installed
            {"name": "DiplomaChecker-windows-gpu.manifest.json", "size": 5},
        ]
        self.assertEqual(core.variant_sizes({"assets": assets}, "linux"), {"gpu": 120, "base": 7})


class LanguageTest(unittest.TestCase):
    def test_polish_on_a_polish_system(self):
        for name, expected in (("pl_PL", "pl"), ("Polish_Poland", "pl"), ("en_US", "en"), (None, "en")):
            with mock.patch.object(core.locale, "getlocale", return_value=(name, "UTF-8")):
                self.assertEqual(core.language(), expected, name)


class RetryTest(unittest.TestCase):
    def run_install(self, errors):
        with mock.patch.object(core, "_fetch", side_effect=errors) as fetch, mock.patch.object(core, "_swap") as swap, \
                mock.patch.object(core, "_wait"):
            try:
                core.install({}, "cpu", "linux", "/tmp/x", lambda *a: None, lambda: False)
            finally:
                self.calls, self.swapped = fetch.call_count, swap.called

    def test_a_server_error_is_tried_again(self):
        self.run_install([UpdateError("http"), UpdateError("no_manifest"), None])
        self.assertEqual(self.calls, 3)
        self.assertTrue(self.swapped)

    def test_it_gives_up_after_the_last_attempt(self):
        with self.assertRaises(UpdateError):
            self.run_install([UpdateError("http")] * core.ATTEMPTS)
        self.assertEqual(self.calls, core.ATTEMPTS)
        self.assertFalse(self.swapped)

    def test_no_room_is_not_tried_again(self):
        with self.assertRaises(UpdateError):
            self.run_install([UpdateError("space", free=1, needed=2)])
        self.assertEqual(self.calls, 1)


class FolderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def test_new_or_empty_folder_is_used(self):
        self.assertEqual(core.resolve_target(self.root / "new"), self.root / "new")
        (self.root / "empty").mkdir()
        self.assertEqual(core.resolve_target(self.root / "empty"), self.root / "empty")

    def test_the_folder_of_the_app_is_used(self):
        (self.root / "app" / "_internal").mkdir(parents=True)
        self.assertEqual(core.resolve_target(self.root / "app"), self.root / "app")

    def test_a_folder_with_other_files_gets_a_subfolder(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "thesis.pdf").write_text("x")
        self.assertEqual(core.resolve_target(self.root / "docs"), self.root / "docs" / core.APP_DIR_NAME)

    def make_install(self):
        target, staging = self.root / "app", self.root / "app.installing"
        (target / "_internal").mkdir(parents=True)
        (target / "_internal" / "old.py").write_text("old")
        (target / "models").mkdir()
        (target / "models" / "gemma.gguf").write_text("model")
        (staging / "_internal").mkdir(parents=True)
        (staging / "_internal" / "new.py").write_text("new")
        (staging / "DiplomaChecker").write_text("exe")
        return target, staging

    def test_only_the_entries_of_the_app_are_replaced(self):
        target, staging = self.make_install()
        core._swap(staging, target)
        self.assertEqual((target / "_internal" / "new.py").read_text(), "new")
        self.assertFalse((target / "_internal" / "old.py").exists())
        self.assertEqual((target / "models" / "gemma.gguf").read_text(), "model")
        self.assertFalse(staging.exists())
        self.assertFalse((self.root / "app.old").exists())

    def test_a_locked_app_stays_as_it_was(self):
        target, staging = self.make_install()
        real = core.os.replace

        def locked(source, destination):
            if Path(source).name == "DiplomaChecker":
                raise PermissionError("in use")
            real(source, destination)

        with mock.patch.object(core.os, "replace", locked), self.assertRaises(UpdateError) as caught:
            core._swap(staging, target)
        self.assertEqual(caught.exception.code, "locked")
        self.assertEqual((target / "_internal" / "old.py").read_text(), "old")
        self.assertEqual((staging / "_internal" / "new.py").read_text(), "new")


class ShortcutTest(unittest.TestCase):
    def test_the_menu_entry_quotes_the_path(self):
        with mock.patch.object(sys, "platform", "linux"):
            entry = core._desktop_entry(Path("/home/a b/DiplomaChecker"))
        self.assertIn('Exec="/home/a b/DiplomaChecker/DiplomaChecker"', entry)
        self.assertIn("/_internal/ui/assets/logo.png", entry)

    def test_the_app_does_not_inherit_the_libraries_of_the_installer(self):
        with mock.patch.dict(core.os.environ, {"LD_LIBRARY_PATH": "/tmp/_MEI", "LD_LIBRARY_PATH_ORIG": "/usr/lib",
                                               "TCL_LIBRARY": "/tmp/_MEI/tcl"}):
            env = core.clean_environment()
        self.assertEqual(env["LD_LIBRARY_PATH"], "/usr/lib")
        self.assertNotIn("TCL_LIBRARY", env)
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")


if __name__ == "__main__":
    unittest.main()
