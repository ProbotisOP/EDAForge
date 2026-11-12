"""Deterministic random streams.

Every random stream is derived from the run's root seed and a tuple of stable keys (analyzer
name, hypothesis ID, purpose). A stream therefore does not depend on execution order, which
keeps parallel and serial execution byte-identical (gate 5).
"""

from __future__ import annotations

import hashlib

import numpy as np

from edaforge.canonical import canonical_bytes

__all__ = ["derive_seed", "make_rng"]

_SEED_MASK = (1 << 63) - 1


def derive_seed(root_seed: int, *keys: str | int) -> int:
    """A 63-bit seed derived from ``root_seed`` and ``keys`` by SHA-256."""
    digest = hashlib.sha256(canonical_bytes([root_seed, list(keys)])).digest()
    return int.from_bytes(digest[:8], "little") & _SEED_MASK


def make_rng(root_seed: int, *keys: str | int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(derive_seed(root_seed, *keys)))
