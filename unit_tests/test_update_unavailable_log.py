'''
The log has to say why an update inside the app was not offered or failed.
'''
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common import updater  # noqa: E402
try:
    from ui.update_banner import UpdateBanner  # noqa: E402
except ImportError as error:    # e.g. a CI runner without the system libraries Qt needs (libEGL)
    raise unittest.SkipTest(f"Qt is not available: {error}")

ASSET = {"name": updater.APP_DIR_NAME + "-windows-cpu.zip"}


def can_update(result, assets):
    banner = SimpleNamespace(_info={"assets": assets})
    with mock.patch.object(updater, "can_self_update", return_value=result):
        return UpdateBanner._can_update_in_place(banner)


class UnavailableUpdateLogTest(unittest.TestCase):
    def test_the_reason_goes_to_the_log(self):
        with self.assertLogs("ui.update_banner", "INFO") as logs:
            self.assertFalse(can_update((False, "readonly"), [ASSET]))
        self.assertIn("readonly", logs.output[0])

    def test_a_release_without_files_is_named(self):
        with self.assertLogs("ui.update_banner", "INFO") as logs:
            self.assertFalse(can_update((True, ""), []))
        self.assertIn("no files", logs.output[0])

    def test_nothing_is_logged_when_the_update_is_possible(self):
        with self.assertNoLogs("ui.update_banner", "INFO"):
            self.assertTrue(can_update((True, ""), [ASSET]))


if __name__ == "__main__":
    unittest.main()
