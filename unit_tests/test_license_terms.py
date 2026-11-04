"""The license and terms ship with the app and have to be accepted once per version."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from analysis.modules.llm import config  # noqa: E402
from common import license_terms  # noqa: E402


class LicenseTermsTest(unittest.TestCase):
    def setUp(self):
        self.saved = {"device": "cpu"}
        patches = (mock.patch.object(config, "load_config", lambda: dict(self.saved)),
                   mock.patch.object(config, "save_config", lambda cfg: setattr(self, "saved", cfg)))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_text_in_both_languages(self):
        text = license_terms.read_terms()
        self.assertIn("LICENCJA I WARUNKI", text)
        self.assertIn("LICENSE AND TERMS", text)
        self.assertIn("AGPL-3.0", text)
        for author in ("Natalia Płocha", "Maja Mogielnicka", "Aleksandra Słomska", "Dorian Neumann", "Zofia Narloch"):
            self.assertIn(author, text)

    def test_license_file_ships_with_the_build(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", (root / "LICENSE").read_text(encoding="utf-8"))
        self.assertIn('("LICENSE", ".")', (root / "DiplomaChecker.spec").read_text(encoding="utf-8"))

    def test_not_accepted_on_a_clean_start(self):
        self.assertFalse(license_terms.is_accepted())

    def test_accepting_keeps_the_other_settings(self):
        license_terms.accept()
        self.assertTrue(license_terms.is_accepted())
        self.assertEqual(self.saved["device"], "cpu")

    def test_new_version_has_to_be_accepted_again(self):
        license_terms.accept()
        with mock.patch.object(license_terms, "TERMS_VERSION", license_terms.TERMS_VERSION + 1):
            self.assertFalse(license_terms.is_accepted())


if __name__ == "__main__":
    unittest.main()
