"""Link between the running analysis and code that has no cancel token at hand (the AI models).

The analysis is cancelled with common.cancellation.CancelToken (the UI worker owns it and passes it down the
pipeline). Code deep inside, such as the llama.cpp wrapper that spends minutes in native code, cannot be handed the
token through every call, so the UI worker registers it here for the duration of the analysis:

    run_control.bind(token, sink)   # worker, at the start of the analysis (sink: callable(value, text) or None)
    run_control.unbind()            # worker, in `finally`
    run_control.check_cancelled()   # deep code: raises AnalysisCancelled when the token was cancelled
    run_control.notify(text, value) # deep code: a status line for the progress view

It adds no cancellation logic of its own: the token and AnalysisCancelled are those of common.cancellation.
"""

import logging
import threading

from common.cancellation import AnalysisCancelled

logger = logging.getLogger(__name__)

__all__ = ["AnalysisCancelled", "bind", "unbind", "is_cancelled", "check_cancelled", "notify"]

_lock = threading.Lock()
_token = None
_sink = None


def bind(token, sink=None):
    global _token, _sink
    with _lock:
        _token, _sink = token, sink


def unbind():
    bind(None, None)


def is_cancelled():
    token = _token
    return token is not None and token.is_cancelled()


def check_cancelled():
    token = _token
    if token is not None:
        token.check()


def notify(text, value=None):
    """Send a status line (and optionally a progress value) to the progress view; never raises except for a cancel."""
    sink = _sink
    if sink is None:
        return
    try:
        sink(-1 if value is None else int(value), str(text))
    except AnalysisCancelled:
        raise
    except Exception:
        logger.debug("Progress sink failed", exc_info=True)