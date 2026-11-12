"""Runtime services: events, cache and artifact store."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from edaforge.runtime.cache import ContentCache
from edaforge.runtime.clock import FixedClock
from edaforge.runtime.events import EventBus
from edaforge.runtime.rng import derive_seed, make_rng
from edaforge.store import ArtifactStore


def test_events_are_sequenced_streamed_and_isolated_from_bad_handlers() -> None:
    bus = EventBus("R-1", FixedClock())
    seen: list[str] = []
    bus.subscribe(lambda e: seen.append(e.kind))

    def broken(_: object) -> None:
        raise RuntimeError("subscriber bug")

    bus.subscribe(broken)
    stream = bus.open_stream(timeout=5)
    received: list[str] = []
    thread = threading.Thread(target=lambda: received.extend(e.kind for e in stream))
    thread.start()
    bus.emit("run_started")
    bus.emit("finding", "f", data={"id": "F-000001"})
    bus.emit("run_finished")
    thread.join(timeout=5)
    assert received == ["run_started", "finding", "run_finished"]
    assert seen == received
    assert [e.seq for e in bus.history()] == [1, 2, 3]
    assert bus.handler_errors
    assert "subscriber bug" in bus.handler_errors[0]
    assert all("wall_time" not in e for e in bus.transcript())


def test_late_streams_replay_history() -> None:
    bus = EventBus("R-1", FixedClock())
    bus.emit("run_started")
    bus.emit("run_finished")
    assert [e.kind for e in bus.open_stream(timeout=1)] == ["run_started", "run_finished"]


def test_cache_round_trip_and_corruption(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = ContentCache.key("unit", data="abc", version="1")
    assert key == ContentCache.key("unit", version="1", data="abc")
    assert cache.get_json(key) is None
    cache.put_json(key, {"x": [1, 2.5]})
    assert cache.get_json(key) == {"x": [1, 2.5]}
    stored = tmp_path / key[:2] / key[2:]
    stored.write_bytes(stored.read_bytes().replace(b"2.5", b"9.9"))
    assert cache.get_json(key) is None  # checksum mismatch: a miss, and the entry is dropped
    assert not stored.exists()
    with pytest.raises(ValueError, match="invalid cache key"):
        cache.get_bytes("../../etc/passwd")


def test_artifact_store_is_content_addressed(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    digest = store.put(b"hello")
    assert store.put(b"hello") == digest
    assert store.get(digest) == b"hello"
    (tmp_path / digest[:2] / digest[2:]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="corrupted"):
        store.get(digest)


def test_seed_derivation_is_order_independent_and_distinct() -> None:
    assert derive_seed(1, "a", "b") == derive_seed(1, "a", "b")
    assert derive_seed(1, "a", "b") != derive_seed(1, "b", "a")
    assert derive_seed(1, "a") != derive_seed(2, "a")
    assert make_rng(5, "x").random() == make_rng(5, "x").random()


def test_fixed_clock_requires_timezone() -> None:
    from datetime import datetime

    with pytest.raises(ValueError, match="timezone"):
        FixedClock(datetime(2026, 1, 1))  # noqa: DTZ001
