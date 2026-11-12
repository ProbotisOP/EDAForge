"""Batch multiplicity control (section 8.2).

* :func:`bh_adjust`: Benjamini & Hochberg (1995) step-up adjusted p-values (q-values).
* :func:`by_adjust`: Benjamini & Yekutieli (2001), valid under arbitrary dependence.
* :func:`ebh_reject`: e-BH (Wang & Ramdas, 2022), valid for e-values under arbitrary dependence.

Hierarchical control (p-filter, Yekutieli 2008) is built on these in the Phase 3 kernel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import ArrayLike, NDArray

__all__ = ["bh_adjust", "bh_reject", "by_adjust", "ebh_reject"]


def _as_pvalues(p_values: ArrayLike) -> NDArray[np.float64]:
    p = np.asarray(p_values, dtype=np.float64)
    if p.ndim != 1:
        msg = "p-values must be a one-dimensional array"
        raise ValueError(msg)
    if not np.all(np.isfinite(p)) or np.any(p < 0.0) or np.any(p > 1.0):
        msg = "p-values must be finite and lie in [0, 1]"
        raise ValueError(msg)
    return p


def _step_up(p: NDArray[np.float64], scale: float) -> NDArray[np.float64]:
    m = p.size
    if m == 0:
        return p.copy()
    order = np.argsort(p, kind="mergesort")
    ranks = np.arange(1, m + 1, dtype=np.float64)
    scaled = p[order] * (m * scale) / ranks
    adjusted_sorted = np.minimum.accumulate(scaled[::-1])[::-1]
    adjusted = np.empty(m, dtype=np.float64)
    adjusted[order] = np.minimum(adjusted_sorted, 1.0)
    return adjusted


def bh_adjust(p_values: ArrayLike) -> NDArray[np.float64]:
    """Benjamini-Hochberg adjusted p-values: ``q_(i) = min_{j>=i} m p_(j) / j``."""
    return _step_up(_as_pvalues(p_values), 1.0)


def by_adjust(p_values: ArrayLike) -> NDArray[np.float64]:
    """Benjamini-Yekutieli adjusted p-values (BH scaled by the harmonic number of m)."""
    p = _as_pvalues(p_values)
    if p.size == 0:
        return p.copy()
    harmonic = float(np.sum(1.0 / np.arange(1, p.size + 1)))
    return _step_up(p, harmonic)


def bh_reject(p_values: ArrayLike, q: float) -> NDArray[np.bool_]:
    """Rejections of the BH procedure at level ``q``.

    The k* smallest p-values are rejected, with k* = max{k : p_(k) m <= q k}.

    Equivalent to ``bh_adjust(p) <= q`` in exact arithmetic. The step-up rule is applied as
    written (a multiplication on both sides) so that a p-value exactly on the boundary, such as
    p = q with k = m, is not lost to rounding in the division of the adjusted p-value.
    """
    if not 0.0 < q < 1.0:
        msg = "q must lie in (0, 1)"
        raise ValueError(msg)
    p = np.asarray(p_values, dtype=np.float64)
    adjusted = bh_adjust(p)  # validates the input
    m = p.size
    reject = np.zeros(m, dtype=np.bool_)
    if m == 0:
        return reject
    order = np.argsort(p, kind="mergesort")
    ks = np.arange(1, m + 1, dtype=np.float64)
    ok = np.nonzero(p[order] * m <= q * ks)[0]
    if ok.size:
        reject[order[: ok[-1] + 1]] = True
    return reject | (adjusted <= q)


def ebh_reject(e_values: ArrayLike, alpha: float) -> NDArray[np.bool_]:
    """e-BH: reject the k* largest e-values, ``k* = max{k : e_(k) >= m / (alpha k)}``."""
    e = np.asarray(e_values, dtype=np.float64)
    if e.ndim != 1 or np.any(e < 0.0) or not np.all(np.isfinite(e)):
        msg = "e-values must be a finite, non-negative one-dimensional array"
        raise ValueError(msg)
    if not 0.0 < alpha < 1.0:
        msg = "alpha must lie in (0, 1)"
        raise ValueError(msg)
    m = e.size
    reject = np.zeros(m, dtype=np.bool_)
    if m == 0:
        return reject
    order = np.argsort(-e, kind="mergesort")
    ks = np.arange(1, m + 1, dtype=np.float64)
    passing = np.nonzero(e[order] >= m / (alpha * ks))[0]
    if passing.size:
        k_star = int(passing.max()) + 1
        reject[order[:k_star]] = True
    return reject
