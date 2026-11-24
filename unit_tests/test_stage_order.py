'''
The stages the progress bar announces (app/llm_task.py STAGES) must be the stages the time tracker expects
(common/eta.py): otherwise the stage list shows "figures" during the SOTA stage and "SOTA" during the figures, and the
time of the figures lands in the SOTA stage of the run history.
'''
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import llm_task  # noqa: E402
from common import eta  # noqa: E402

MACHINE = eta.MachineFacts(threads=16, ram_gb=32, gpu=True, gpu_layers=-1, gpu_name="GPU", vram_gb=16)


DOC = eta.DocFacts(pages=60, chars=100000, images=20, sections=40, figures=15)


class StageOrderTest(unittest.TestCase):
    def test_tracker_values_are_the_values_the_analysis_announces(self):
        self.assertEqual(dict(eta.STAGE_VALUES), llm_task.STAGES)

    def test_the_estimate_lists_the_stages_in_the_order_they_run(self):
        keys = [key for key, _ in eta.raw_estimate(DOC, MACHINE, True, True)]
        self.assertEqual(keys, ["prep", "purpose", "goal", "summaries", "sota", "images", "language_review"])

    def test_figures_time_is_not_counted_as_sota(self):
        tracker = eta.EtaTracker(eta.estimate(DOC, MACHINE, True, True, history=[]))
        clock = {"t": 0.0}
        # (progress value announced, seconds that passed before it): SOTA runs from 80 to 90, the figures from 90 to 95
        for value, seconds in ((55, 30), (62, 20), (70, 20), (80, 400), (90, 500), (95, 100)):
            clock["t"] += seconds
            tracker.on_progress(value, now=clock["t"])
        spent = tracker.stage_seconds(now=clock["t"] + 50)
        self.assertEqual((round(spent["sota"]), round(spent["images"])), (500, 100))


if __name__ == "__main__":
    unittest.main()
