"""Synthetic handlers used only by load-test workers."""

import random
import time
from typing import Any, Dict


class SyntheticHandler:
    """Simulate configurable I/O latency, jitter, and failures."""

    def __init__(
        self,
        delay_ms: float = 0,
        jitter_ms: float = 0,
        failure_rate: float = 0,
    ) -> None:
        if delay_ms < 0:
            raise ValueError("delay_ms must be non-negative")
        if jitter_ms < 0:
            raise ValueError("jitter_ms must be non-negative")
        if not 0 <= failure_rate <= 1:
            raise ValueError("failure_rate must be between 0 and 1")

        self.delay_ms = delay_ms
        self.jitter_ms = jitter_ms
        self.failure_rate = failure_rate

    def __call__(self, payload: Dict[str, Any]) -> None:
        """Handle one synthetic event without producing log I/O."""
        del payload
        delay_ms = self.delay_ms
        if self.jitter_ms:
            delay_ms += random.uniform(0, self.jitter_ms)
        if delay_ms:
            time.sleep(delay_ms / 1000)
        if self.failure_rate and random.random() < self.failure_rate:
            raise RuntimeError("Synthetic load-test failure")
