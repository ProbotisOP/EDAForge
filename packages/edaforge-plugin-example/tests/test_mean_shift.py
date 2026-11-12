"""The example analyzer: reference equivalence of its statistics, and null calibration."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from scipy import stats

import edaforge as gh
from edaforge_plugin_example.mean_shift import (
    MeanShiftAnalyzer,
    _batch_cohen_d,
    _batch_mean_diff,
    _permutation_draw,
    cohen_d,
    prob_superiority,
    welch_t,
)


def test_welch_t_matches_scipy() -> None:
    rng = np.random.default_rng(0)
    a, b = rng.normal(0, 1, 80), rng.normal(0.3, 2, 120)
    reference = stats.ttest_ind(b, a, equal_var=False).statistic
    assert welch_t(a, b) == pytest.approx(float(reference), rel=1e-12)


def test_cohen_d_and_probability_of_superiority() -> None:
    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([3.0, 4.0, 5.0, 6.0])
    pooled = np.sqrt((3 * np.var(a, ddof=1) + 3 * np.var(b, ddof=1)) / 6)
    assert cohen_d(a, b) == pytest.approx(2.0 / pooled)
    brute = np.mean([(y > x) + 0.5 * (y == x) for x in a for y in b])
    assert prob_superiority(a, b) == pytest.approx(brute)


def test_batch_statistics_match_scalar_ones() -> None:
    rng = np.random.default_rng(1)
    a, b = rng.normal(size=(5, 30)), rng.normal(size=(5, 40))
    np.testing.assert_allclose(
        _batch_mean_diff(a, b), [b[i].mean() - a[i].mean() for i in range(5)]
    )
    np.testing.assert_allclose(_batch_cohen_d(a, b), [cohen_d(a[i], b[i]) for i in range(5)])


def test_permutation_draw_reproduces_welch_t_on_a_relabelling() -> None:
    rng = np.random.default_rng(2)
    pooled = rng.normal(size=50)
    draw = _permutation_draw(pooled, 20)
    stats_draw = draw(np.random.default_rng(7), 3)
    keys = np.random.default_rng(7).random((3, 50))
    for i in range(3):
        idx = np.argpartition(keys[i], 19)[:20]
        mask = np.zeros(50, dtype=bool)
        mask[idx] = True
        assert stats_draw[i] == pytest.approx(abs(welch_t(pooled[mask], pooled[~mask])), rel=1e-9)


def test_plan_enumerates_columns_and_environment_pairs() -> None:
    frame = pl.DataFrame(
        {"x": [1.0, 2.0, 3.0], "y": [1.0, 1.0, 2.0], "__source__": ["a", "b", "c"]}
    )
    run = gh.discover(frame, analyzers=[MeanShiftAnalyzer()], budget="quick")
    tested = run.searched[0].tested
    assert tested == 0  # three rows: groups too small, every hypothesis registered untested
    registered = [e for e in run.ledger if e.analyzer == "example.mean_shift"]
    assert len(registered) == 6  # 2 columns x 3 environment pairs


@pytest.mark.slow
def test_discovery_p_values_are_uniform_under_the_null() -> None:
    """Exploration p-values of the permutation test are calibrated on null data."""
    p_values = []
    for seed in range(60):
        rng = np.random.default_rng(seed)
        frame = pl.DataFrame(
            {
                "x": rng.lognormal(size=400),
                "__source__": rng.choice(["A", "B"], size=400),
            }
        )
        run = gh.discover(frame, analyzers=[MeanShiftAnalyzer()], budget="quick", seed=seed)
        p_values.extend(
            e.p_value for e in run.ledger if e.p_value is not None and e.split == "full"
        )
    result = stats.kstest(p_values, "uniform")
    assert result.pvalue > 0.01
