"""Example analyzer: does a column's mean differ between two environments (files, sites)?

This is the Phase 0 "dummy analyzer". It is simple, but statistically honest:

* ``screen`` (exploration rows): the absolute Welch t statistic, with a permutation null that
  shuffles the environment labels. The studentized statistic keeps the permutation test
  asymptotically valid when the group variances differ (Chung & Romano, 2013). The p-value comes
  from ``ctx.ledger`` (Besag-Clifford sequential stopping).
* ``refine`` (survivors only): the mean difference and Cohen's d with BCa intervals.
* ``confirm`` (sealed rows): the same test as a child hypothesis, and the effect sizes recomputed
  on the sealed rows so that the reported effect does not carry the winner's curse.

Missing values are excluded per test and the count is reported, never dropped silently.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar

import numpy as np
import polars as pl
from numpy.typing import NDArray
from pydantic import JsonValue
from scipy.stats import rankdata

from edaforge.config import Budget
from edaforge.explain.render import render_lenses
from edaforge.models import (
    Candidate,
    ColumnRef,
    Confirmation,
    Effect,
    EvidenceDraft,
    Finding,
    FindingKind,
    Lenses,
    PatternClass,
)
from edaforge.plugins.sdk import AnalysisData, CostEstimate, DataProfile, RunContext, Task
from edaforge.rigor.assumptions import (
    AssumptionSpec,
    lag1_autocorrelation_check,
    min_group_size_check,
)

__all__ = ["MeanShiftAnalyzer", "cohen_d", "mean_diff", "prob_superiority", "welch_t"]

FloatArray = NDArray[np.float64]
_TEST = "welch_t_permutation"
_MIN_GROUP = 10
_BATCH_ELEMENTS = 2_000_000


def welch_t(a: FloatArray, b: FloatArray) -> float:
    """Welch's t for ``mean(b) - mean(a)``; 0 when both groups are constant and equal."""
    va = float(np.var(a, ddof=1))
    vb = float(np.var(b, ddof=1))
    se = np.sqrt(va / a.size + vb / b.size)
    diff = float(b.mean() - a.mean())
    if se == 0.0:
        return 0.0 if diff == 0.0 else float(np.sign(diff)) * 1e12
    return float(diff / se)


def mean_diff(a: FloatArray, b: FloatArray) -> float:
    return float(b.mean() - a.mean())


