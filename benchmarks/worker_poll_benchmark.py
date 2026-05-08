from __future__ import annotations

import argparse
import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PollStrategy:
    name: str
    poll_min_seconds: float
    poll_max_seconds: float
    backoff_factor: float

    def next_interval(self, current: float, activity: bool) -> float:
        if activity:
            return self.poll_min_seconds
        return min(self.poll_max_seconds, current * self.backoff_factor)


def simulate_strategy(strategy: PollStrategy, *, idle_seconds: float) -> dict[str, float]:
    elapsed = 0.0
    polls = 0
    current = max(0.01, strategy.poll_min_seconds)
    while elapsed < idle_seconds:
        polls += 1
        elapsed += current
        current = strategy.next_interval(current, activity=False)
    avg_interval = elapsed / polls if polls else 0.0
    return {
        "idle_seconds": float(idle_seconds),
        "idle_polls": float(polls),
        "avg_idle_interval_seconds": avg_interval,
        "worst_case_new_job_latency_seconds": current,
        "latency_after_recent_activity_seconds": strategy.poll_min_seconds,
    }


def run_poll_benchmark(*, idle_seconds: float = 300.0) -> dict[str, dict[str, float]]:
    strategies = [
        PollStrategy("fixed_1_0", poll_min_seconds=1.0, poll_max_seconds=1.0, backoff_factor=1.0),
        PollStrategy("fixed_0_5", poll_min_seconds=0.5, poll_max_seconds=0.5, backoff_factor=1.0),
        PollStrategy("adaptive_0_2_to_1_0", poll_min_seconds=0.2, poll_max_seconds=1.0, backoff_factor=1.5),
    ]
    return {
        strategy.name: simulate_strategy(strategy, idle_seconds=idle_seconds)
        for strategy in strategies
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare worker poll strategies under idle periods.")
    parser.add_argument("--idle-seconds", type=float, default=300.0)
    args = parser.parse_args()
    print(json.dumps(run_poll_benchmark(idle_seconds=args.idle_seconds), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
