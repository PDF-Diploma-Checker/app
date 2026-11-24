"""Repeating a network call after a short failure: waits 1 s, 2 s, 4 s ... with a random share added (jitter), so a
brief outage does not become an error at once and many clients do not all knock at the same moment."""

import random
import time


def backoff_delays(attempts, base=1.0, jitter=0.25):
    """The waits between `attempts` tries: base, 2 * base, 4 * base ..., each plus up to `jitter` of itself."""
    return [base * (2 ** i) * (1 + random.uniform(0, jitter)) for i in range(max(attempts - 1, 0))]


def retry_call(function, retry_on, attempts=3, base=1.0, jitter=0.25, sleep=time.sleep):
    """Call `function()`; on one of the `retry_on` exceptions wait and try again, up to `attempts` times in all.
    The last error is raised. Only for calls that are safe to repeat (a GET, or a POST that carries an
    Idempotency-Key)."""
    delays = backoff_delays(attempts, base, jitter)
    for number in range(attempts):
        try:
            return function()
        except retry_on:
            if number == attempts - 1:
                raise
            sleep(delays[number])
