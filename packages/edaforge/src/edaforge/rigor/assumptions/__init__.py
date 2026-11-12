"""Assumption registry (section 8.6).

Every analyzer declares its assumptions as :class:`AssumptionSpec` objects. A spec without a
check is *untestable* (for example, "no unmeasured confounding") and is reported as a caveat.
A failed check triggers the registered fallback, or a downgrade with a caveat; the outcome is
stored on the finding as an :class:`~edaforge.models.AssumptionCheck`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import polars as pl
from pydantic import JsonValue

from edaforge.models import AssumptionCheck

__all__ = [
    "AssumptionSpec",
    "CheckFn",
    "CheckOutcome",
    "lag1_autocorrelation_check",
    "min_group_size_check",
    "run_assumption_checks",
]

Severity = Literal["minor", "major", "critical"]


@dataclass(frozen=True)
class CheckOutcome:
    status: Literal["pass", "warn", "fail", "not_checked"]
    statistic: float | None = None
    p_value: float | None = None
    detail: str = ""


CheckFn = Callable[[pl.DataFrame, Mapping[str, JsonValue]], CheckOutcome]


@dataclass(frozen=True)
class AssumptionSpec:
    name: str
    description: str
    severity: Severity
    check: CheckFn | None = None  # None: untestable
    on_fail: Literal["fallback", "downgrade", "caveat"] = "downgrade"
    fallback_to: str | None = None


def run_assumption_checks(
    specs: Sequence[AssumptionSpec], data: pl.DataFrame, params: Mapping[str, JsonValue]
) -> list[AssumptionCheck]:
    results: list[AssumptionCheck] = []
    for spec in specs:
        if spec.check is None:
            results.append(
                AssumptionCheck(
                    name=spec.name,
                    description=spec.description,
                    status="untestable",
                    severity=spec.severity,
                    detail="cannot be checked from the data; see the sensitivity analysis",
                    action="caveat",
                )
            )
            continue
        try:
            outcome = spec.check(data, params)
        except Exception as exc:  # noqa: BLE001 - a crashing check is recorded, not hidden
            outcome = CheckOutcome(status="not_checked", detail=f"check raised {exc!r}")
        action: Literal["none", "fallback", "downgrade", "caveat"] = "none"
        fallback_to = None
        if outcome.status == "fail":
            if spec.on_fail == "fallback" and spec.fallback_to:
                action, fallback_to = "fallback", spec.fallback_to
            else:
                action = "downgrade" if spec.on_fail != "caveat" else "caveat"
        elif outcome.status in {"warn", "not_checked"}:
            action = "caveat"
        p_value = outcome.p_value
        if p_value is not None and not np.isfinite(p_value):
            p_value = None
        results.append(
            AssumptionCheck(
                name=spec.name,
                description=spec.description,
                status=outcome.status,
                severity=spec.severity,
                statistic=outcome.statistic,
                p_value=p_value,
                detail=outcome.detail,
                action=action,
                fallback_to=fallback_to,
            )
        )
    return results


def _task_groups(
    data: pl.DataFrame, params: Mapping[str, JsonValue], group_param: str
) -> tuple[pl.DataFrame, str | None]:
    """Restrict ``data`` to the task's groups (``group_a``/``group_b``) when they are given."""
    group_column = params.get(group_param)
    if not isinstance(group_column, str) or group_column not in data.columns:
        return data, None
    wanted = [params[k] for k in ("group_a", "group_b") if isinstance(params.get(k), str)]
    if wanted:
        data = data.filter(pl.col(group_column).cast(pl.String).is_in([str(w) for w in wanted]))
    return data, group_column


def min_group_size_check(minimum: int, group_param: str = "env_column") -> CheckFn:
    """Every group under test has at least ``minimum`` non-null values of the analyzed column.

    The grouping column is read from the task parameter ``group_param``.
    """

    def check(data: pl.DataFrame, params: Mapping[str, JsonValue]) -> CheckOutcome:
        frame, group_column = _task_groups(data, params, group_param)
        if group_column is None:
            return CheckOutcome(status="not_checked", detail=f"no {group_param} parameter")
        column = params.get("column")
        if isinstance(column, str):
            frame = frame.filter(pl.col(column).is_not_null())
        counts = frame.group_by(group_column).len()
        smallest = int(counts["len"].min()) if counts.height else 0  # pyright: ignore[reportArgumentType]
        status: Literal["pass", "fail"] = "pass" if smallest >= minimum else "fail"
        return CheckOutcome(
            status=status,
            statistic=float(smallest),
            detail=f"smallest group has {smallest} rows (minimum {minimum})",
        )

    return check


def lag1_autocorrelation_check(
    order_column: str | None, threshold: float = 0.1, group_param: str = "env_column"
) -> CheckFn:
    """Rows look independent: pooled within-group lag-1 autocorrelation of the analyzed column.

    Centering within each group matters: stacked files with a real difference in level would
    otherwise look autocorrelated in file order.
    """

    def check(data: pl.DataFrame, params: Mapping[str, JsonValue]) -> CheckOutcome:
        column = params.get("column")
        if not isinstance(column, str):
            return CheckOutcome(status="not_checked", detail="no column to check")
        frame, group_column = _task_groups(data, params, group_param)
        if order_column:
            frame = frame.sort(order_column)
        if group_column is None:
            parts = [frame[column].drop_nulls().cast(pl.Float64).to_numpy()]
        else:
            parts = [
                part[column].drop_nulls().cast(pl.Float64).to_numpy()
                for part in frame.partition_by(group_column, maintain_order=True)
            ]
        numerator = 0.0
        denominator = 0.0
        count = 0
        for values in parts:
            if values.size < 3:
                continue
            centered = values - values.mean()
            numerator += float(np.dot(centered[:-1], centered[1:]))
            denominator += float(np.dot(centered, centered))
            count += values.size
        if count < 10 or denominator == 0.0:
            return CheckOutcome(status="not_checked", detail="too few non-constant values")
        rho = numerator / denominator
        status: Literal["pass", "warn"] = "pass" if abs(rho) < threshold else "warn"
        basis = f"ordered by {order_column}" if order_column else "in file order"
        return CheckOutcome(
            status=status,
            statistic=rho,
            detail=(
                f"within-group lag-1 autocorrelation {rho:.3f} {basis} "
                f"(warn at |rho| >= {threshold})"
            ),
        )

    return check
