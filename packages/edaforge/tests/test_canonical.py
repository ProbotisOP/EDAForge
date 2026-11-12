"""Canonical JSON and hashing: the basis of the determinism gate (gate 5)."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from edaforge.canonical import canonical_json, content_hash, hash_array, hash_frame, round_sig

json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53), max_value=2**53)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=20,
)


@given(json_values)
def test_canonical_json_is_idempotent(value: object) -> None:
    once = canonical_json(value)
    assert canonical_json(json.loads(once)) == once


@given(st.dictionaries(st.text(max_size=5), st.integers(), max_size=6))
def test_key_order_does_not_matter(mapping: dict[str, int]) -> None:
    reversed_mapping = dict(reversed(list(mapping.items())))
    assert canonical_json(mapping) == canonical_json(reversed_mapping)


def test_floats_are_rounded_and_negative_zero_normalized() -> None:
    assert canonical_json(0.1 + 0.2) == canonical_json(0.3)
    assert canonical_json(-0.0) == "0.0"
    assert round_sig(123456.789, 3) == 123000.0


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_floats_are_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json({"x": bad})


def test_naive_datetimes_are_rejected_and_aware_ones_are_utc() -> None:
    with pytest.raises(ValueError, match="naive"):
        canonical_json(datetime(2026, 1, 1))  # noqa: DTZ001 - the point of the test
    assert canonical_json(datetime(2026, 1, 1, tzinfo=UTC)) == '"2026-01-01T00:00:00Z"'


def test_numpy_values_serialize_like_python_values() -> None:
    assert canonical_json(np.float64(1.5)) == canonical_json(1.5)
    assert canonical_json(np.arange(3)) == "[0,1,2]"


def test_hash_array_depends_on_dtype_shape_and_values() -> None:
    a = np.arange(6, dtype=np.int64)
    assert hash_array(a) == hash_array(a.copy())
    assert hash_array(a) != hash_array(a.astype(np.int32))
    assert hash_array(a) != hash_array(a.reshape(2, 3))
    with pytest.raises(TypeError):
        hash_array(np.array(["a"], dtype=object))


def test_hash_frame_is_content_based() -> None:
    frame = pl.DataFrame({"x": [1.0, None, 3.0], "g": ["a", "b", None], "b": [True, False, None]})
    same = pl.DataFrame({"x": [1.0, None, 3.0], "g": ["a", "b", None], "b": [True, False, None]})
    assert hash_frame(frame) == hash_frame(same)
    assert hash_frame(frame) != hash_frame(frame.with_columns(pl.col("x").fill_null(0.0)))
    assert hash_frame(frame) != hash_frame(frame.select("g", "x", "b"))
    assert hash_frame(frame) != hash_frame(frame.rename({"x": "y"}))


def test_content_hash_is_stable() -> None:
    assert content_hash({"b": 1, "a": [1, 2]}) == content_hash({"a": [1, 2], "b": 1})
    assert len(content_hash({})) == 64
