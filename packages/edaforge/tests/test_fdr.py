"""Batch FDR: reference equivalence with statsmodels, and properties."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from statsmodels.stats.multitest import multipletests

from edaforge.rigor.fdr import bh_adjust, bh_reject, by_adjust, ebh_reject

p_lists = st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=60)


@pytest.mark.parametrize("seed", range(5))
def test_bh_and_by_match_statsmodels(seed: int) -> None:
    rng = np.random.default_rng(seed)
    p = np.concatenate([rng.uniform(size=80), rng.uniform(0, 0.01, size=20)])
    _, ref_bh, _, _ = multipletests(p, method="fdr_bh")
    _, ref_by, _, _ = multipletests(p, method="fdr_by")
    np.testing.assert_allclose(bh_adjust(p), ref_bh, rtol=1e-12, atol=1e-15)
    np.testing.assert_allclose(by_adjust(p), ref_by, rtol=1e-12, atol=1e-15)
    reject_ref, *_ = multipletests(p, alpha=0.05, method="fdr_bh")
    np.testing.assert_array_equal(bh_reject(p, 0.05), reject_ref)


@given(p_lists)
@settings(max_examples=200)
def test_bh_properties(p: list[float]) -> None:
    q = bh_adjust(p)
    arr = np.asarray(p)
    assert np.all(q >= arr - 1e-15)
    assert np.all(q <= 1.0)
    order = np.argsort(arr, kind="mergesort")
    assert np.all(np.diff(q[order]) >= -1e-15)  # monotone in p
    assert np.all(by_adjust(p) >= q - 1e-15)  # BY is never less conservative


@given(st.lists(st.floats(min_value=1e-6, max_value=1.0), min_size=1, max_size=40))
@settings(max_examples=200)
def test_ebh_on_reciprocal_p_values_equals_bh(p: list[float]) -> None:
    # With e = 1/p the e-BH and BH step-up conditions coincide algebraically.
    e = 1.0 / np.asarray(p)
    np.testing.assert_array_equal(ebh_reject(e, 0.1), bh_reject(p, 0.1))


def test_ebh_small_example() -> None:
    # m = 3, alpha = 0.1: thresholds m / (alpha k) = 30, 15, 10 for k = 1, 2, 3.
    np.testing.assert_array_equal(ebh_reject([40.0, 16.0, 1.0], 0.1), [True, True, False])
    np.testing.assert_array_equal(ebh_reject([29.0, 14.0, 9.0], 0.1), [False, False, False])


@pytest.mark.parametrize("bad", [[-0.1], [1.5], [np.nan], [[0.1, 0.2]]])
def test_invalid_p_values_are_rejected(bad: list[float]) -> None:
    with pytest.raises(ValueError, match="p-values"):
        bh_adjust(bad)


def test_empty_input() -> None:
    assert bh_adjust([]).size == 0
    assert ebh_reject([], 0.1).size == 0


def test_bh_rejects_a_p_value_exactly_on_the_boundary() -> None:
    # p_(3) = 0.1 = (3/3) * 0.1: BH rejects all three. The adjusted p-value 0.1 * 3 / 3 rounds to
    # 0.10000000000000002, which a division-based comparison would wrongly keep.
    assert bh_reject([0.0625, 0.0625, 0.1], 0.1).tolist() == [True, True, True]
    assert bh_reject([0.0625, 0.0625, 0.1000001], 0.1).tolist() == [
        True,
        True,
        False,
    ]  # k* = 2: 0.1875 <= 0.2
