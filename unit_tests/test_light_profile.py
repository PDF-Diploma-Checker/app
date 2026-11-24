"""The light profile: the whole analysis on the small Gemma 3 4B, for those who do not want to download the 12B."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.llm import config  # noqa: E402
from app import llm_process, llm_task  # noqa: E402
from common import eta, gpu_check  # noqa: E402

FULL = eta.MachineFacts(threads=16, ram_gb=32, gpu=True, gpu_layers=-1, gpu_name="GPU", vram_gb=16)
LIGHT = eta.MachineFacts(threads=16, ram_gb=32, gpu=True, gpu_layers=-1, gpu_name="GPU", vram_gb=16, profile="light")
DOC = eta.DocFacts(pages=60, chars=100000, images=20, sections=40, figures=15)


class ConfigTest(unittest.TestCase):
    def tearDown(self):
        config.reload_config()

    def test_each_profile_has_its_own_model_file(self):
        folder = Path("/models")
        self.assertEqual(config.text_model_path(folder, "full"), folder / "gemma3_12b" / config.GEMMA_FILE)
        self.assertEqual(config.text_model_path(folder, "light"), folder / "gemma3_4b" / config.LIGHT_FILE)

    def test_presence_is_checked_per_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(config._models_present(folder))
            path = config.text_model_path(folder, "light")
            path.parent.mkdir(parents=True)
            path.write_bytes(b"x")
            self.assertTrue(config._models_present(folder, "light"))
            self.assertFalse(config._models_present(folder, "full"))
            self.assertTrue(config._models_present(folder))                 # any profile

    def test_the_profile_in_the_settings_chooses_the_model(self):
        with tempfile.TemporaryDirectory() as folder:
            config._apply(dict(config.default_config(), model_profile="light", model_dir=folder))
            self.assertEqual(config.MODEL_PROFILE, "light")
            self.assertEqual(config.MODEL_PATH, config.text_model_path(folder, "light"))
            config._apply(dict(config.default_config(), model_profile="nonsense", model_dir=folder))
            self.assertEqual(config.MODEL_PROFILE, "full")                  # an unknown profile is the default

    def test_language_review_only_with_the_full_model(self):
        self.assertTrue(config.language_review_enabled("full"))
        self.assertFalse(config.language_review_enabled("light"))

    def test_the_purpose_is_rated_only_by_the_full_model(self):
        self.assertTrue(config.goal_check_enabled("full"))
        self.assertFalse(config.goal_check_enabled("light"))


class AdviceTest(unittest.TestCase):
    def test_the_small_model_fits_whole_on_a_small_card(self):
        self.assertEqual(gpu_check.recommend_gpu_layers(6, "light"), -1)
        self.assertEqual(gpu_check.recommend_gpu_layers(4, "light"), 20)
        self.assertEqual(gpu_check.recommend_gpu_layers(1, "light"), 0)
        self.assertEqual(gpu_check.recommend_gpu_layers(6, "full"), 16)     # the 12B: unchanged

    def test_smaller_download_and_weak_card_limit(self):
        self.assertLess(gpu_check.models_size_gb("light"), gpu_check.models_size_gb("full"))
        self.assertFalse(gpu_check.is_weak_gpu(6, "light"))
        self.assertTrue(gpu_check.is_weak_gpu(6, "full"))

    def test_the_computer_gets_the_model_it_can_run(self):
        small = {"ai_runtime": True, "gpu_build": True, "ram_gb": 16, "driver_cuda": "12.8", "free_gb": 20,
                 "nvidia": {"name": "GPU", "driver": "1", "vram_gb": 6.0, "used_mb": 0.0}}
        big = dict(small, nvidia={"name": "GPU", "driver": "1", "vram_gb": 16.0, "used_mb": 0.0})
        self.assertEqual((gpu_check.diagnose(small).recommended_profile, gpu_check.diagnose(small).recommended_layers), ("light", -1))
        self.assertEqual((gpu_check.diagnose(big).recommended_profile, gpu_check.diagnose(big).recommended_layers), ("full", -1))
        no_card = {"ai_runtime": True, "gpu_build": False, "ram_gb": 8, "free_gb": 20}
        self.assertEqual(gpu_check.diagnose(no_card).recommended_profile, "light")           # little RAM, no card
        self.assertEqual(gpu_check.diagnose(dict(no_card, ram_gb=32)).recommended_profile, "full")


class EstimateTest(unittest.TestCase):
    def stages(self, machine):
        return dict(eta.raw_estimate(DOC, machine, True, True))

    def test_the_light_model_is_faster_and_loads_quicker(self):
        full, light = self.stages(FULL), self.stages(LIGHT)
        for stage in ("purpose", "summaries", "sota"):
            self.assertLess(light[stage], full[stage], stage)

    def test_no_review_and_no_goal_stage_with_the_light_model(self):
        self.assertIn("language_review", self.stages(FULL))
        self.assertIn("goal", self.stages(FULL))
        self.assertNotIn("language_review", self.stages(LIGHT))
        self.assertNotIn("goal", self.stages(LIGHT))

    def test_runs_of_the_two_models_are_not_mixed_in_the_history(self):
        self.assertNotEqual(eta._kind(True, True, FULL), eta._kind(True, True, LIGHT))
        record = {"llm": True, "images": True, "n_images": 5, "gpu": True}
        self.assertEqual(eta._record_kind(record), eta._kind(True, True, FULL))
        self.assertEqual(eta._record_kind(dict(record, profile="light")), eta._kind(True, True, LIGHT))

    def test_machine_from_config_reads_the_profile(self):
        hw = {"gpu_build": True, "vram_gb": 16, "threads": 8}
        machine = eta.machine_from_config({"device": "cuda", "n_gpu_layers": -1, "model_profile": "light"}, hw)
        self.assertEqual(machine.profile, "light")


class ProcessTest(unittest.TestCase):
    def test_both_models_fit_a_16_gb_card_only_with_the_small_text_model(self):
        self.assertFalse(llm_process.can_overlap_figures(-1, free_mb=15500, profile="full"))
        self.assertTrue(llm_process.can_overlap_figures(-1, free_mb=15500, profile="light"))
        self.assertLess(llm_process.overlap_needs_mb(-1, "light"), llm_process.overlap_needs_mb(-1, "full"))

    def test_language_findings_all_stay_with_the_light_model(self):
        matches = [{"x": 1}, {"x": 2}]
        with mock.patch.object(config, "MODEL_PROFILE", "light"), \
                mock.patch.object(llm_process, "_run_once", side_effect=AssertionError("no process expected")):
            self.assertIs(llm_process.run_language_review_isolated(matches, "pl"), matches)
            self.assertIs(llm_task.run_language_review(matches, "pl"), matches)


class PanelTest(unittest.TestCase):
    def test_the_report_says_the_purpose_was_not_rated_with_the_light_model(self):
        try:
            from PySide6.QtWidgets import QApplication, QLabel
        except Exception as error:
            self.skipTest(f"Qt is not available: {error}")
        app = QApplication.instance() or QApplication([])      # noqa: F841
        from ui.report_panel import build_report_panel

        def texts(grade_info):
            content, _ = build_report_panel({"content_grade": grade_info, "language": "pl"}, lambda: None, [])
            return " | ".join(label.text() for label in content.findChildren(QLabel))

        light = dict(grade=80.0, max_grade=100.0, off_topic_sections=0, p_off=0, off_topic_headings=[],
                     purpose_score=None, purpose_reason="", model_profile="light")
        self.assertIn("nie jest oceniana", texts(light))
        full = dict(light, purpose_score=50, purpose_reason="Cel częściowo zrealizowany.", model_profile="full")
        self.assertNotIn("nie jest oceniana", texts(full))
        self.assertIn("Cel częściowo zrealizowany.", texts(full))


if __name__ == "__main__":
    unittest.main()
