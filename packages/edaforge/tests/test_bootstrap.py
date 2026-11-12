"""BCa bootstrap: equivalence with scipy.stats.bootstrap on the same replicates."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from edaforge.rigor.bootstrap import bca_bounds, bootstrap_interval, jackknife_values


def _jackknife_loo(samples: list[np.ndarray], statistic) -> list[np.ndarray]:
    values, kind = jackknife_values(samples, statistic, np.random.default_rng(0))
    assert kind == "leave_one_out"
    return values


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_one_sample_bca_matches_scipy(seed: int) -> None:
    rng = np.random.default_rng(seed)
    x = rng.exponential(size=60)
    res = stats.bootstrap(
        (x,), np.mean, n_resamples=4000, method="BCa", confidence_level=0.9, rng=seed
    )
    replicates = np.asarray(res.bootstrap_distribution)
    low, high, _, _ = bca_bounds(
        float(x.mean()), replicates, _jackknife_loo([x], lambda a: float(a.mean())), 0.9
    )
    assert low == pytest.approx(res.confidence_interval.low, rel=1e-10)
    assert high == pytest.approx(res.confidence_interval.high, rel=1e-10)


def test_two_sample_bca_matches_scipy() -> None:
    rng = np.random.default_rng(7)
    a = rng.normal(0.0, 1.0, size=40)
    b = rng.lognormal(0.0, 0.5, size=55)

    def diff(x: np.ndarray, y: np.ndarray, axis: int = -1) -> np.ndarray:
        return np.mean(y, axis=axis) - np.mean(x, axis=axis)

    res = stats.bootstrap(
        (a, b), diff, n_resamples=3000, method="BCa", confidence_level=0.95, rng=7
    )
    replicates = np.asarray(res.bootstrap_distribution)
    jack = _jackknife_loo([a, b], lambda x, y: float(y.mean() - x.mean()))
    low, high, _, _ = bca_bounds(float(b.mean() - a.mean()), replicates, jack, 0.95)
    assert low == pytest.approx(res.confidence_interval.low, rel=1e-10)
    assert high == pytest.approx(res.confidence_interval.high, rel=1e-10)


def test_bootstrap_interval_is_deterministic_and_sensible() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(5.0, 2.0, size=200)
    kwargs = {"n_resamples": 1500, "level": 0.95}
    first = bootstrap_interval([x], lambda a: float(a.mean()), np.random.default_rng(9), **kwargs)
    second = bootstrap_interval([x], lambda a: float(a.mean()), np.random.default_rng(9), **kwargs)
    assert first == second
    assert first.method == "bca"
    assert first.low < x.mean() < first.high
    se = x.std(ddof=1) / np.sqrt(x.size)
    assert first.high - first.low == pytest.approx(2 * 1.96 * se, rel=0.15)


def test_batch_statistic_matches_scalar_statistic() -> None:
    x = np.random.default_rng(4).normal(size=80)
    scalar = bootstrap_interval([x], lambda a: float(a.mean()), np.random.default_rng(1))
    batch = bootstrap_interval(
        [x],
        lambda a: float(a.mean()),
        np.random.default_rng(1),
        batch_statistic=lambda a: a.mean(axis=1),
    )
    assert scalar.low == pytest.approx(batch.low, rel=1e-12)
    assert scalar.high == pytest.approx(batch.high, rel=1e-12)


def test_grouped_jackknife_for_large_samples() -> None:
    x = np.random.default_rng(5).normal(size=6000)
    result = bootstrap_interval(
        [x],
        lambda a: float(a.mean()),
        np.random.default_rng(2),
        n_resamples=500,
        batch_statistic=lambda a: a.mean(axis=1),
    )
    assert result.jackknife == "grouped"
    assert result.method == "bca"
    se = x.std(ddof=1) / np.sqrt(x.size)
    assert result.high - result.low == pytest.approx(2 * 1.96 * se, rel=0.2)


def test_degenerate_and_fallback_cases() -> None:
    constant = np.ones(20)
    result = bootstrap_interval([constant], lambda a: float(a.mean()), np.random.default_rng(0))
    assert result.method == "degenerate"
    assert (result.low, result.high) == (1.0, 1.0)
    # A resample almost surely has fewer distinct values than the sample, so every replicate
    # lies strictly below the estimate: BCa's bias correction is infinite, the percentile
    # interval is used, and the reason is recorded.
    x = np.random.default_rng(1).normal(size=30)
    result = bootstrap_interval([x], lambda a: float(np.unique(a).size), np.random.default_rng(0))
    assert result.method == "percentile"
    assert "percentile interval used" in result.note


def test_input_validation() -> None:
    with pytest.raises(ValueError, match="at least two"):
        bootstrap_interval([np.array([1.0])], lambda a: float(a.mean()), np.random.default_rng(0))
    with pytest.raises(ValueError, match="level"):
        bootstrap_interval(
            [np.arange(5.0)], lambda a: float(a.mean()), np.random.default_rng(0), level=1.5
        )
