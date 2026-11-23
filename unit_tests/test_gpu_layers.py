import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.gpu_check import recommend_gpu_layers


class RecommendGpuLayersTest(unittest.TestCase):
    def test_sixteen_gb_card_gets_every_layer(self):
        # nvidia-smi reports 16311 MiB for an RTX 5060 Ti, 16384 MiB for others: both are "16 GB"
        self.assertEqual(recommend_gpu_layers(16311 / 1024), -1)
        self.assertEqual(recommend_gpu_layers(16384 / 1024), -1)

    def test_smaller_cards_keep_part_of_the_model_on_the_processor(self):
        self.assertEqual(recommend_gpu_layers(12288 / 1024), 40)
        self.assertEqual(recommend_gpu_layers(10), 40)
        self.assertEqual(recommend_gpu_layers(8), 25)
        self.assertEqual(recommend_gpu_layers(6), 16)
        self.assertEqual(recommend_gpu_layers(4), 8)
        self.assertEqual(recommend_gpu_layers(2), 0)


if __name__ == "__main__":
    unittest.main()
