"""Rate-limit cooldown: after a backend signals it's being rate limited
(HTTP 429), skip calling it entirely for a configurable duration instead
of continuing to hammer it uselessly until its quota resets. Not specific
to any one backend -- any backend can hold one of these and check it at
the top of ``resolve()``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

DEFAULT_COOLDOWN_SECONDS = 24 * 60 * 60  # 24 hours


@dataclass
class RateLimitCooldown:
    duration_seconds: float = DEFAULT_COOLDOWN_SECONDS
    _until: float | None = field(default=None, init=False, repr=False, compare=False)

    def trigger(self) -> None:
        self._until = time.monotonic() + self.duration_seconds

    def active(self) -> bool:
        return self._until is not None and time.monotonic() < self._until

    def remaining_seconds(self) -> float:
        if self._until is None:
            return 0.0
        return max(0.0, self._until - time.monotonic())
