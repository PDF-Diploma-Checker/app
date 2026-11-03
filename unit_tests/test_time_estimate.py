'''
Tests of the time estimate. No model or GPU is needed.

Run (from the repository root):
    .venv/bin/python -m unittest unit_tests.test_time_estimate -v
'''
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import fitz  # noqa: E402

from common import eta  # noqa: E402

MACHINE = eta.MachineFacts(threads=16, ram_gb=32, gpu=True, gpu_layers=25, gpu_name="GPU", vram_gb=16)


def _stages(**facts):
    doc = eta.DocFacts(**{"pages": 20, "chars": 30000, "images": 5, "sections": 10, "figures": 3, **facts})
    return dict(eta.raw_estimate(doc, MACHINE, True, True))


class DocFactsTest(unittest.TestCase):
    def test_counts_sections_once_and_only_captioned_figures(self):
        pdf = fitz.open()
        page = pdf.new_page()
        lines = ["2.1 Pierwsza sekcja . . . . 3", "2.2. Druga sekcja", "2.1 Pierwsza sekcja", "Rysunek 1. Podpis",
                 "Wykres 1. Podpis", "Rys. 2.1. Podpis", "Na rysunku 1 widać wynik.", "Rok 2.5 procent"]
        for number, line in enumerate(lines):
            page.insert_text((50, 60 + 20 * number), line)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "t.pdf")
            pdf.save(path)
            facts = eta.doc_facts(path)
        self.assertEqual((facts.sections, facts.figures), (2, 3))


class StagesTest(unittest.TestCase):
    def test_no_sections_no_summaries(self):
        self.assertNotIn("summaries", _stages(sections=0))

    def test_no_captioned_figures_no_image_stage(self):
        self.assertNotIn("images", _stages(figures=0))

    def test_more_work_takes_longer(self):
        self.assertGreater(_stages(sections=30)["summaries"], _stages(sections=10)["summaries"])
        self.assertGreater(_stages(figures=9)["images"], _stages(figures=3)["images"])
        self.assertGreater(_stages(chars=90000)["sota"], _stages(chars=30000)["sota"])

    def test_tracker_ignores_a_stage_that_was_not_predicted(self):
        doc = eta.DocFacts(pages=5, chars=5000, images=0)
        estimate = eta.estimate(doc, MACHINE, True, True, history=[])
        tracker = eta.EtaTracker(estimate)
        tracker.on_progress(70)     # "summaries" is not in the estimate of a thesis without sections
        self.assertIn(tracker.stage, [key for key, _ in estimate.stages])


if __name__ == "__main__":
    unittest.main()
