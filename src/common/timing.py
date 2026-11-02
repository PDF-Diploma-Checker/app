"""Time measurements for the application log."""

import time
from contextlib import contextmanager


@contextmanager
def log_time(logger, label):
    """Log how long the block took, also when it ended with an error or a cancellation."""
    start = time.perf_counter()
    status = "finished"
    try:
        yield
    except BaseException:
        status = "interrupted"
        raise
    finally:
        logger.info("[TIME] %s: %.1f s (%s)", label, time.perf_counter() - start, status)


class StageTimer:
    """Logs the time of consecutive stages: each next() ends the previous stage."""

    def __init__(self, logger, prefix):
        self.logger = logger
        self.prefix = prefix
        self.label = None
        self.start = 0.0

    def next(self, label):
        self.finish()
        self.label = label
        self.start = time.perf_counter()

    def finish(self):
        if self.label is not None:
            self.logger.info("[TIME] %s - %s: %.1f s", self.prefix, self.label, time.perf_counter() - self.start)
            self.label = None
