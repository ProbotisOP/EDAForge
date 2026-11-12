"""The event bus: progress, candidates, findings and warnings, streamed as they happen.

Events carry a per-run sequence number. ``wall_time`` is informational only and is excluded
from deterministic transcripts (:meth:`EventBus.transcript`).
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Literal

from pydantic import JsonValue

from edaforge.models import Contract
from edaforge.runtime.clock import Clock, SystemClock

__all__ = ["Event", "EventBus", "EventKind", "EventStream"]

EventKind = Literal["run_started", "progress", "candidate", "finding", "warning", "run_finished"]


class Event(Contract):
    seq: int
    run_id: str
    kind: EventKind
    stage: str | None = None
    message: str = ""
    data: dict[str, JsonValue] = {}
    wall_time: datetime | None = None


Handler = Callable[[Event], None]


class EventStream:
    """A blocking iterator over events, ending after ``run_finished``."""

    def __init__(self, bus: EventBus, timeout: float | None) -> None:
        self._bus = bus
        self._queue: queue.Queue[Event] = queue.Queue()
        self._timeout = timeout

    def _push(self, event: Event) -> None:
        self._queue.put(event)

    def __iter__(self) -> Iterator[Event]:
        while True:
            try:
                event = self._queue.get(timeout=self._timeout)
            except queue.Empty:
                return
            yield event
            if event.kind == "run_finished":
                self._bus.close_stream(self)
                return


class EventBus:
    def __init__(self, run_id: str, clock: Clock | None = None) -> None:
        self.run_id = run_id
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._lock = threading.Lock()
        self._seq = 0
        self._history: list[Event] = []
        self._handlers: list[Handler] = []
        self._streams: list[EventStream] = []
        self.handler_errors: list[str] = []

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        with self._lock:
            self._handlers.append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._handlers:
                    self._handlers.remove(handler)

        return unsubscribe

    def open_stream(self, timeout: float | None = None) -> EventStream:
        stream = EventStream(self, timeout)
        with self._lock:
            self._streams.append(stream)
            for event in self._history:
                stream._push(event)  # pyright: ignore[reportPrivateUsage]
        return stream

    def close_stream(self, stream: EventStream) -> None:
        with self._lock:
            if stream in self._streams:
                self._streams.remove(stream)

    def emit(
        self,
        kind: EventKind,
        message: str = "",
        *,
        stage: str | None = None,
        data: dict[str, JsonValue] | None = None,
    ) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(
                seq=self._seq,
                run_id=self.run_id,
                kind=kind,
                stage=stage,
                message=message,
                data=data or {},
                wall_time=self._clock.now(),
            )
            self._history.append(event)
            handlers = list(self._handlers)
            streams = list(self._streams)
        for stream in streams:
            stream._push(event)  # pyright: ignore[reportPrivateUsage]
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 - a broken subscriber must not break a run
                self.handler_errors.append(f"{type(exc).__name__}: {exc}")
        return event

    def history(self) -> tuple[Event, ...]:
        with self._lock:
            return tuple(self._history)

    def transcript(self) -> list[dict[str, JsonValue]]:
        """Events without wall-clock times, for deterministic comparison and export."""
        return [e.model_dump(mode="json", exclude={"wall_time"}) for e in self.history()]
