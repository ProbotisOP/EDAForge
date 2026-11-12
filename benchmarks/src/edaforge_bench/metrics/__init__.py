"""Benchmark metrics (section 16.3)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "DetectionScore",
    "detection_score",
    "edge_f1",
    "expected_calibration_error",
    "structural_hamming_distance",
    "varsortability",
]


@dataclass(frozen=True)
class DetectionScore:
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def fdr(self) -> float:
        found = self.true_positives + self.false_positives
        return self.false_positives / found if found else 0.0

    @property
    def recall(self) -> float:
        truth = self.true_positives + self.false_negatives
        return self.true_positives / truth if truth else 1.0


def detection_score(found: Iterable[str], truth: Iterable[str]) -> DetectionScore:
    found_set, truth_set = set(found), set(truth)
    return DetectionScore(
        true_positives=len(found_set & truth_set),
        false_positives=len(found_set - truth_set),
        false_negatives=len(truth_set - found_set),
    )


def structural_hamming_distance(estimated: ArrayLike, truth: ArrayLike) -> int:
    """SHD between directed graphs: missing, extra and reversed edges each count once."""
    est = np.asarray(estimated, dtype=np.int64) != 0
    tru = np.asarray(truth, dtype=np.int64) != 0
    est_skeleton = est | est.T
    tru_skeleton = tru | tru.T
    skeleton_diff = int(np.triu(est_skeleton ^ tru_skeleton, k=1).sum())
    both = np.triu(est_skeleton & tru_skeleton, k=1)
    reversed_ = 0
    for i, j in zip(*np.nonzero(both), strict=True):
        if bool(est[i, j]) != bool(tru[i, j]) or bool(est[j, i]) != bool(tru[j, i]):
            reversed_ += 1
    return skeleton_diff + reversed_


def edge_f1(estimated: ArrayLike, truth: ArrayLike) -> float:
    est = np.asarray(estimated, dtype=np.int64) != 0
    tru = np.asarray(truth, dtype=np.int64) != 0
    tp = int((est & tru).sum())
    fp = int((est & ~tru).sum())
    fn = int((~est & tru).sum())
    return 0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn)


def varsortability(data: ArrayLike, adjacency: ArrayLike, rtol: float = 1e-9) -> float:
    """Share of directed paths i -> ... -> j along which marginal variance increases.

    Reisach, Seiler & Weichwald (2021): 1 means sorting by variance recovers the causal order,
    0.5 is uninformative. Variances within a relative tolerance ``rtol`` are ties and count one
    half, so floating-point noise after standardization does not decide the order.
    """
    x = np.asarray(data, dtype=np.float64)
    a = (np.asarray(adjacency, dtype=np.int64) != 0).astype(np.int64)
    n_nodes = a.shape[0]
    if x.shape[1] != n_nodes:
        msg = "data columns must match the adjacency matrix"
        raise ValueError(msg)
    variances = x.var(axis=0)
    reach = a.copy()
    power = a.copy()
    for _ in range(n_nodes - 1):
        power = (power @ a > 0).astype(np.int64)
        reach = ((reach + power) > 0).astype(np.int64)
    pairs = np.nonzero(reach)
    if pairs[0].size == 0:
        return 0.5
    score = 0.0
    for i, j in zip(*pairs, strict=True):
        scale = max(abs(float(variances[i])), abs(float(variances[j])), 1e-300)
        difference = float(variances[j] - variances[i])
        if abs(difference) <= rtol * scale:
            score += 0.5
        elif difference > 0.0:
            score += 1.0
    return score / pairs[0].size


def expected_calibration_error(
    probabilities: ArrayLike, outcomes: ArrayLike, n_bins: int = 10
) -> float:
    """ECE with equal-width bins: sum over bins of (share of items) * |mean p - hit rate|."""
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(outcomes, dtype=np.float64)
    if p.shape != y.shape or p.ndim != 1 or p.size == 0:
        msg = "probabilities and outcomes must be equal-length non-empty vectors"
        raise ValueError(msg)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: NDArray[np.int64] = np.clip(np.digitize(p, edges[1:-1], right=True), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        mask = bins == b
        if mask.any():
            ece += mask.mean() * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return float(ece)
