from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded jittered exponential backoff settings for transient operations."""

    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.initial_delay < 0:
            raise ValueError("initial_delay must be >= 0")
        if self.max_delay < 0:
            raise ValueError("max_delay must be >= 0")
        if self.multiplier < 1:
            raise ValueError("multiplier must be >= 1")
        if self.jitter < 0 or self.jitter > 1:
            raise ValueError("jitter must be between 0 and 1")

    def delay_for_attempt(
        self,
        failed_attempt: int,
        *,
        override_delay: float | None = None,
        apply_jitter: bool = True,
        random_fraction: float | None = None,
    ) -> float:
        """Return sleep seconds after a failed 1-based attempt number."""
        if failed_attempt < 1:
            raise ValueError("failed_attempt must be >= 1")

        if override_delay is None:
            delay = self.initial_delay * (self.multiplier ** (failed_attempt - 1))
        else:
            delay = override_delay

        delay = min(max(0.0, delay), self.max_delay)
        if not apply_jitter or self.jitter == 0 or delay == 0:
            return delay

        fraction = random.random() if random_fraction is None else random_fraction
        fraction = min(max(0.0, fraction), 1.0)
        jitter_delta = delay * self.jitter * ((fraction * 2.0) - 1.0)
        return min(max(0.0, delay + jitter_delta), self.max_delay)


def sleep_before_retry(
    policy: RetryPolicy,
    failed_attempt: int,
    *,
    override_delay: float | None = None,
    apply_jitter: bool = True,
    sleeper: Callable[[float], object] | None = None,
) -> float:
    """Sleep according to policy and return the delay that was used."""
    delay = policy.delay_for_attempt(
        failed_attempt,
        override_delay=override_delay,
        apply_jitter=apply_jitter,
    )
    if delay > 0:
        (sleeper or time.sleep)(delay)
    return delay
