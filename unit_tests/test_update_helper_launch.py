'''
The update helper (PowerShell on Windows) must be started so that it can actually run.
With DETACHED_PROCESS Windows PowerShell 5.1 dies during start-up and the update never happens.
'''
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common import updater  # noqa: E402


@unittest.skipUnless(sys.platform == "win32", "Windows creation flags")
class HelperLaunchTest(unittest.TestCase):
    def launch_flags(self):
        staged = updater.StagedUpdate(version="9.9.9", new_dir="new")
        with mock.patch.object(updater, "can_self_update", return_value=(True, "")), \
                mock.patch.object(updater, "validate_package"), \
                mock.patch.object(updater, "_write_script", return_value=["powershell"]), \
                mock.patch.object(updater.subprocess, "Popen") as popen:
            popen.return_value.pid = 4242
            updater.apply_update_and_restart(staged)
        return popen.call_args.kwargs["creationflags"]

    def test_the_helper_has_a_console(self):
        self.assertFalse(self.launch_flags() & subprocess.DETACHED_PROCESS)

    def test_the_helper_shows_no_window(self):
        self.assertTrue(self.launch_flags() & subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
