"""Assumption registry (section 8.6)."""

from __future__ import annotations

import numpy as np
import polars as pl

from edaforge.rigor.assumptions import (
    AssumptionSpec,
    CheckOutcome,
    lag1_autocorrelation_check,
    min_group_size_check,
    run_assumption_checks,
)


def test_untestable_crashing_and_fallback_checks() -> None:
    def boom(data: pl.DataFrame, params: object) -> CheckOutcome:
        raise RuntimeError("broken")

    def fails(data: pl.DataFrame, params: object) -> CheckOutcome:
        return CheckOutcome(status="fail", detail="nope")

    specs = [
        AssumptionSpec("no_confounding", "untestable", "major"),
        AssumptionSpec("crash", "raises", "major", check=boom),
        AssumptionSpec(
            "linear", "fails", "major", check=fails, on_fail="fallback", fallback_to="gam"
        ),
    ]
    results = run_assumption_checks(specs, pl.DataFrame({"x": [1]}), {})
    assert [r.status for r in results] == ["untestable", "not_checked", "fail"]
    assert "broken" in results[1].detail
    assert (results[2].action, results[2].fallback_to) == ("fallback", "gam")


def test_min_group_size_uses_only_the_tested_groups() -> None:
    frame = pl.DataFrame(
        {"x": [1.0] * 25 + [2.0] * 25 + [3.0] * 3, "g": ["a"] * 25 + ["b"] * 25 + ["c"] * 3}
    )
    check = min_group_size_check(10)
    ok = check(frame, {"column": "x", "env_column": "g", "group_a": "a", "group_b": "b"})
    bad = check(frame, {"column": "x", "env_column": "g", "group_a": "a", "group_b": "c"})
    assert ok.status == "pass"
    assert bad.status == "fail"
    assert check(frame, {"column": "x"}).status == "not_checked"


def test_level_shift_between_groups_is_not_autocorrelation() -> None:
    rng = np.random.default_rng(0)
    values = np.concatenate([rng.normal(0, 1, 500), rng.normal(3, 1, 500)])
    frame = pl.DataFrame({"x": values, "g": ["a"] * 500 + ["b"] * 500})
    params = {"column": "x", "env_column": "g", "group_a": "a", "group_b": "b"}
    assert lag1_autocorrelation_check(None)(frame, params).status == "pass"
    walk = np.cumsum(rng.normal(size=1000))
    serial = pl.DataFrame({"x": walk, "g": ["a"] * 500 + ["b"] * 500})
    assert lag1_autocorrelation_check(None)(serial, params).status == "warn"
