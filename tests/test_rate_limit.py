from __future__ import annotations

import unittest
from unittest.mock import patch

from api.middleware.rate_limit import InMemoryRateLimiter


class InMemoryRateLimiterTests(unittest.TestCase):
    def test_allows_under_limit(self) -> None:
        limiter = InMemoryRateLimiter(requests_per_minute=10)

        results = [limiter.is_allowed("client-a") for _ in range(5)]

        self.assertEqual(results, [True, True, True, True, True])

    def test_blocks_over_limit(self) -> None:
        limiter = InMemoryRateLimiter(requests_per_minute=10)

        results = [limiter.is_allowed("client-a") for _ in range(11)]

        self.assertTrue(all(results[:10]))
        self.assertFalse(results[10])

    def test_window_resets_after_60s(self) -> None:
        limiter = InMemoryRateLimiter(requests_per_minute=10)

        with patch("api.middleware.rate_limit.time.time") as mocked_time:
            mocked_time.return_value = 1000.0
            first_window = [limiter.is_allowed("client-a") for _ in range(10)]
            mocked_time.return_value = 1061.0
            second_window = [limiter.is_allowed("client-a") for _ in range(10)]

        self.assertTrue(all(first_window))
        self.assertTrue(all(second_window))

    def test_zero_limit_disables_rate_limiting(self) -> None:
        limiter = InMemoryRateLimiter(requests_per_minute=0)

        results = [limiter.is_allowed("client-a") for _ in range(100)]

        self.assertTrue(all(results))


if __name__ == "__main__":
    unittest.main()
