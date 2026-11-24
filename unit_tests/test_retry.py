import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.retry import backoff_delays, retry_call


class BackoffTest(unittest.TestCase):
    def test_waits_double_and_stay_within_jitter(self):
        delays = backoff_delays(4, base=1.0, jitter=0.25)
        self.assertEqual(len(delays), 3)
        for expected, actual in zip((1.0, 2.0, 4.0), delays):
            self.assertGreaterEqual(actual, expected)
            self.assertLessEqual(actual, expected * 1.25)

    def test_single_attempt_has_no_wait(self):
        self.assertEqual(backoff_delays(1), [])


class RetryCallTest(unittest.TestCase):
    def test_succeeds_after_two_failures(self):
        calls, waits = [], []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("down")
            return "ok"

        self.assertEqual(retry_call(flaky, ConnectionError, attempts=3, sleep=waits.append), "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(waits), 2)

    def test_raises_the_last_error_when_every_try_fails(self):
        waits = []
        with self.assertRaises(ConnectionError):
            retry_call(lambda: (_ for _ in ()).throw(ConnectionError("down")), ConnectionError,
                       attempts=3, sleep=waits.append)
        self.assertEqual(len(waits), 2)

    def test_other_errors_are_not_retried(self):
        calls = []

        def broken():
            calls.append(1)
            raise ValueError("bad")

        with self.assertRaises(ValueError):
            retry_call(broken, ConnectionError, attempts=3, sleep=lambda _s: None)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
