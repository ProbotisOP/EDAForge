"""Bootstrap confidence intervals (section 8.3).

:func:`bca_bounds` implements the bias-corrected and accelerated interval of Efron (1987) with
the same conventions as ``scipy.stats.bootstrap``: the bias correction uses the mid-rank of the
estimate among the replicates, and the acceleration is computed from per-sample jackknife
values. Given the same replicates it returns the same endpoints, which is what the
reference-equivalence test checks.

For samples larger than ``jackknife_max`` the acceleration is estimated with a grouped
(delete-a-group) jackknife over ``jackknife_groups`` random groups, a standard approximation
that keeps the cost linear in n. The method used is recorded on the result.

Resampling is stratified by sample: each sample is resampled independently, as for a
two-sample comparison. Cluster and block bootstraps arrive with the Phase 3 kernel.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtr, ndtri

__all__ = [
    "BatchStatistic",
    "BootstrapInterval",
    "Statistic",
    "bca_bounds",
    "bootstrap_interval",
    "jackknife_values",
]

Statistic = Callable[..., float]
"""``statistic(*samples) -> float`` on one-dimensional samples."""

BatchStatistic = Callable[..., NDArray[np.float64]]
"""``batch(*samples) -> (B,)`` where sample ``j`` has shape ``(B, n_j)``."""

_MAX_BATCH_ELEMENTS = 2_000_000


@dataclass(frozen=True)
class BootstrapInterval:
    estimate: float
    low: float
    high: float
    level: float
    method: Literal["bca", "percentile", "degenerate"]
    n_resamples: int
    z0: float | None = None
    acceleration: float | None = None
    jackknife: Literal["leave_one_out", "grouped"] | None = None
    note: str = ""


def bca_bounds(
    theta_hat: float,
    replicates: NDArray[np.float64],
    jackknife: Sequence[NDArray[np.float64]],
    level: float,
) -> tuple[float, float, float, float]:
    """BCa endpoints ``(low, high, z0, a)`` from replicates and per-sample jackknife values."""
    b = replicates.size
    below = float(np.count_nonzero(replicates < theta_hat))
    at_or_below = float(np.count_nonzero(replicates <= theta_hat))
    z0 = float(ndtri((below + at_or_below) / (2.0 * b)))
    num = 0.0
    den = 0.0
    for values in jackknife:
        n = values.size
        u = (n - 1) * (values.mean() - values)
        num += float(np.sum(u**3)) / n**3
        den += float(np.sum(u**2)) / n**2
    accel = num / (6.0 * den**1.5) if den > 0.0 else 0.0
    alpha = (1.0 - level) / 2.0
    z_lo = float(ndtri(alpha))
    z_hi = -z_lo
    alpha_1 = float(ndtr(z0 + (z0 + z_lo) / (1.0 - accel * (z0 + z_lo))))
    alpha_2 = float(ndtr(z0 + (z0 + z_hi) / (1.0 - accel * (z0 + z_hi))))
    low = float(np.percentile(replicates, alpha_1 * 100.0))
    high = float(np.percentile(replicates, alpha_2 * 100.0))
    return low, high, z0, accel


def _resample_replicates(
    samples: Sequence[NDArray[np.float64]],
    statistic: Statistic,
    batch_statistic: BatchStatistic | None,
    rng: np.random.Generator,
    n_resamples: int,
) -> NDArray[np.float64]:
    out = np.empty(n_resamples, dtype=np.float64)
    width = max(sum(s.size for s in samples), 1)
    chunk = max(1, min(n_resamples, _MAX_BATCH_ELEMENTS // width))
    done = 0
    while done < n_resamples:
        size = min(chunk, n_resamples - done)
        resampled = [s[rng.integers(0, s.size, size=(size, s.size))] for s in samples]
        if batch_statistic is not None:
            values = np.asarray(batch_statistic(*resampled), dtype=np.float64)
        else:
            values = np.array(
                [statistic(*[r[i] for r in resampled]) for i in range(size)], dtype=np.float64
            )
        out[done : done + size] = values
        done += size
    return out


def jackknife_values(
    samples: Sequence[NDArray[np.float64]],
    statistic: Statistic,
    rng: np.random.Generator,
    *,
    jackknife_max: int = 5000,
    jackknife_groups: int = 200,
) -> tuple[list[NDArray[np.float64]], Literal["leave_one_out", "grouped"]]:
    """Per-sample jackknife statistics (leave-one-out, or grouped for large samples)."""
    kind: Literal["leave_one_out", "grouped"] = "leave_one_out"
    result: list[NDArray[np.float64]] = []
    for j, sample in enumerate(samples):
        n = sample.size
        if n <= jackknife_max:
            blocks = [np.array([i]) for i in range(n)]
        else:
            kind = "grouped"
            perm = rng.permutation(n)
            blocks = [b for b in np.array_split(perm, jackknife_groups) if b.size]
        values = np.empty(len(blocks), dtype=np.float64)
        mask = np.ones(n, dtype=np.bool_)
        for g, block in enumerate(blocks):
            mask[block] = False
            args = [s if k != j else sample[mask] for k, s in enumerate(samples)]
            values[g] = statistic(*args)
            mask[block] = True
        result.append(values)
    return result, kind


def bootstrap_interval(
    samples: Sequence[NDArray[np.float64]],
    statistic: Statistic,
    rng: np.random.Generator,
    *,
    n_resamples: int = 2000,
    level: float = 0.95,
    method: Literal["bca", "percentile"] = "bca",
    batch_statistic: BatchStatistic | None = None,
    jackknife_max: int = 5000,
    jackknife_groups: int = 200,
) -> BootstrapInterval:
    """Bootstrap interval for ``statistic`` with independent resampling of each sample."""
    if not 0.0 < level < 1.0:
        msg = "level must lie in (0, 1)"
        raise ValueError(msg)
    arrays = [np.asarray(s, dtype=np.float64) for s in samples]
    if any(a.ndim != 1 or a.size < 2 for a in arrays):
        msg = "each sample must be one-dimensional with at least two observations"
        raise ValueError(msg)
    theta_hat = float(statistic(*arrays))
    replicates = _resample_replicates(arrays, statistic, batch_statistic, rng, n_resamples)
    if not np.all(np.isfinite(replicates)):
        msg = "bootstrap statistic produced non-finite values"
        raise ValueError(msg)
    if float(np.ptp(replicates)) == 0.0:
        return BootstrapInterval(
            estimate=theta_hat,
            low=theta_hat,
            high=theta_hat,
            level=level,
            method="degenerate",
            n_resamples=n_resamples,
            note="all bootstrap replicates are identical",
        )
    alpha = (1.0 - level) / 2.0
    if method == "bca":
        below = np.count_nonzero(replicates < theta_hat)
        at_or_below = np.count_nonzero(replicates <= theta_hat)
        if at_or_below == 0 or below == n_resamples:
            note = "estimate lies outside the bootstrap distribution; percentile interval used"
        else:
            jack, kind = jackknife_values(
                arrays,
                statistic,
                rng,
                jackknife_max=jackknife_max,
                jackknife_groups=jackknife_groups,
            )
            low, high, z0, accel = bca_bounds(theta_hat, replicates, jack, level)
            return BootstrapInterval(
                estimate=theta_hat,
                low=low,
                high=high,
                level=level,
                method="bca",
                n_resamples=n_resamples,
                z0=z0,
                acceleration=accel,
                jackknife=kind,
            )
    else:
        note = ""
    return BootstrapInterval(
        estimate=theta_hat,
        low=float(np.percentile(replicates, 100.0 * alpha)),
        high=float(np.percentile(replicates, 100.0 * (1.0 - alpha))),
        level=level,
        method="percentile",
        n_resamples=n_resamples,
        note=note,
    )
