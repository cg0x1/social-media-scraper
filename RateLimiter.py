import random
import time

class RateLimiter:
    def __init__(self, *, min_interval_s: float, success_jitter_s: float = 0.35):
        self.min_interval_s = float(min_interval_s)
        self.success_jitter_s = float(success_jitter_s)
        self._next_allowed = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self._next_allowed:
            time.sleep(self._next_allowed - now)

        # ✅ add tiny jitter to avoid perfect periodicity
        jitter = random.uniform(0.0, self.success_jitter_s)
        self._next_allowed = time.monotonic() + self.min_interval_s + jitter
