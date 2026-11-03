'''
Tests of the figure analysis around the vision model. No model is needed: the answers are given by the test.

Run (from the repository root):
    .venv/bin/python -m unittest unit_tests.extraction.test_vision_analysis -v
'''
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from analysis.modules.llm.image_analysis import vision_engine
    from analysis.modules.llm.image_analysis.consistency_checker import verdict_from_answer
except ImportError as e:  # the base variant has no AI libraries
    raise unittest.SkipTest(f"AI libraries are not available: {e}")


class VerdictTest(unittest.TestCase):
    def test_no_mismatches(self):
        self.assertEqual(verdict_from_answer({"niezgodnosci": []})["poprawnosc_danych"], "True")

    def test_items_with_equal_values_are_not_mismatches(self):
        answer = {"niezgodnosci": [{"element": "gzip", "w_tekscie": "180 ms", "na_rysunku": "180ms"}]}
        self.assertEqual(verdict_from_answer(answer)["poprawnosc_danych"], "True")

    def test_mismatch_names_both_values(self):
        answer = {"niezgodnosci": [
            {"element": "zstd", "w_tekscie": "75%", "na_rysunku": "68%"},
            {"element": "gzip", "w_tekscie": "62%", "na_rysunku": "62%"},
        ]}
        result = verdict_from_answer(answer)
        self.assertEqual(result["poprawnosc_danych"], "False")
        self.assertEqual(result["bledy"], "zstd: w tekście 75%, na rysunku 68%")

    def test_mismatch_in_english(self):
        answer = {"niezgodnosci": [{"element": "zstd", "w_tekscie": "75%", "na_rysunku": "68%"}]}
        self.assertEqual(verdict_from_answer(answer, "en")["bledy"], "zstd: 75% in the text, 68% in the figure")

    def test_answer_without_the_list_is_an_error(self):
        self.assertEqual(verdict_from_answer({"cos": 1})["poprawnosc_danych"], "Error")


class UnreadableFigureTest(unittest.TestCase):
    def test_unreadable_figure_is_listed_but_is_not_a_failure_or_an_error_in_the_thesis(self):
        from app.llm_task import build_image_summary

        summary = build_image_summary([{"obrazek": "Rys. 1", "poprawnosc_danych": "Unreadable", "bledy": "x"}])
        self.assertEqual((summary["total"], summary["bad_count"], summary["good_count"]), (1, 0, 0))
        self.assertFalse(summary["analysis_failed"])
        self.assertEqual(len(summary["problem_details"]), 1)


class ImageSizeTest(unittest.TestCase):
    def _png(self, width, height):
        import io
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (width, height), "white").save(buffer, "PNG")
        return buffer.getvalue()

    def test_tiny_image_cannot_be_read(self):
        self.assertTrue(vision_engine.too_small_to_read(self._png(90, 60)))

    def test_normal_image_can_be_read(self):
        self.assertFalse(vision_engine.too_small_to_read(self._png(600, 400)))


class MemoryTest(unittest.TestCase):
    def test_closing_frees_the_model_and_the_projector(self):
        handler, llm = MagicMock(), MagicMock()
        with patch.object(vision_engine, "Qwen25VLChatHandler", return_value=handler), \
                patch.object(vision_engine, "make_llama", return_value=llm):
            with vision_engine.VisionEngine("test"):
                pass
        llm.close.assert_called_once()
        handler._exit_stack.close.assert_called_once()

    def test_failed_load_frees_the_projector(self):
        handler = MagicMock()
        with patch.object(vision_engine, "Qwen25VLChatHandler", return_value=handler), \
                patch.object(vision_engine, "make_llama", side_effect=OSError("no file")):
            with self.assertRaises(RuntimeError):
                vision_engine.VisionEngine("test")
        handler._exit_stack.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
