"""Phase 0 statistical gates on the example analyzer (section 16.3, gates 1 and 3 in miniature)."""

from __future__ import annotations

import pytest

from edaforge_bench.gates import null_control_mean_shift, recall_mean_shift


@pytest.mark.gate
@pytest.mark.slow
def test_null_control_200_datasets() -> None:
    result = null_control_mean_shift(n_datasets=200)
    assert result.passed, result.summary()


@pytest.mark.gate
@pytest.mark.slow
def test_recall_of_medium_shifts() -> None:
    result = recall_mean_shift(n_datasets=50)
    assert result.passed, result.summary()
    assert result.details["false_confirmed_unshifted"] <= 2


def test_null_control_smoke() -> None:
    assert null_control_mean_shift(n_datasets=10).value <= 0.10
