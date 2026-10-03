"""Central logging config: call configure_logging() once at startup.
Sets up a rotating file handler (platformdirs log dir), a queue handler for the log window, and global exception hooks."""

import logging
import logging.handlers
import queue
import sys
import threading
from pathlib import Path

import platformdirs

APP_NAME = "Diploma Checker"
LOG_FILENAME = "app.log"
MAX_BYTES = 5_000_000
BACKUP_COUNT = 3

_log_queue = queue.Queue()
_configured = False


def get_log_dir():
    """Return the per-user log directory, creating it if it doesn't exist yet."""

    log_dir = Path(platformdirs.user_log_dir(APP_NAME, appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file_path():
    """Return the path to the main (current) log file."""

    return get_log_dir() / LOG_FILENAME


def get_log_queue():
    """Return the shared queue fed by the root logger's queue handler."""

    return _log_queue


def _log_unhandled_exception(exc_type, exc_value, exc_traceback):
    """sys.excepthook replacement: log instead of printing to a (possibly
    nonexistent) stderr and losing the traceback."""

    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logging.getLogger("unhandled").critical(
        "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
    )


def _log_unhandled_thread_exception(args):
    """threading.excepthook replacement: log exceptions that escape a
    background thread's run() instead of letting them print to stderr only."""

    logging.getLogger("unhandled").critical(
        "Unhandled exception in thread %r",
        args.thread.name if args.thread is not None else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def configure_logging(level=logging.INFO):
    """Attach handlers to the root logger and install the global exception
    hooks. Safe to call more than once; returns the log file path."""

    global _configured

    if _configured:
        return get_log_file_path()

    log_file = get_log_file_path()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    queue_handler = logging.handlers.QueueHandler(_log_queue)
    queue_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(queue_handler)

    # A frozen --windowed/--noconsole build has no console, and
    # sys.stderr can be None there - only log to it when it actually exists.
    if sys.stderr is not None:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    sys.excepthook = _log_unhandled_exception
    threading.excepthook = _log_unhandled_thread_exception

    _configured = True

    logging.getLogger(__name__).info("Logging initialized, writing to %s", log_file)

    return log_file
