"""Injectable clocks.

Wall-clock time appears only in audit fields (ledger timestamps, manifest ``created_at``), never
in findings JSON or run IDs, so determinism does not depend on the clock. Tests use
:class:`FixedClock`.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Protocol

__all__ = ["Clock", "FixedClock", "SystemClock"]


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock that starts at ``start`` and advances by ``step`` on every call."""

    def __init__(
        self,
        start: datetime | None = None,
        step: timedelta = timedelta(microseconds=1),
    ) -> None:
        base = start if start is not None else datetime(2026, 1, 1, tzinfo=UTC)
        if base.tzinfo is None:
            msg = "FixedClock requires a timezone-aware start time"
            raise ValueError(msg)
        self._current = base
        self._step = step
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            value = self._current
            self._current = value + self._step
            return value
