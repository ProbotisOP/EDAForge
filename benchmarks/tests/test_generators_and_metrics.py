"""Proving Grounds generators and metrics."""

from __future__ import annotations

from typing import cast

import numpy as np
import polars as pl
import pytest

from edaforge_bench.generators import (
    NULL_VARIANTS,
    MultiEnvSpec,
    SCMSpec,
    multi_environment,
    null_world,
    permuted_copy,
    random_dag,
    structural_causal_model,
)
from edaforge_bench.metrics import (
    detection_score,
    edge_f1,
    expected_calibration_error,
    structural_hamming_distance,
    varsortability,
)


def test_null_worlds_are_reproducible_and_typed() -> None:
    assert len(NULL_VARIANTS) == 10
    for name, spec in NULL_VARIANTS.items():
        a = null_world(spec, seed=3).frame
        b = null_world(spec, seed=3).frame
        assert a.equals(b), name
        assert a.height == spec.n
    missing = null_world(NULL_VARIANTS["missing_mcar"], seed=1).frame
    assert 0.05 < missing["num0_normal"].null_count() / missing.height < 0.15


def test_permuted_copy_keeps_marginals_and_breaks_links() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=2000)
    frame = pl.DataFrame(
        {"x": x, "y": 2 * x + rng.normal(size=2000) * 0.1, "g": rng.choice(["a", "b"], 2000)}
    )
    shuffled = permuted_copy(frame, np.random.default_rng(1), within="g")
    for name in ("x", "y"):
        np.testing.assert_array_equal(
            np.sort(shuffled[name].to_numpy()), np.sort(frame[name].to_numpy())
        )
    assert abs(np.corrcoef(shuffled["x"], shuffled["y"])[0, 1]) < 0.1
    assert shuffled["g"].equals(frame["g"])


def test_random_dags_are_acyclic() -> None:
    for seed in range(20):
        a = random_dag(9, 2.0, np.random.default_rng(seed))
        power = np.eye(9, dtype=np.int64)
        for _ in range(9):
            power = power @ a
        assert not power.any(), "a cycle would survive nine multiplications"


def test_varsortability_is_high_raw_and_neutral_when_standardized() -> None:
    raw = structural_causal_model(SCMSpec(n=3000, n_nodes=8, expected_degree=2.5), seed=4)
    std = structural_causal_model(
        SCMSpec(n=3000, n_nodes=8, expected_degree=2.5, standardize=True), seed=4
    )
    assert varsortability(raw.frame.to_numpy(), raw.adjacency) > 0.75
    assert varsortability(std.frame.to_numpy(), std.adjacency) == pytest.approx(0.5, abs=0.15)


def test_scm_options() -> None:
    data = structural_causal_model(
        SCMSpec(
            n=1000,
            n_nodes=6,
            n_latent=2,
            n_binary=1,
            selection_on=0,
            mechanism="nonlinear",
            noise="mixed",
        ),
        seed=2,
    )
    assert data.frame.width == 4
    assert data.selected_rows == data.frame.height == 500
    assert set(data.frame[data.binary[0]].unique().to_list()) <= {0, 1}
    assert not set(data.latent) & set(data.frame.columns)


def test_multi_environment_truth_matches_the_data() -> None:
    data = multi_environment(MultiEnvSpec(n_per_env=20000, n_nodes=5, shift_size=0.4), seed=6)
    frame = data.frame
    for name, standardized in data.mean_shift.items():
        e0 = frame.filter(pl.col("__source__") == "E0")[name]
        e1 = frame.filter(pl.col("__source__") == "E1")[name]
        pooled_sd = float(cast("float | None", pl.concat([e0, e1]).std()) or 1.0)
        empirical = (float(e1.mean()) - float(e0.mean())) / pooled_sd  # type: ignore[arg-type]
        assert empirical == pytest.approx(standardized, abs=0.03), name
    assert data.shifted_mechanisms == ("x0",)


def test_metrics() -> None:
    truth = np.array([[0, 1, 0], [0, 0, 1], [0, 0, 0]])
    reversed_edge = np.array([[0, 0, 0], [1, 0, 1], [0, 0, 0]])
    assert structural_hamming_distance(truth, truth) == 0
    assert structural_hamming_distance(reversed_edge, truth) == 1
    assert structural_hamming_distance(np.zeros((3, 3)), truth) == 2
    assert edge_f1(truth, truth) == 1.0
    assert edge_f1(np.zeros((3, 3)), truth) == 0.0
    score = detection_score({"a", "b", "c"}, {"a", "b", "d"})
    assert (score.fdr, score.recall) == (pytest.approx(1 / 3), pytest.approx(2 / 3))
    assert expected_calibration_error([0.9] * 10, [1] * 9 + [0]) == pytest.approx(0.0)
    assert expected_calibration_error([0.9] * 10, [0] * 10) == pytest.approx(0.9)
