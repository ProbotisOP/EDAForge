"""Canonical JSON and content hashing.

Gate 5 (section 16.3) requires that identical inputs, seeds and versions produce byte-identical
findings JSON. Every persisted engine artifact therefore goes through :func:`canonical_json`:

* object keys are sorted;
* floats are rounded to ``FLOAT_SIGNIFICANT_DIGITS`` significant digits, which absorbs
  last-bit noise from reduction order, and ``-0.0`` is normalized to ``0.0``;
* NaN and infinities are rejected (strict JSON); contracts forbid them anyway;
* datetimes must be timezone-aware and are written in UTC.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from pydantic import BaseModel

if TYPE_CHECKING:
    import polars as pl
    from numpy.typing import NDArray

FLOAT_SIGNIFICANT_DIGITS = 12

__all__ = [
    "FLOAT_SIGNIFICANT_DIGITS",
    "canonical_bytes",
    "canonical_json",
    "content_hash",
    "hash_array",
    "hash_file",
    "hash_frame",
    "normalize_json",
    "round_sig",
    "sha256_hex",
    "short_hash",
]


def round_sig(value: float, sig: int = FLOAT_SIGNIFICANT_DIGITS) -> float:
    """Round ``value`` to ``sig`` significant digits; normalize ``-0.0`` to ``0.0``."""
    if not math.isfinite(value):
        msg = f"non-finite float {value!r} cannot be serialized canonically"
        raise ValueError(msg)
    if value == 0.0:
        return 0.0
    return float(f"{value:.{sig}g}")


def normalize_json(value: object, sig: int = FLOAT_SIGNIFICANT_DIGITS) -> object:
    """Convert ``value`` into plain JSON types with canonical floats."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return round_sig(value, sig)
    if isinstance(value, Enum):
        return normalize_json(value.value, sig)
    if isinstance(value, np.generic):
        scalar: object = cast("np.generic[Any]", value).item()
        return normalize_json(scalar, sig)
    if isinstance(value, np.ndarray):
        items_np: list[object] = cast("NDArray[Any]", value).tolist()
        return [normalize_json(v, sig) for v in items_np]
    if isinstance(value, BaseModel):
        return normalize_json(value.model_dump(mode="json"), sig)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            msg = "naive datetimes are not allowed in canonical JSON; use timezone-aware UTC"
            raise ValueError(msg)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, Mapping):
        out: dict[str, object] = {}
        mapping = cast("Mapping[object, object]", value)
        for key, item in mapping.items():
            if not isinstance(key, str):
                msg = f"canonical JSON requires string keys, got {type(key).__name__}"
                raise TypeError(msg)
            out[key] = normalize_json(item, sig)
        return out
    if isinstance(value, list | tuple | set | frozenset):
        items: list[object] = list(cast("list[object]", value))
        if isinstance(value, set | frozenset):
            normalized = [normalize_json(v, sig) for v in items]
            return sorted(normalized, key=lambda v: json.dumps(v, sort_keys=True))
        return [normalize_json(v, sig) for v in items]
    msg = f"type {type(value).__name__} is not canonically serializable"
    raise TypeError(msg)


def canonical_json(
    value: object, *, indent: int | None = None, sig: int = FLOAT_SIGNIFICANT_DIGITS
) -> str:
    """Serialize ``value`` deterministically (sorted keys, canonical floats, strict JSON)."""
    normalized = normalize_json(value, sig)
    if indent is None:
        return json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    return (
        json.dumps(normalized, sort_keys=True, indent=indent, ensure_ascii=False, allow_nan=False)
        + "\n"
    )


def canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(value: object) -> str:
    """SHA-256 of the canonical JSON encoding of ``value``."""
    return sha256_hex(canonical_bytes(value))


def short_hash(digest: str, length: int = 16) -> str:
    return digest[:length]


def hash_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file's raw bytes, streamed."""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def hash_array(array: NDArray[Any]) -> str:
    """SHA-256 over dtype, shape and little-endian C-ordered bytes of a numeric array."""
    if array.dtype.kind in {"O", "U", "S", "V"}:
        msg = f"hash_array supports numeric and boolean dtypes only, got {array.dtype}"
        raise TypeError(msg)
    contiguous = np.ascontiguousarray(array)
    little = contiguous.astype(contiguous.dtype.newbyteorder("<"), copy=False)
    h = hashlib.sha256()
    h.update(f"{little.dtype.str}|{list(little.shape)}|".encode())
    h.update(little.tobytes(order="C"))
    return h.hexdigest()


def hash_frame(frame: pl.DataFrame) -> str:
    """Deterministic content hash of a Polars frame.

    The hash covers column order, names, logical dtypes, null masks and values. It does not
    depend on Polars' internal hashing, which is not stable across versions.
    """
    import polars as pl

    h = hashlib.sha256()
    h.update(f"rows={frame.height}|cols={frame.width}|".encode())
    for series in frame.get_columns():
        h.update(f"{series.name}\x1f{series.dtype}\x1e".encode())
        nulls = series.is_null().to_numpy().astype(np.uint8)
        h.update(nulls.tobytes())
        dtype = series.dtype
        if dtype.is_numeric():
            filled = series.fill_null(0)
            h.update(hash_array(filled.to_numpy()).encode())
        elif dtype == pl.Boolean:
            h.update(hash_array(series.fill_null(value=False).cast(pl.UInt8).to_numpy()).encode())
        elif dtype.is_temporal():
            physical = series.to_physical().fill_null(0)
            h.update(hash_array(physical.to_numpy()).encode())
        else:
            for item in series.cast(pl.String).fill_null("").to_list():
                text = str(item).encode("utf-8")
                h.update(len(text).to_bytes(8, "little"))
                h.update(text)
    return h.hexdigest()
