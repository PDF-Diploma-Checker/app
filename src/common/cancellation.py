import threading


class AnalysisCancelled(BaseException):
    """Raised at a checkpoint once the user has cancelled the analysis.

    Derives from BaseException so the many ``except Exception`` blocks in the
    analysis modules do not swallow it.
    """


class CancelToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    def is_cancelled(self):
        return self._event.is_set()

    def check(self):
        if self._event.is_set():
            raise AnalysisCancelled()


def check_cancelled(token):
    """Checkpoint helper that tolerates a missing token."""
    if token is not None:
        token.check()
