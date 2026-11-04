"""The license agreement ships with the app and states what the app really does with data."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from common.path import resource_path  # noqa: E402


class EulaTest(unittest.TestCase):
    def test_text_in_both_languages(self):
        with open(resource_path("ui/assets/EULA.txt"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("UMOWA LICENCYJNA", text)
        self.assertIn("END USER LICENSE AGREEMENT", text)
        self.assertIn("AGPL-3.0", text)


if __name__ == "__main__":
    unittest.main()
