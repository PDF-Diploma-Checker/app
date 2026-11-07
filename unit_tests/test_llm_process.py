"""The AI part runs in its own process: a native crash there (llama.cpp abort, access violation) must come back as
an analysis error with a useful hint, not take the app down."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import llm_process
from common import run_control
from common.cancellation import AnalysisCancelled, CancelToken

PDF = Path(__file__).resolve().parent / "linguistics" / "acronyms" / "fp_acronym_list_subscript_pdflatex.pdf"
CARD_8GB = {"name": "RTX Test", "driver": "1", "vram_gb": 6.0, "used_mb": 0.0}


class ExitCodeTest(unittest.TestCase):
    def test_windows_codes(self):
        self.assertIn("access violation", llm_process.describe_exit_code(0xC0000005))
        self.assertIn("access violation", llm_process.describe_exit_code(-1073741819))     # the same, signed
        self.assertIn("abort", llm_process.describe_exit_code(3))

    def test_posix_signals(self):
        self.assertIn("SIGABRT", llm_process.describe_exit_code(-6))
        self.assertIn("SIGSEGV", llm_process.describe_exit_code(-11))


class DiagnosisTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(llm_process, "_gpu_facts", return_value=CARD_8GB)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cuda_out_of_memory_names_the_layers(self):
        tail = "ggml_backend_cuda_buffer_type_alloc_buffer: cudaMalloc failed: out of memory\nGGML_ASSERT(x) failed"
        kind, hint = llm_process.diagnose_crash(-6, tail, 25)
        self.assertEqual(kind, "oom")
        self.assertIn("25", hint)
        self.assertIn("RTX Test", hint)
        self.assertIn("16", hint)           # recommended for 6 GB

    def test_killed_by_the_system(self):
        self.assertEqual(llm_process.diagnose_crash(-9, "", 0)[0], "ram")

    def test_unknown_crash_on_gpu_still_suggests_fewer_layers(self):
        kind, hint = llm_process.diagnose_crash(0xC0000005, "nothing useful", 25)
        self.assertEqual(kind, "unknown")
        self.assertIn("25", hint)

    def test_layers_warning(self):
        self.assertIsNotNone(llm_process.layers_warning(25))      # 6 GB card: 16 recommended
        self.assertIsNone(llm_process.layers_warning(8))
        self.assertIsNone(llm_process.layers_warning(0))

    def test_fewer_layers(self):
        self.assertEqual(llm_process._fewer_layers(25), 12)
        self.assertEqual(llm_process._fewer_layers(1), 0)
        self.assertEqual(llm_process._fewer_layers(-1), 8)        # half of the recommended 16

    def test_most_specific_error_line(self):
        tail = "load ok\nGGML_ASSERT(buf != NULL) failed\nFatal Python error: Aborted\n  File \"x.py\", line 1"
        self.assertEqual(llm_process._last_error_line(tail), "GGML_ASSERT(buf != NULL) failed")


@unittest.skipUnless(PDF.is_file(), "test PDF missing")
class IsolationTest(unittest.TestCase):
    """Start the real child process and let it die like llama.cpp does."""

    def _run(self, crash, token=None):
        from analysis.extraction.main_extractor import extractPDF

        problems = []
        run_control.bind(token, None, lambda title, text, popup=True: problems.append(text) if popup else None)
        self.addCleanup(run_control.unbind)
        with mock.patch.dict(os.environ, {llm_process.CRASH_TEST_ENV: crash}), \
                mock.patch.object(llm_process, "_gpu_facts", return_value=None):
            result = llm_process.run_task_llm_isolated(extractPDF(str(PDF)), str(PDF), "pl", True, False, token)
        return result, problems

    def test_abort_becomes_an_analysis_error(self):
        result, problems = self._run("abort")
        failure = result[0]["analysis_error"]
        self.assertTrue(failure["crashed"])
        self.assertIsNone(result[1])
        self.assertEqual(len(problems), 1)          # the user is told once, at the end of the attempts

    def test_cancel_kills_a_stuck_process(self):
        import threading

        token = CancelToken()
        threading.Timer(1.0, token.cancel).start()
        with self.assertRaises(AnalysisCancelled):
            self._run("hang", token)


if __name__ == "__main__":
    unittest.main()
