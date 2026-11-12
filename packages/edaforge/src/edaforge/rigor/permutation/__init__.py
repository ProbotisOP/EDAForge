"""Permutation p-values with sequential Monte Carlo stopping (Besag & Clifford, 1991).

Null statistics are drawn until either ``h`` of them are at least as extreme as the observed
statistic, or ``n_max - 1`` draws have been made. The p-value is

* ``h / l`` if the h-th exceedance occurred at draw ``l``; otherwise
* ``(g + 1) / n_max`` with ``g < h`` exceedances after ``n_max - 1`` draws.

Both cases give a valid p-value (``P(p <= alpha) <= alpha`` under the null). The smallest
attainable p-value is ``1 / n_max``. Ties count as exceedances (conservative), using a relative
tolerance to absorb floating-point noise. Draws are generated in fixed-size batches, and the
result is identical to a draw-by-draw procedure on the same stream.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

__all__ = ["BatchDraw", "PermutationOutcome", "besag_clifford_pvalue"]

BatchDraw = Callable[[np.random.Generator, int], NDArray[np.float64]]
"""``draw(rng, size)`` returns ``size`` statistics computed on independent null resamples."""

_RTOL = 1e-12


@dataclass(frozen=True)
class PermutationOutcome:
    p_value: float
    n_draws: int
    n_exceed: int
    stopped_early: bool
    h: int
    n_max: int


def besag_clifford_pvalue(
    observed: float,
    draw: BatchDraw,
    rng: np.random.Generator,
    *,
    h: int = 10,
    n_max: int = 1000,
    batch_size: int = 64,
) -> PermutationOutcome:
    """Sequential Monte Carlo p-value for "larger statistics are more extreme"."""
    if h < 1 or n_max < 2 or h >= n_max:
        msg = "require h >= 1, n_max >= 2 and h < n_max"
        raise ValueError(msg)
    if not np.isfinite(observed):
        msg = "observed statistic must be finite"
        raise ValueError(msg)
    threshold = observed - _RTOL * max(1.0, abs(observed))
    budget = n_max - 1
    drawn = 0
    exceed = 0
    while drawn < budget:
        size = min(batch_size, budget - drawn)
        stats = np.asarray(draw(rng, size), dtype=np.float64)
        if stats.shape != (size,):
            msg = f"draw returned shape {stats.shape}, expected ({size},)"
            raise ValueError(msg)
        if not np.all(np.isfinite(stats)):
            msg = "null statistics must be finite"
            raise ValueError(msg)
        hits = np.cumsum(stats >= threshold) + exceed
        reached = np.nonzero(hits >= h)[0]
        if reached.size:
            stop_at = drawn + int(reached[0]) + 1
            return PermutationOutcome(
                p_value=h / stop_at,
                n_draws=stop_at,
                n_exceed=h,
                stopped_early=True,
                h=h,
                n_max=n_max,
            )
        exceed = int(hits[-1])
        drawn += size
    return PermutationOutcome(
        p_value=(exceed + 1) / n_max,
        n_draws=drawn,
        n_exceed=exceed,
        stopped_early=False,
        h=h,
        n_max=n_max,
    )
