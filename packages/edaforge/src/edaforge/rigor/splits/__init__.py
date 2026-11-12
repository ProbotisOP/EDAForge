"""Splitting and blinding (section 8.1).

* ``n >= holdout_min_n`` (2,000): a sealed holdout of ``confirmation_fraction`` (30%), stratified,
  group-aware (an entity never appears on both sides) and, for time-ordered data, split in time
  order with an embargo gap.
* ``cross_fit_min_n <= n < holdout_min_n`` (300 to 2,000): repeated random half-splits; on each
  split, candidates are selected on one half and tested on the other, and the per-split p-values
  are aggregated with the quantile rule of Meinshausen, Meier & Buhlmann (2009). A candidate
  that is not selected on a split receives p = 1 for that split.
* ``n < cross_fit_min_n`` (300): small-sample mode; no confirmation is possible and every finding
  is exploratory unless it was pre-registered.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from edaforge.canonical import hash_array, sha256_hex
from edaforge.models import SplitRecord

if TYPE_CHECKING:
    from edaforge.config import RigorConfig
    from edaforge.rigor.ledger import HypothesisLedger

__all__ = [
    "HoldoutPlan",
    "SealedHoldout",
    "SplitMode",
    "choose_mode",
    "half_splits",
    "holdout_plan",
    "mmb_adaptive_aggregate",
    "mmb_quantile_aggregate",
]

SplitMode = Literal["holdout", "cross_fit", "small_sample"]
IntArray = NDArray[np.int64]


def choose_mode(n: int, rigor: RigorConfig) -> SplitMode:
    if n >= rigor.holdout_min_n:
        return "holdout"
    if n >= rigor.cross_fit_min_n:
        return "cross_fit"
    return "small_sample"


@dataclass(frozen=True)
class HoldoutPlan:
    exploration: IntArray
    confirmation: IntArray
    embargo: IntArray
    strategy: str


def _labels(values: ArrayLike | None, n: int) -> NDArray[np.int64]:
    """Integer codes for arbitrary labels, in order of first sorted appearance."""
    if values is None:
        return np.zeros(n, dtype=np.int64)
    array = np.asarray(values)
    if array.shape != (n,):
        msg = f"label array has shape {array.shape}, expected ({n},)"
        raise ValueError(msg)
    _, codes = np.unique(array.astype(str), return_inverse=True)
    return codes.astype(np.int64)


def holdout_plan(
    n: int,
    fraction: float,
    rng: np.random.Generator,
    *,
    strata: ArrayLike | None = None,
    groups: ArrayLike | None = None,
    order: ArrayLike | None = None,
    embargo: int = 0,
) -> HoldoutPlan:
    """Indices of the exploration and sealed confirmation sides."""
    if not 0.0 < fraction < 1.0:
        msg = "fraction must lie in (0, 1)"
        raise ValueError(msg)
    if order is not None:
        ordering = np.argsort(np.asarray(order), kind="mergesort").astype(np.int64)
        n_conf = round(fraction * n)
        n_expl = n - n_conf - embargo
        if n_expl < 1 or n_conf < 1:
            msg = "time-ordered split leaves an empty side"
            raise ValueError(msg)
        return HoldoutPlan(
            exploration=np.sort(ordering[:n_expl]),
            confirmation=np.sort(ordering[n_expl + embargo :]),
            embargo=np.sort(ordering[n_expl : n_expl + embargo]),
            strategy=f"time-ordered, last {fraction:.0%} sealed, embargo {embargo} rows",
        )
    strata_codes = _labels(strata, n)
    confirmation: list[int] = []
    if groups is not None:
        group_codes = _labels(groups, n)
        n_groups = int(group_codes.max()) + 1
        sizes = np.bincount(group_codes, minlength=n_groups)
        # A group's stratum is its most frequent stratum (ties: smallest code).
        joint = np.zeros((n_groups, int(strata_codes.max()) + 1), dtype=np.int64)
        np.add.at(joint, (group_codes, strata_codes), 1)
        group_stratum = joint.argmax(axis=1)
        chosen: list[int] = []
        for stratum in range(joint.shape[1]):
            members = np.nonzero(group_stratum == stratum)[0]
            if members.size == 0:
                continue
            members = rng.permutation(members)
            target = fraction * float(sizes[members].sum())
            total = 0
            for g in members:
                size = int(sizes[g])
                if abs(total + size - target) <= abs(total - target):
                    chosen.append(int(g))
                    total += size
        mask = np.isin(group_codes, np.asarray(chosen, dtype=np.int64))
        confirmation = np.nonzero(mask)[0].tolist()
        strategy = f"group-aware, {fraction:.0%} of rows sealed by whole groups"
    else:
        for stratum in np.unique(strata_codes):
            members = rng.permutation(np.nonzero(strata_codes == stratum)[0])
            k = round(fraction * members.size)
            confirmation.extend(members[:k].tolist())
        strategy = f"stratified random, {fraction:.0%} sealed"
    conf = np.sort(np.asarray(confirmation, dtype=np.int64))
    expl = np.setdiff1d(np.arange(n, dtype=np.int64), conf, assume_unique=True)
    if conf.size == 0 or expl.size == 0:
        msg = "split leaves an empty side"
        raise ValueError(msg)
    return HoldoutPlan(
        exploration=expl,
        confirmation=conf,
        embargo=np.zeros(0, dtype=np.int64),
        strategy=strategy,
    )


class SealedHoldout:
    """A holdout whose confirmation side is sealed until the candidate list is frozen."""

    def __init__(self, plan: HoldoutPlan, data_hash: str) -> None:
        self._plan = plan
        self.seal_hash = sha256_hex(f"{data_hash}|{hash_array(plan.confirmation)}".encode())

    @property
    def exploration_indices(self) -> IntArray:
        return self._plan.exploration

    @property
    def n_confirmation(self) -> int:
        return int(self._plan.confirmation.size)

    def unseal(self, ledger: HypothesisLedger, *, reason: str) -> IntArray:
        """Return the sealed indices; access is logged and breaks blinding before the freeze."""
        ledger.note_sealed_access(reason)
        return self._plan.confirmation

    def record(self, n_total: int) -> SplitRecord:
        return SplitRecord(
            mode="holdout",
            n_total=n_total,
            n_exploration=int(self._plan.exploration.size),
            n_confirmation=int(self._plan.confirmation.size),
            n_embargo=int(self._plan.embargo.size),
            seal_hash=self.seal_hash,
            strategy=self._plan.strategy,
        )


def half_splits(
    n: int,
    n_splits: int,
    rng: np.random.Generator,
    *,
    strata: ArrayLike | None = None,
    groups: ArrayLike | None = None,
) -> list[tuple[IntArray, IntArray]]:
    """``n_splits`` random (selection, test) half-splits, stratified and group-aware."""
    splits: list[tuple[IntArray, IntArray]] = []
    for _ in range(n_splits):
        plan = holdout_plan(n, 0.5, rng, strata=strata, groups=groups)
        splits.append((plan.exploration, plan.confirmation))
    return splits


def _check_p(p_values: ArrayLike) -> NDArray[np.float64]:
    p = np.asarray(p_values, dtype=np.float64)
    if p.ndim != 1 or p.size == 0 or np.any((p < 0.0) | (p > 1.0)) or not np.all(np.isfinite(p)):
        msg = "need a non-empty one-dimensional array of p-values in [0, 1]"
        raise ValueError(msg)
    return p


def mmb_quantile_aggregate(p_values: ArrayLike, gamma: float = 0.5) -> float:
    """``Q(gamma) = min(1, q_gamma({p_b / gamma}))`` with the empirical (inverted-CDF) quantile."""
    if not 0.0 < gamma < 1.0:
        msg = "gamma must lie in (0, 1)"
        raise ValueError(msg)
    p = _check_p(p_values)
    return float(min(1.0, np.quantile(p / gamma, gamma, method="inverted_cdf")))


def mmb_adaptive_aggregate(p_values: ArrayLike, gamma_min: float = 0.05) -> float:
    """Adaptive rule: ``min(1, (1 - log gamma_min) * inf_gamma Q(gamma))``, gamma in (gamma_min, 1).

    From Meinshausen, Meier & Buhlmann (2009).
    """
    if not 0.0 < gamma_min < 1.0:
        msg = "gamma_min must lie in (0, 1)"
        raise ValueError(msg)
    p = np.sort(_check_p(p_values))
    b = p.size
    # Q(gamma) is piecewise constant in the quantile and decreasing in 1/gamma between grid
    # points, so the infimum over (gamma_min, 1) is attained at gamma = k / b (k = b is the
    # limit gamma -> 1, where Q equals the largest p-value).
    best = 1.0
    for k in range(1, b + 1):
        gamma = k / b
        if gamma <= gamma_min:
            continue
        best = min(best, p[k - 1] / gamma)
    return float(min(1.0, (1.0 - math.log(gamma_min)) * best))
