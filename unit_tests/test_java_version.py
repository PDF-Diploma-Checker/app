import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.llm import config
from common import gpu_check


def _java_says(stderr, returncode=0):
    result = subprocess.CompletedProcess([], returncode, stdout="", stderr=stderr)
    return (mock.patch.object(config.shutil, "which", return_value="/usr/bin/java"),
            mock.patch.object(config.subprocess, "run", return_value=result))


class JavaVersionTest(unittest.TestCase):
    def version_of(self, stderr, returncode=0):
        which, run = _java_says(stderr, returncode)
        with which, run:
            return config.java_version(), config.java_available()

    def test_new_scheme(self):
        self.assertEqual(self.version_of('openjdk version "17.0.2" 2022-01-18'), (17, True))
        self.assertEqual(self.version_of('openjdk version "21" 2023-09-19'), (21, True))
        self.assertEqual(self.version_of('openjdk version "25.0.3" 2026-04-21'), (25, True))

    def test_old_scheme_is_too_old(self):
        self.assertEqual(self.version_of('java version "1.8.0_292"'), (8, False))
        self.assertEqual(self.version_of('openjdk version "11.0.20" 2023-07-18'), (11, False))

    def test_unreadable_or_failing(self):
        self.assertEqual(self.version_of("garbage"), (None, False))
        self.assertEqual(self.version_of('openjdk version "21"', returncode=1), (None, False))

    def test_missing(self):
        with mock.patch.object(config.shutil, "which", return_value=None):
            self.assertEqual((config.java_version(), config.java_available()), (None, False))


class JavaCheckTest(unittest.TestCase):
    def java_check(self, java, version):
        facts = {"java": java, "java_version": version, "models_ready": True, "threads": 8, "ram_gb": 32}
        return next(c for c in gpu_check.diagnose(facts).checks if c.id.startswith("java"))

    def test_ok(self):
        check = self.java_check(True, 21)
        self.assertEqual((check.id, check.level), ("java", "ok"))

    def test_too_old_names_the_version(self):
        check = self.java_check(False, 8)
        self.assertEqual((check.id, check.level, check.params["version"]), ("java_old", "fail", 8))

    def test_missing(self):
        check = self.java_check(False, None)
        self.assertEqual((check.id, check.level), ("java", "fail"))


class JavaProblemTest(unittest.TestCase):
    def test_message_names_the_old_version(self):
        with mock.patch.object(config, "java_version", return_value=8):
            message = config.java_problem()
        self.assertIn("8", message)
        self.assertIn("17", message)

    def test_instructions_for_the_users_system(self):
        for system, hint in [("Windows", "Add to PATH"), ("Linux", "alternatives --config java")]:
            with mock.patch.object(config.platform, "system", return_value=system), \
                    mock.patch.object(config, "java_version", return_value=8):
                self.assertIn(hint, config.java_problem())

    def test_instructions_stay_out_of_the_log(self):
        report = gpu_check.diagnose({"java": False, "java_version": 8, "models_ready": True})
        check = next(c for c in report.checks if c.id == "java_old")
        self.assertIn("howto", check.params)
        self.assertIn("[fail] java_old (version=8, min=17)", report.as_text())

    def test_missing_and_ok(self):
        with mock.patch.object(config, "java_version", return_value=None):
            self.assertTrue(config.java_problem())
        with mock.patch.object(config, "java_version", return_value=21):
            self.assertIsNone(config.java_problem())


class AnalysisFailsWithoutJavaTest(unittest.TestCase):
    def test_pipeline_stops_before_extraction(self):
        from app import pipeline
        document = mock.Mock(pdf_path=__file__)
        with mock.patch.object(pipeline, "java_problem", return_value="update Java"), \
                mock.patch("analysis.extraction.main_extractor.extractPDF") as extract:
            with self.assertRaisesRegex(config.LanguageToolUnavailable, "update Java"):
                pipeline.AnalysisPipeline()._run(document, use_llm=False)
        extract.assert_not_called()

    def test_language_tool_is_started_before_extraction_and_the_ai(self):
        # a failure found later, in the language thread, would only show up after the AI thread had finished
        from app import pipeline
        from analysis.modules.linguistics import language_error_extractor as extractor
        document = mock.Mock(pdf_path=__file__)
        failure = config.LanguageToolUnavailable("LanguageTool did not start")
        with mock.patch.object(pipeline, "java_problem", return_value=None), \
                mock.patch.object(extractor, "start_language_tools", side_effect=failure), \
                mock.patch("analysis.extraction.main_extractor.extractPDF") as extract, \
                mock.patch("app.llm_process.run_task_llm_isolated") as llm:
            with self.assertRaisesRegex(config.LanguageToolUnavailable, "did not start"):
                pipeline.AnalysisPipeline()._run(document, use_llm=True)
        extract.assert_not_called()
        llm.assert_not_called()

    def test_language_tool_that_did_not_start_fails_the_analysis(self):
        from analysis.modules.linguistics import language_error_extractor as extractor
        for pl, en in [(None, None), (mock.Mock(), None), (None, mock.Mock())]:
            with mock.patch.object(extractor, "_TOOL_PL", pl), mock.patch.object(extractor, "_TOOL_EN", en), \
                    mock.patch.object(extractor, "_init_language_tools"), \
                    mock.patch.object(config, "java_version", return_value=8):
                with self.assertRaisesRegex(config.LanguageToolUnavailable, "Jav"):
                    extractor.language_tool_analisys([])


if __name__ == "__main__":
    unittest.main()
