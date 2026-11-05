import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.gpu_check import is_weak_gpu


class WeakGpuTest(unittest.TestCase):
    def test_small_card_is_weak(self):
        self.assertTrue(is_weak_gpu(4.0))
        self.assertTrue(is_weak_gpu(7.9))

    def test_enough_memory(self):
        self.assertFalse(is_weak_gpu(8.0))
        self.assertFalse(is_weak_gpu(16.0))

    def test_no_card_is_not_a_weak_card(self):
        self.assertFalse(is_weak_gpu(0.0))


if __name__ == "__main__":
    unittest.main()
