"""Tests for Polish verbless comparison filter (ROWNIE_JAK) and robotics/ML whitelist terms."""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.modules.linguistics.language_error_extractor import (
    is_verbless_comparison,
    typo_check,
)


def _verbless(sentence, token=" jak"):
    offset = sentence.index(token)
    return is_verbless_comparison(sentence, offset, len(token))


class VerblessComparisonTest(unittest.TestCase):
    def test_tak_samo_jak_without_verb_is_dropped(self):
        self.assertTrue(_verbless(
            "Jedną zmianę da się sprawdzić od razu w pętli uczenia: obecnie wyczerpanie limitu kroków "
            "kończy epizod tak samo jak upadek, natomiast Rudin i in. [28] doliczają wartość stanu."
        ))
        self.assertTrue(_verbless("Działa tak samo jak poprzedni model."))
        self.assertTrue(_verbless("Działa tak samo jak w stanie spoczynku."))
        self.assertTrue(_verbless("Jest równie szybki jak poprzedni."))
        self.assertTrue(_verbless("Następowało po tym 5 epok tak samo jak w [28]."))

    def test_tak_samo_jak_with_verb_is_kept(self):
        self.assertFalse(_verbless("Zrobił to tak samo jak mu kazano."))
        self.assertFalse(_verbless("Działa tak samo jak opisano wcześniej."))
        self.assertFalse(_verbless("Jest równie szybki jak opisano w rozdziale 2."))
        self.assertFalse(_verbless("Wyczerpanie limitu kończy epizod tak samo jak dzieje się przy upadku."))


class RoboticsTermsWhitelistTest(unittest.TestCase):
    def test_proprioceptive_and_odometry_inflections_are_known(self):
        for word in (
            "proprioceptywny", "proprioceptywna", "proprioceptywne",
            "proprioceptywnych", "proprioceptywnym", "proprioceptywnie",
            "odometria", "odometrii", "odometrię", "odometrią",
            "odometryczny", "odometrycznych",
            "samonadzorowany", "samonadzorowanego", "samonadzorowane",
        ):
            with self.subTest(word=word):
                self.assertTrue(typo_check(word))


if __name__ == "__main__":
    unittest.main()
