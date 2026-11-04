"""The license agreement ships with the app and has to be accepted once per version."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from analysis.modules.llm import config  # noqa: E402
from common import eula  # noqa: E402


class EulaTest(unittest.TestCase):
    def setUp(self):
        self.saved = {"device": "cpu"}
        patches = (mock.patch.object(config, "load_config", lambda: dict(self.saved)),
                   mock.patch.object(config, "save_config", lambda cfg: setattr(self, "saved", cfg)))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_text_in_both_languages(self):
        text = eula.read_eula()
        self.assertIn("UMOWA LICENCYJNA", text)
        self.assertIn("END USER LICENSE AGREEMENT", text)

    def test_not_accepted_on_a_clean_start(self):
        self.assertFalse(eula.is_accepted())

    def test_accepting_keeps_the_other_settings(self):
        eula.accept()
        self.assertTrue(eula.is_accepted())
        self.assertEqual(self.saved["device"], "cpu")

    def test_new_version_has_to_be_accepted_again(self):
        eula.accept()
        with mock.patch.object(eula, "EULA_VERSION", eula.EULA_VERSION + 1):
            self.assertFalse(eula.is_accepted())


if __name__ == "__main__":
    unittest.main()
