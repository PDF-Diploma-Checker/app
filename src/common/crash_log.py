"""What is left when the application dies in native code (llama.cpp, Qt), where Python cannot catch anything.

faulthandler writes the stacks to crash.log next to the app log, and a marker file left behind by an analysis that
never finished lets the next start tell the user what happened.
"""

import faulthandler
import logging

from common.logging_setup import get_log_dir

logger = logging.getLogger(__name__)

CRASH_LOG_NAME = "crash.log"
_MARKER_NAME = "analysis_running"
_crash_file = None      # faulthandler keeps writing to it, so it has to stay open


def crash_log_path():
    return get_log_dir() / CRASH_LOG_NAME


def _marker():
    return get_log_dir() / _MARKER_NAME


def enable():
    """Send native crashes to crash.log. A build without a console has no stderr to write them to."""
    global _crash_file
    try:
        _crash_file = open(crash_log_path(), "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file)
    except (OSError, RuntimeError, ValueError):
        logger.exception("Could not enable the crash log")


def analysis_started(pdf_path):
    try:
        _marker().write_text(str(pdf_path), encoding="utf-8")
    except OSError:
        logger.exception("Could not write the analysis marker")


def analysis_finished():
    try:
        _marker().unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not remove the analysis marker")


def previous_analysis_crashed():
    """True once when the last analysis never reported its end."""
    marker = _marker()
    try:
        if not marker.exists():
            return False
        logger.error("The previous analysis of %s did not finish: the application crashed or was killed",
                     marker.read_text(encoding="utf-8"))
        marker.unlink()
        return True
    except OSError:
        logger.exception("Could not read the analysis marker")
        return False
