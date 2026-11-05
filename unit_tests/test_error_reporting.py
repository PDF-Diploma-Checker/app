import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common import crash_log


class CrashMarkerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(crash_log, "get_log_dir", return_value=Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_finished_analysis_leaves_nothing(self):
        crash_log.analysis_started("thesis.pdf")
        crash_log.analysis_finished()
        self.assertFalse(crash_log.previous_analysis_crashed())

    def test_unfinished_analysis_is_reported_once(self):
        crash_log.analysis_started("thesis.pdf")
        self.assertTrue(crash_log.previous_analysis_crashed())
        self.assertFalse(crash_log.previous_analysis_crashed())


class LlmFailureTest(unittest.TestCase):
    def test_failure_names_the_stage_and_the_error(self):
        try:
            import analysis.extraction.helper_llm.converter_linguistics_llm as converter
        except ImportError as error:
            self.skipTest(str(error))
        from app.llm_task import run_task_llm

        with mock.patch.object(converter, "get_plain_text", side_effect=NameError("name 'obj' is not defined")), \
                mock.patch("analysis.extraction.linguistics_conversion.converter_linguistics_clean.PDFMapper"), \
                self.assertLogs("app.llm_task", "ERROR"), mock.patch("traceback.print_exc"):
            result, score, _ = run_task_llm(mock.Mock(), "thesis.pdf")
        self.assertIsNone(score)
        self.assertEqual(result["analysis_error"]["stage"], "preparing the text")
        self.assertRegex(result["analysis_error"]["error"], r"^(NameError|ModuleNotFoundError): ")     # no AI libraries on CI


class ReportShowsFailureTest(unittest.TestCase):
    def test_pdf_report(self):
        try:
            import fitz
            from ui.report_pdf import build_report_pdf
        except ImportError as error:
            self.skipTest(str(error))
        data = {"analysis_error": {"stage": "x", "error": "y"}, "image_analysis": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp, "report.pdf"))
            build_report_pdf(data, "t.pdf", "pl", path)
            with fitz.open(path) as doc:
                text = " ".join(" ".join(page.get_text().split()) for page in doc)
        self.assertIn("Analiza merytoryczna nie", text)


class ErrorDialogTest(unittest.TestCase):
    def test_exception_from_a_thread_opens_one_dialog(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from ui import error_dialog
        except ImportError as error:
            self.skipTest(str(error))
        app = QApplication.instance() or QApplication([])
        hooks = sys.excepthook, threading.excepthook
        self.addCleanup(lambda: (setattr(sys, "excepthook", hooks[0]), setattr(threading, "excepthook", hooks[1]),
                                 setattr(error_dialog, "_bridge", None)))
        sys.excepthook, threading.excepthook = mock.Mock(), mock.Mock()
        error_dialog._bridge = None
        error_dialog.install()

        def fail():
            raise ValueError("boom")

        with mock.patch.object(error_dialog.MessageBox, "critical") as critical:
            thread = threading.Thread(target=fail)
            thread.start()
            thread.join()
            app.processEvents()
        critical.assert_called_once()
        self.assertIn("ValueError: boom", critical.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
