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
    from analysis.modules.llm.image_analysis.consistency_checker import values_are_printed, verdict_from_answer
except ImportError as e:  # the base variant has no AI libraries
    raise unittest.SkipTest(f"AI libraries are not available: {e}")


class VerdictTest(unittest.TestCase):
    def test_no_mismatches(self):
        self.assertEqual(verdict_from_answer({"niezgodnosci": []})["poprawnosc_danych"], "True")

    def test_bare_number_in_the_figure_agrees_with_the_text(self):
        answer = {"niezgodnosci": [{"element": "S3", "w_tekscie": "200 błędów", "na_rysunku": "200"}]}
        self.assertEqual(verdict_from_answer(answer)["poprawnosc_danych"], "True")

    def test_different_units_stay_a_mismatch(self):
        answer = {"niezgodnosci": [{"element": "kopia", "w_tekscie": "300 ms", "na_rysunku": "300 s"}]}
        self.assertEqual(verdict_from_answer(answer)["poprawnosc_danych"], "False")

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

    def test_value_not_printed_in_the_figure_is_no_mismatch(self):
        """A chart without values: the model made up 100 when reading it, and the text gives 40 GB."""
        answer = {"niezgodnosci": [{"element": "A", "w_tekscie": "40 GB", "na_rysunku": "100"}]}
        self.assertEqual(verdict_from_answer(answer, printed=[])["poprawnosc_danych"], "Unreadable")

    def test_printed_value_stays_a_mismatch(self):
        answer = {"niezgodnosci": [{"element": "tekst", "w_tekscie": "40%", "na_rysunku": "70%"},
                                   {"element": "S1", "w_tekscie": "10", "na_rysunku": "2"}]}
        result = verdict_from_answer(answer, printed=[70, 20, 10])
        self.assertEqual(result["poprawnosc_danych"], "False")
        self.assertIn("tekst", result["bledy"])
        self.assertNotIn("S1", result["bledy"])

    def test_no_list_of_numbers_decides_nothing(self):
        answer = {"niezgodnosci": [{"element": "A", "w_tekscie": "40", "na_rysunku": "100"}]}
        self.assertEqual(verdict_from_answer(answer, printed=None)["poprawnosc_danych"], "False")

    def _verdict(self, in_text, in_image, **kwargs):
        answer = {"niezgodnosci": [{"element": "A", "w_tekscie": in_text, "na_rysunku": in_image}]}
        return verdict_from_answer(answer, **kwargs)["poprawnosc_danych"]

    def test_the_same_number_written_differently_agrees(self):
        for in_text, in_image in (("0,9", "0.90"), ("40,0%", "40%"), ("5000 ms", "5,000 ms"), ("0.989", "1.0")):
            self.assertEqual(self._verdict(in_text, in_image), "True", (in_text, in_image))

    def test_a_fraction_with_three_places_is_no_thousand(self):
        self.assertEqual(self._verdict("0,989", "989"), "False")

    def test_value_within_a_range_in_the_text_agrees(self):
        self.assertEqual(self._verdict("0,4–0,6", "0.5"), "True")
        self.assertEqual(self._verdict("0,4–0,6", "0.8"), "False")

    def test_words_are_not_values(self):
        self.assertEqual(self._verdict("odrzucone", "0.8"), "Unreadable")

    def test_value_the_paragraph_does_not_give_is_no_mismatch(self):
        self.assertEqual(self._verdict("75%", "68%", paragraph="Rysunek 1: zstd osiągnął 68%."), "Unreadable")
        self.assertEqual(self._verdict("75%", "68%", paragraph="Rysunek 1: zstd osiągnął 75%."), "False")

    def test_number_of_an_axis_scale_is_not_a_printed_value(self):
        printed = [0, 5000, 10000, 15000, 20000, 0, 0.2, 0.4, 0.6, 0.8, 1.0]
        self.assertEqual(self._verdict("0.7", "1.0", printed=printed), "Unreadable")

    def test_chart_read_from_its_labels_is_compared(self):
        self.assertTrue(values_are_printed("Czas\ngzip: 180 ms\nlz4: 20 ms", [180, 70, 20]))

    def test_chart_estimated_from_its_axis_is_not_compared(self):
        self.assertFalse(values_are_printed("W0: 0.2\nW1: 0.6\nW2: 1.0", [0, 5000, 10000, 15000, 20000, 1.0]))
        self.assertFalse(values_are_printed("Evolution\nA: B", []))

    def test_no_list_of_numbers_keeps_the_comparison(self):
        self.assertTrue(values_are_printed("A: 1", None))

    def test_ratio_is_not_compared_as_a_count(self):
        self.assertEqual(self._verdict("37/80", "35"), "Unreadable")

    def test_hallucinated_figure_value_is_not_a_discrepancy(self):
        self.assertEqual(self._verdict("0.81", "0", paragraph="Wynik 0.81", image_data="kontakt: 0.8"), "Unreadable")

    def test_unverified_reading_is_not_reported_as_correct(self):
        from analysis.modules.llm.image_analysis.consistency_checker import ConsistencyChecker
        checker = object.__new__(ConsistencyChecker)
        checker.llm = MagicMock()
        result = checker.check("Wynik 0.7", "A: 0.8", printed=[])
        self.assertEqual(result["poprawnosc_danych"], "Unreadable")
        checker.llm.create_chat_completion.assert_not_called()

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


class ProjectorPlaceTest(unittest.TestCase):
    def load(self, layers=8, gpus=()):
        handler = MagicMock()
        with patch.object(vision_engine, "Qwen25VLChatHandler", return_value=handler), \
                patch.object(vision_engine, "make_llama", return_value=MagicMock()), \
                patch.object(vision_engine.config, "N_GPU_LAYERS", layers), \
                patch.object(vision_engine.gpu_check, "nvidia_gpus", return_value=list(gpus)):
            vision_engine.VisionEngine("test")
        return isinstance(handler._mtmd_cpp, vision_engine._ProjectorOnCpu)

    def test_a_small_card_keeps_the_projector_on_the_processor(self):
        # an RTX 3050 Laptop with the model loaded: about 2 GB of 4 GB free
        self.assertTrue(self.load(gpus=[{"vram_gb": 4.0, "used_mb": 2000}]))

    def test_a_big_card_takes_the_projector(self):
        self.assertFalse(self.load(gpus=[{"vram_gb": 16.0, "used_mb": 2000}]))

    def test_the_processor_keeps_it_when_the_model_is_there(self):
        self.assertTrue(self.load(layers=0, gpus=[{"vram_gb": 16.0, "used_mb": 0}]))

    def test_without_nvidia_smi_llama_cpp_decides(self):
        self.assertFalse(self.load(gpus=[]))

    def test_the_projector_is_asked_for_without_the_gpu(self):
        module, params = MagicMock(), MagicMock(use_gpu=True)
        vision_engine._ProjectorOnCpu(module).mtmd_init_from_file(b"mmproj", "model", params)
        self.assertFalse(params.use_gpu)
        module.mtmd_init_from_file.assert_called_once_with(b"mmproj", "model", params)


if __name__ == "__main__":
    unittest.main()
