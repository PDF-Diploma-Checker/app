import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common import gpu_startup

FULL_MODELS = {"gemma": True, "vision": True, "mmproj": True, "embeddings": True}
CARD = {"name": "RTX 4070", "driver": "560.1", "vram_gb": 12.0, "used_mb": 500.0}


def facts(**overrides):
    base = {
        "torch": "cuda", "ai_runtime": True, "gpu_build": True, "nvidia": CARD, "driver_cuda": "12.6",
        "other_gpus": [], "models": FULL_MODELS, "model_dir": "/models", "free_gb": 100.0,
    }
    base.update(overrides)
    return base


def ids(issues):
    return [issue.id for issue in issues]


class FindIssuesTest(unittest.TestCase):
    def test_nothing_missing(self):
        self.assertEqual(gpu_startup.find_issues(facts(), {}), [])

    def test_cpu_build_is_silent(self):
        broken = facts(torch="cpu", ai_runtime=False, nvidia=None, models={"gemma": False})
        self.assertEqual(gpu_startup.find_issues(broken, {"device": "cpu"}), [])

    def test_user_chose_the_processor(self):
        cfg = {"device": "cpu", "hardware_configured": True}
        self.assertEqual(gpu_startup.find_issues(facts(nvidia=None, models={"gemma": False}), cfg), [])

    def test_gpu_configured_on_a_build_without_cuda_torch(self):
        self.assertEqual(ids(gpu_startup.find_issues(facts(torch=None, nvidia=None), {"device": "cuda"})), ["gpu_none"])

    def test_no_card(self):
        self.assertEqual(ids(gpu_startup.find_issues(facts(nvidia=None, driver_cuda=None), {})), ["gpu_none"])

    def test_card_without_cuda(self):
        found = gpu_startup.find_issues(facts(nvidia=None, other_gpus=["AMD Radeon"]), {})
        self.assertEqual(ids(found), ["gpu_other"])
        self.assertEqual(found[0].params["name"], "AMD Radeon")

    def test_old_driver(self):
        found = gpu_startup.find_issues(facts(driver_cuda="11.8"), {})
        self.assertEqual(ids(found), ["driver"])
        self.assertEqual(found[0].params["needed"], "12.0")

    def test_base_build_is_silent(self):
        """The base build has no AI libraries and no detailed mode: nothing to report, even with a CUDA config."""
        base = facts(ai_runtime=False, gpu_build=False, models={"gemma": False})
        self.assertEqual(gpu_startup.find_issues(base, {"device": "cuda"}), [])

    def test_gpu_build_missing(self):
        self.assertEqual(ids(gpu_startup.find_issues(facts(gpu_build=False), {})), ["gpu_build"])

    def test_weak_card_gets_a_layer_count(self):
        found = gpu_startup.find_issues(facts(nvidia=dict(CARD, vram_gb=6.0, used_mb=0.0)), {})
        self.assertEqual(ids(found), ["vram"])
        self.assertEqual(found[0].params["layers"], 16)

    def test_tiny_card(self):
        found = gpu_startup.find_issues(facts(nvidia=dict(CARD, vram_gb=2.0, used_mb=0.0)), {})
        self.assertEqual(ids(found), ["vram_tiny"])

    def test_missing_models_are_named(self):
        models = dict(FULL_MODELS, vision=False, mmproj=False)
        found = gpu_startup.find_issues(facts(models=models), {})
        self.assertEqual(ids(found), ["models"])
        self.assertEqual(found[0].params["missing"], "Qwen2.5-VL 7B, Qwen2.5-VL projector")
        self.assertEqual(found[0].params["dir"], "/models")

    def test_low_disk_only_matters_with_missing_models(self):
        self.assertEqual(gpu_startup.find_issues(facts(free_gb=1.0), {}), [])
        found = gpu_startup.find_issues(facts(free_gb=1.0, models={"gemma": False}), {})
        self.assertEqual(ids(found), ["models", "disk"])

    def test_commands_follow_the_platform(self):
        with mock.patch.object(gpu_startup.sys, "platform", "win32"):
            self.assertEqual(gpu_startup.setup_command(), ".\\setup.ps1 gpu")
        with mock.patch.object(gpu_startup.sys, "platform", "linux"):
            self.assertEqual(gpu_startup.setup_command(), "./setup.sh gpu")


class DismissalTest(unittest.TestCase):
    def test_dismissed_only_for_the_same_issues(self):
        issues = [gpu_startup.Issue("models"), gpu_startup.Issue("gpu_none")]
        cfg = {gpu_startup.DISMISSED_KEY: gpu_startup.signature(issues)}
        self.assertTrue(gpu_startup.is_dismissed(issues, cfg))
        self.assertFalse(gpu_startup.is_dismissed(issues + [gpu_startup.Issue("driver")], cfg))
        self.assertFalse(gpu_startup.is_dismissed(issues, {}))
        self.assertFalse(gpu_startup.is_dismissed([], cfg))

    def test_check_skips_dismissed_and_cpu(self):
        from analysis.modules.llm import config
        found = [gpu_startup.Issue("models")]
        cfg = {"device": "cuda"}
        with mock.patch.object(config, "load_config", return_value=cfg), \
                mock.patch.object(config, "ai_models_status", return_value={}), \
                mock.patch.object(gpu_startup.gpu_check, "collect_facts", return_value={}), \
                mock.patch.object(gpu_startup, "find_issues", return_value=found):
            self.assertEqual(gpu_startup.check(), found)
            cfg[gpu_startup.DISMISSED_KEY] = gpu_startup.signature(found)
            self.assertEqual(gpu_startup.check(), [])
        cpu = {"device": "cpu", "hardware_configured": True}
        with mock.patch.object(config, "load_config", return_value=cpu), \
                mock.patch.object(gpu_startup.gpu_check, "collect_facts") as collect:
            self.assertEqual(gpu_startup.check(), [])
            collect.assert_not_called()


class DialogTest(unittest.TestCase):
    def test_every_issue_has_texts_in_both_languages(self):
        from ui import translations
        for table in (translations.PL, translations.EN):
            for issue in ("runtime", "gpu_none", "gpu_other", "driver", "gpu_build", "vram", "vram_tiny", "models", "disk"):
                self.assertIn("title", table["gpu_startup"][issue])
                self.assertIn("fix", table["gpu_startup"][issue])

    def test_dialog_lists_the_issues(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from ui.gpu_startup_dialog import GpuStartupDialog
        except ImportError as e:
            self.skipTest(f"Qt unavailable: {e}")
        app = QApplication.instance() or QApplication([])
        issues = gpu_startup.find_issues(facts(nvidia=None, models={"gemma": False}), {})
        dialog = GpuStartupDialog(issues)
        texts = [label.text() for label in dialog.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)]
        self.assertTrue(any("NVIDIA" in text for text in texts))
        self.assertTrue(any("Gemma" in text for text in texts))
        self.assertFalse(dialog.open_setup)
        dialog.deleteLater()
        del app


if __name__ == "__main__":
    unittest.main()
