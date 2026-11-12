"""Splitting, sealing and cross-fit aggregation (section 8.1)."""

from __future__ import annotations

import numpy as np
import pytest

from edaforge.config import RigorConfig
from edaforge.rigor.ledger import HypothesisLedger
from edaforge.rigor.splits import (
    SealedHoldout,
    choose_mode,
    half_splits,
    holdout_plan,
    mmb_adaptive_aggregate,
    mmb_quantile_aggregate,
)


def test_mode_thresholds_follow_section_8_1() -> None:
    rigor = RigorConfig()
    assert choose_mode(2000, rigor) == "holdout"
    assert choose_mode(1999, rigor) == "cross_fit"
    assert choose_mode(300, rigor) == "cross_fit"
    assert choose_mode(299, rigor) == "small_sample"


def test_stratified_holdout_keeps_proportions() -> None:
    strata = np.array(["a"] * 700 + ["b"] * 300)
    plan = holdout_plan(1000, 0.3, np.random.default_rng(0), strata=strata)
    assert plan.confirmation.size == 300
    conf_share_a = np.mean(strata[plan.confirmation] == "a")
    assert conf_share_a == pytest.approx(0.7, abs=1e-12)
    assert np.intersect1d(plan.exploration, plan.confirmation).size == 0
    assert np.union1d(plan.exploration, plan.confirmation).size == 1000


def test_group_aware_holdout_never_splits_a_group() -> None:
    groups = np.repeat(np.arange(200), 5)
    plan = holdout_plan(1000, 0.3, np.random.default_rng(1), groups=groups)
    assert set(groups[plan.exploration]).isdisjoint(set(groups[plan.confirmation]))
    assert plan.confirmation.size == pytest.approx(300, abs=10)


def test_time_ordered_holdout_with_embargo() -> None:
    order = np.arange(1000)[::-1]  # row 999 is the earliest
    plan = holdout_plan(1000, 0.3, np.random.default_rng(2), order=order, embargo=20)
    assert plan.embargo.size == 20
    assert plan.confirmation.size == 300
    # Every confirmation row comes after every exploration row in time.
    assert order[plan.confirmation].min() > order[plan.exploration].max()


def test_holdout_is_deterministic_given_a_seed() -> None:
    a = holdout_plan(500, 0.3, np.random.default_rng(42))
    b = holdout_plan(500, 0.3, np.random.default_rng(42))
    np.testing.assert_array_equal(a.confirmation, b.confirmation)


def test_sealed_access_is_logged_and_breaks_blinding_before_freeze() -> None:
    plan = holdout_plan(100, 0.3, np.random.default_rng(0))
    sealed = SealedHoldout(plan, data_hash="d" * 64)
    ledger = HypothesisLedger("R-test", 1)
    sealed.unseal(ledger, reason="peek")
    assert ledger.blind_violation
    ledger2 = HypothesisLedger("R-test", 1)
    ledger2.freeze(["k"])
    sealed.unseal(ledger2, reason="confirm")
    assert not ledger2.blind_violation
    assert len(sealed.seal_hash) == 64
    assert sealed.record(100).n_confirmation == 30


def test_half_splits_are_disjoint_halves() -> None:
    splits = half_splits(400, 5, np.random.default_rng(3))
    assert len(splits) == 5
    for select, test in splits:
        assert np.intersect1d(select, test).size == 0
        assert select.size + test.size == 400


def test_mmb_quantile_known_values() -> None:
    assert mmb_quantile_aggregate([0.01, 0.02, 0.03, 0.04], gamma=0.5) == pytest.approx(0.04)
    assert mmb_quantile_aggregate([0.01, 1.0, 1.0, 1.0], gamma=0.5) == 1.0
    assert mmb_quantile_aggregate([0.001] * 10, gamma=0.5) == pytest.approx(0.002)


def test_mmb_aggregates_are_valid_under_the_null() -> None:
    rng = np.random.default_rng(8)
    fixed = []
    adaptive = []
    for _ in range(4000):
        p = rng.uniform(size=10)
        fixed.append(mmb_quantile_aggregate(p, 0.5))
        adaptive.append(mmb_adaptive_aggregate(p, 0.05))
    for values in (np.asarray(fixed), np.asarray(adaptive)):
        for alpha in (0.05, 0.1, 0.2):
            assert np.mean(values <= alpha) <= alpha + 0.015


@pytest.mark.parametrize("bad", [[], [1.2], [[0.1]]])
def test_aggregate_input_validation(bad: list[float]) -> None:
    with pytest.raises(ValueError, match="p-values"):
        mmb_quantile_aggregate(bad)
