"""Besag-Clifford sequential permutation p-values."""

from __future__ import annotations

import numpy as np
import pytest

from edaforge.rigor.permutation import besag_clifford_pvalue


def uniform_draw(rng: np.random.Generator, size: int) -> np.ndarray:
    return rng.random(size)


def test_valid_under_the_null() -> None:
    """P(p <= alpha) <= alpha when the observed statistic comes from the null distribution."""
    rng = np.random.default_rng(11)
    p_values = []
    for _ in range(3000):
        observed = float(rng.random())
        outcome = besag_clifford_pvalue(observed, uniform_draw, rng, h=10, n_max=200)
        p_values.append(outcome.p_value)
    p = np.asarray(p_values)
    for alpha in (0.01, 0.05, 0.1, 0.25, 0.5):
        rate = float(np.mean(p <= alpha))
        # Monte Carlo slack of three standard errors.
        assert rate <= alpha + 3 * np.sqrt(alpha * (1 - alpha) / p.size), (alpha, rate)


def test_stops_early_when_the_null_is_obvious() -> None:
    outcome = besag_clifford_pvalue(0.01, uniform_draw, np.random.default_rng(0), h=10, n_max=1000)
    assert outcome.stopped_early
    assert outcome.n_draws < 50
    assert outcome.p_value == pytest.approx(10 / outcome.n_draws)


def test_floor_when_nothing_is_as_extreme() -> None:
    outcome = besag_clifford_pvalue(2.0, uniform_draw, np.random.default_rng(0), h=10, n_max=1000)
    assert not outcome.stopped_early
    assert outcome.n_draws == 999
    assert outcome.p_value == pytest.approx(1 / 1000)


def test_ties_count_as_exceedances() -> None:
    def tied(rng: np.random.Generator, size: int) -> np.ndarray:
        return np.full(size, 1.0)

    outcome = besag_clifford_pvalue(1.0, tied, np.random.default_rng(0), h=5, n_max=100)
    assert outcome.p_value == 1.0


def test_batch_size_does_not_change_the_result() -> None:
    results = {
        besag_clifford_pvalue(
            0.93, uniform_draw, np.random.default_rng(5), h=10, n_max=500, batch_size=b
        ).p_value
        for b in (1, 7, 64, 499)
    }
    assert len(results) == 1


@pytest.mark.parametrize(("h", "n_max"), [(0, 10), (10, 10), (1, 1)])
def test_invalid_parameters(h: int, n_max: int) -> None:
    with pytest.raises(ValueError, match="require"):
        besag_clifford_pvalue(0.5, uniform_draw, np.random.default_rng(0), h=h, n_max=n_max)


def test_bad_draws_are_rejected() -> None:
    with pytest.raises(ValueError, match="shape"):
        besag_clifford_pvalue(
            0.5, lambda rng, size: rng.random(size + 1), np.random.default_rng(0), n_max=20
        )
    with pytest.raises(ValueError, match="finite"):
        besag_clifford_pvalue(
            0.5, lambda rng, size: np.full(size, np.nan), np.random.default_rng(0), n_max=20
        )
