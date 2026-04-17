import unittest
from unittest.mock import patch

from core.exceptions import JobCancelledError
from core.retry import execute_with_retry


class RetryTests(unittest.TestCase):
    def test_cancelled_error_is_not_retried(self) -> None:
        attempts = {"count": 0}

        def _run():
            attempts["count"] += 1
            raise JobCancelledError("cancelled")

        with self.assertRaises(JobCancelledError):
            execute_with_retry(_run, attempts=3, delay_seconds=0.0)

        self.assertEqual(attempts["count"], 1)

    def test_retryable_error_is_retried(self) -> None:
        attempts = {"count": 0}

        def _run():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("transient")
            return "ok"

        result = execute_with_retry(_run, attempts=3, delay_seconds=0.0)

        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 2)

    def test_backoff_is_exponential(self) -> None:
        attempts = {"count": 0}

        def _run():
            attempts["count"] += 1
            raise RuntimeError("transient")

        with patch("core.retry.time.sleep") as sleep_mock:
            with self.assertRaises(RuntimeError):
                execute_with_retry(_run, attempts=3, delay_seconds=1.0)

        self.assertEqual(attempts["count"], 3)
        self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [1.0, 2.0])

    def test_attempts_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            execute_with_retry(lambda: "ok", attempts=0, delay_seconds=0.0)
