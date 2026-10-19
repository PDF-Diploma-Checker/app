import logging
import os
import sys

if getattr(sys, "frozen", False):
    # Windowed build has no console: stdout/stderr are None and break tqdm & co.
    for _name in ("stdout", "stderr"):
        if getattr(sys, _name) is None:
            setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
else:
    _SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)

from common.logging_setup import configure_logging

log_file = configure_logging()
logger = logging.getLogger(__name__)

from PySide6.QtWidgets import QApplication, QMessageBox
from analysis.modules.llm.config import check_and_download_requirements, java_available
from ui import styles
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

    for name in SMOKE_MODULES:
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
    if update_result:
        _show_update_result(update_result)
    sys.exit(app.exec())


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        sys.exit(smoke_test())
    try:
        main()
    except Exception:
        logger.exception("Unhandled exception, application terminating")
        raise