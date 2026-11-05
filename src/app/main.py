import logging
import os
import sys

if not getattr(sys, "frozen", False):        # in a build app/launcher.py starts this file
    _SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)

from common.logging_setup import configure_logging

log_file = configure_logging()
logger = logging.getLogger(__name__)

from PySide6.QtWidgets import QApplication, QMessageBox
from analysis.modules.llm.config import check_and_download_requirements, java_available, llm_runtime_available
from common import crash_log
from ui import error_dialog, styles
from ui.license_dialog import ensure_accepted
from ui.main_window import PDFReader

SMOKE_MODULES = [
    "ui.main_window", "ui.settings", "ui.report_bug", "ui.log_window", "ui.analysis_dialog",
    "ui.ai_setup_dialog", "common.gpu_check", "common.run_control", "common.resource_monitor",
    "ui.update_dialog", "common.updater",
    "app.entry", "app.pipeline", "app.llm_task",
    "analysis.modules.linguistics.run_linguistics",
    "analysis.modules.redaction.redaction_validator",
]


def smoke_test():
    """Import everything, load spaCy models, build the main window. Exit code 0 = OK."""
    import importlib
    failures = []

    modules = list(SMOKE_MODULES)
    if llm_runtime_available():     # the base variant has no AI libraries
        # similarity pulls in sentence_transformers, sklearn and scipy, which can fail to import only when frozen
        modules += ["analysis.modules.llm.similarity", "analysis.modules.llm.get_grade",
                    "analysis.modules.llm.image_analysis.run_image", "analysis.modules.llm.image_analysis.font_checker",
                    "analysis.modules.llm.image_analysis.axis_checker",
                    "analysis.modules.llm.image_analysis.image_quality_checker"]
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as e:
            failures.append(f"import {name}: {e!r}")

    try:
        import spacy
        for model in ("pl_core_news_lg", "en_core_web_lg"):
            spacy.load(model)
    except Exception as e:
        failures.append(f"spacy: {e!r}")

    try:
        app = QApplication.instance() or QApplication(sys.argv)
        PDFReader()
    except Exception as e:
        failures.append(f"main window: {e!r}")

    with open("smoke_test.log", "w", encoding="utf-8") as f:
        f.write("\n".join(failures) if failures else "SMOKE OK")
    return 1 if failures else 0


def analysis_test(pdf_path):
    """Run a full detailed analysis of a PDF in this build, with the real models. Exit code 0 = it finished with results
    and with no failed figure stage. For checking a build before a release: --analysis-test thesis.pdf"""
    from app.entry import run_analysis_for_pdf

    result = getattr(run_analysis_for_pdf(pdf_path, use_llm=True), "llm_result", None)
    images = (result or {}).get("image_analysis") or {}
    ok = bool(result) and not images.get("analysis_failed") and not result.get("analysis_error")
    with open("analysis_test.log", "w", encoding="utf-8") as f:
        f.write(("ANALYSIS OK " if ok else "ANALYSIS FAILED ") + repr((result or {}).get("analysis_error") or images) + "\n")
    return 0 if ok else 1


def _finish_pending_update():
    """The app was just restarted by the updater: read how the swap went and clean up the leftovers."""
    try:
        from common import updater
        return updater.finish_pending_update()
    except Exception:
        logger.exception("Could not finish the pending update")
        return None


def _show_update_result(result):
    from common.version import APP_VERSION
    from ui.i18n import t
    if result["status"] == "ok":
        QMessageBox.information(None, t("updater.title"), t("updater.result_ok", version=APP_VERSION))
    else:
        QMessageBox.warning(None, t("updater.title"), t("updater.result_failed", log=result["log"]))


def main():
    app = QApplication(sys.argv)
    styles.apply_global_style(app)
    crash_log.enable()
    error_dialog.install()
    if not ensure_accepted():
        sys.exit(0)
    check_and_download_requirements()
    if not java_available():
        QMessageBox.warning(
            None, "Brak Javy",
            "Nie wykryto Javy 17+. Analiza językowa (LanguageTool) nie będzie działać.\n"
            "Zainstaluj Javę i uruchom aplikację ponownie.",
        )
    update_result = _finish_pending_update()
    window = PDFReader()
    window.show()
    if crash_log.previous_analysis_crashed():
        from ui.i18n import t
        QMessageBox.warning(window, t("analysis.crashed_title"), t("analysis.crashed_text"))
    if update_result:
        _show_update_result(update_result)
    sys.exit(app.exec())


def run():
    if "--smoke-test" in sys.argv:
        sys.exit(smoke_test())
    if "--analysis-test" in sys.argv:
        sys.exit(analysis_test(sys.argv[sys.argv.index("--analysis-test") + 1]))
    try:
        main()
    except Exception:
        logger.exception("Unhandled exception, application terminating")
        raise


if __name__ == "__main__":
    run()