def cohen_d(a: FloatArray, b: FloatArray) -> float:
    """Standardized mean difference ``(mean(b) - mean(a)) / pooled SD``."""
    na, nb = a.size, b.size
    pooled = ((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2)
    sd = float(np.sqrt(pooled))
    return 0.0 if sd == 0.0 else float((b.mean() - a.mean()) / sd)


def prob_superiority(a: FloatArray, b: FloatArray) -> float:
    """``P(B > A) + P(B = A) / 2`` for random draws (common-language effect size)."""
    ranks = rankdata(np.concatenate([a, b]))
    rank_sum_b = float(ranks[a.size :].sum())
    u_b = rank_sum_b - b.size * (b.size + 1) / 2.0
    return u_b / (a.size * b.size)


def _batch_mean_diff(a: FloatArray, b: FloatArray) -> FloatArray:
    return np.asarray(b.mean(axis=1) - a.mean(axis=1), dtype=np.float64)


def _batch_cohen_d(a: FloatArray, b: FloatArray) -> FloatArray:
    na, nb = a.shape[1], b.shape[1]
    pooled = ((na - 1) * a.var(axis=1, ddof=1) + (nb - 1) * b.var(axis=1, ddof=1)) / (na + nb - 2)
    sd = np.sqrt(pooled)
    diff = b.mean(axis=1) - a.mean(axis=1)
    return np.asarray(np.where(sd > 0, diff / np.where(sd > 0, sd, 1.0), 0.0), dtype=np.float64)


def _permutation_draw(pooled: FloatArray, n_a: int):
    centered = pooled - pooled.mean()
    total = float(centered.sum())
    total_sq = float(np.dot(centered, centered))
    n = centered.size
    n_b = n - n_a

    def draw(rng: np.random.Generator, size: int) -> FloatArray:
        out = np.empty(size, dtype=np.float64)
        rows = max(1, _BATCH_ELEMENTS // max(n, 1))
        done = 0
        while done < size:
            chunk = min(rows, size - done)
            keys = rng.random((chunk, n))
            idx = np.argpartition(keys, n_a - 1, axis=1)[:, :n_a]
            picked = centered[idx]
            sum_a = picked.sum(axis=1)
            sq_a = np.square(picked).sum(axis=1)
            sum_b = total - sum_a
            sq_b = total_sq - sq_a
            mean_a = sum_a / n_a
            mean_b = sum_b / n_b
            var_a = np.maximum(sq_a - n_a * mean_a**2, 0.0) / (n_a - 1)
            var_b = np.maximum(sq_b - n_b * mean_b**2, 0.0) / (n_b - 1)
            se = np.sqrt(var_a / n_a + var_b / n_b)
            t = np.where(se > 0, (mean_b - mean_a) / np.where(se > 0, se, 1.0), 0.0)
            out[done : done + chunk] = np.abs(t)
            done += chunk
        return out

    return draw


def _groups(
    data: pl.DataFrame, params: Mapping[str, JsonValue]
) -> tuple[FloatArray, FloatArray, int]:
    column = str(params["column"])
    env = str(params["env_column"])
    frame = data.select(column, env)
    n_missing = int(frame[column].null_count())
    frame = frame.drop_nulls()
    values = frame[column].cast(pl.Float64)
    labels = frame[env].cast(pl.String)
    a = values.filter(labels == str(params["group_a"])).to_numpy().astype(np.float64)
    b = values.filter(labels == str(params["group_b"])).to_numpy().astype(np.float64)
    return a, b, n_missing


class MeanShiftAnalyzer:
    name: ClassVar[str] = "example.mean_shift"
    version: ClassVar[str] = "0.1.0"
    pattern_class: ClassVar[PatternClass] = PatternClass.ACROSS_FILES
    requires: ClassVar[frozenset[str]] = frozenset({"environment>=2", "numeric>=1"})
    assumptions: ClassVar[Sequence[AssumptionSpec]] = (
        AssumptionSpec(
            name="exchangeability",
            description=(
                "Under the null hypothesis, rows are exchangeable between the two groups."
            ),
            severity="major",
            check=None,
        ),
        AssumptionSpec(
            name="min_group_size",
            description=f"Each group has at least {_MIN_GROUP} non-missing values.",
            severity="major",
            check=min_group_size_check(_MIN_GROUP),
        ),
        AssumptionSpec(
            name="independence",
            description="Rows are independent (weak serial dependence in file order).",
            severity="major",
            check=lag1_autocorrelation_check(None),
            on_fail="caveat",
        ),
    )

    def estimate_cost(self, profile: DataProfile, budget: Budget) -> CostEstimate:
        pairs = max(1, len(profile.environments) * (len(profile.environments) - 1) // 2)
        tests = pairs * len(profile.numeric)
        return CostEstimate(seconds=1e-6 * tests * profile.n_rows * 50, memory_mb=1.0)

    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        env = data.profile.environment_column
        levels = data.profile.environments
        if env is None or len(levels) < 2:
            return []
        return [
            Task(
                key=f"{column}|{group_a}|{group_b}",
                params={
                    "column": column,
                    "env_column": env,
                    "group_a": group_a,
                    "group_b": group_b,
                },
            )
            for column in sorted(data.profile.numeric)
            for i, group_a in enumerate(levels)
            for group_b in levels[i + 1 :]
        ]

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        params = dict(task.params)
        a, b, n_missing = _groups(data, params)
        column, group_a, group_b = (
            str(params["column"]),
            str(params["group_a"]),
            str(params["group_b"]),
        )
        hid = ctx.ledger.register(
            hypothesis=f"the mean of {column} is equal in {group_a} and {group_b}",
            family=["mean_shift", f"env={params['env_column']}"],
            test=_TEST,
            params=task.params,
        )
        if a.size < 2 or b.size < 2 or (np.ptp(a) == 0.0 and np.ptp(b) == 0.0):
            return []  # registered but untestable: counts with p = 1 in the family
        observed = abs(welch_t(a, b))
        result = ctx.ledger.permutation_test(
            hid,
            observed=observed,
            draw=_permutation_draw(np.concatenate([a, b]), a.size),
            n_obs=a.size + b.size,
        )
        return [
            Candidate(
                key=task.key,
                analyzer=self.name,
                kind=FindingKind.DISTRIBUTION_SHIFT,
                pattern_class=self.pattern_class,
                title=f"Average {column} differs between {group_a} and {group_b}",
                variables=[ColumnRef(column=column), ColumnRef(column=str(params["env_column"]))],
                hypothesis_id=hid,
                test=_TEST,
                statistic=observed,
                p_value=result.p_value,
                params=task.params,
                facts={
                    "explore_n": a.size + b.size,
                    "explore_mean_diff": float(b.mean() - a.mean()),
                    "explore_missing": n_missing,
                },
                claimed_rung="R1",
            )
        ]

    def _effects(
        self, cand: Candidate, data: pl.DataFrame, ctx: RunContext, purpose: str
    ) -> tuple[Effect, dict[str, float | int | str], FloatArray, FloatArray]:
        params = dict(cand.params)
        a, b, n_missing = _groups(data, params)
        level = ctx.config.rigor.ci_level
        resamples = ctx.budget_settings.bootstrap_resamples
        diff_ci = ctx.ledger.bootstrap(
            purpose=f"{purpose}:{cand.key}:mean_diff",
            samples=[a, b],
            statistic=mean_diff,
            batch_statistic=_batch_mean_diff,
            n_resamples=resamples,
            level=level,
        )
        d_ci = ctx.ledger.bootstrap(
            purpose=f"{purpose}:{cand.key}:cohen_d",
            samples=[a, b],
            statistic=cohen_d,
            batch_statistic=_batch_cohen_d,
            n_resamples=resamples,
            level=level,
        )
        effect = Effect(
            measure="cohen_d",
            estimate=d_ci.estimate,
            ci_low=d_ci.low,
            ci_high=d_ci.high,
            ci_level=level,
            ci_method=d_ci.method,
            split=ctx.split,
        )
        facts: dict[str, float | int | str] = {
            "column": str(params["column"]),
            "env_column": str(params["env_column"]),
            "group_a": str(params["group_a"]),
            "group_b": str(params["group_b"]),
            "n_a": int(a.size),
            "n_b": int(b.size),
            "n_missing": n_missing,
            "mean_a": float(a.mean()),
            "mean_b": float(b.mean()),
            "mean_diff": diff_ci.estimate,
            "mean_diff_ci_low": diff_ci.low,
            "mean_diff_ci_high": diff_ci.high,
            "prob_superiority": prob_superiority(a, b),
            "bootstrap_resamples": resamples,
            "permutation_h": ctx.config.rigor.permutation_h,
            "permutation_max": ctx.budget_settings.permutation_max,
        }
        return effect, facts, a, b

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        effect, facts, _, _ = self._effects(cand, data, ctx, "refine")
        return cand.model_copy(update={"effect": effect, "facts": {**facts, **cand.facts}})

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        params = dict(cand.params)
        a, b, _ = _groups(sealed, params)
        column, group_a, group_b = (
            str(params["column"]),
            str(params["group_a"]),
            str(params["group_b"]),
        )
        hid = ctx.ledger.register(
            hypothesis=f"the mean of {column} is equal in {group_a} and {group_b} (confirmation)",
            family=["mean_shift", f"env={params['env_column']}", "confirmation"],
            test=_TEST,
            params=cand.params,
            parent_id=cand.hypothesis_id,
        )
        method = "sealed_holdout" if ctx.split == "confirmation" else "cross_fit"
        if a.size < 2 or b.size < 2:
            return EvidenceDraft(
                test=_TEST,
                statistic=cand.statistic,
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id, hid],
                n=a.size + b.size,
                confirmation=Confirmation(
                    status="not_confirmed", method=method, hypothesis_ids=[hid], n=a.size + b.size
                ),
                caveats=["Too few sealed rows in one group to run the confirmation test."],
            )
        observed = abs(welch_t(a, b))
        result = ctx.ledger.permutation_test(
            hid,
            observed=observed,
            draw=_permutation_draw(np.concatenate([a, b]), a.size),
            n_obs=a.size + b.size,
        )
        effect, facts, _, _ = self._effects(cand, sealed, ctx, "confirm")
        facts["confirm_statistic"] = observed
        caveats: list[str] = []
        if int(facts["n_missing"]) > 0:
            caveats.append(
                f"{facts['n_missing']} sealed rows with a missing {column} were excluded "
                "from the confirmation test."
            )
        return EvidenceDraft(
            test=_TEST,
            statistic=cand.statistic,
            p_value=cand.p_value,
            hypothesis_ids=[cand.hypothesis_id, hid],
            n=a.size + b.size,
            confirmation=Confirmation(
                status="pending",
                method=method,
                p_value=result.p_value,
                hypothesis_ids=[hid],
                n=a.size + b.size,
            ),
            effect=effect,
            claimed_rung="R1",
            facts=dict(facts),
            caveats=caveats,
        )

    def render(self, finding: Finding) -> Lenses:
        return render_lenses(finding)
