"""Cross-file (and cross-group) differences: distribution shift and recording mismatches.

Applies when the analyzed table has an environment column: ``__source__`` for appended files,
or a group column the user chose to compare. For every numeric column and every pair of files:
the two-sample Kolmogorov-Smirnov test (any difference in distribution), medians, means and
Cohen's d with a BCa interval. A ratio of medians close to ×100 or ×1,000 is flagged as a
possible unit difference ("recorded differently"). For categorical columns: the chi-square test
of the label shares, and labels that appear in one file only.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np
import polars as pl
from scipy import stats

from edaforge.discovery import charts
from edaforge.discovery.base import BaseAnalyzer, measure_stability, stability_rng
from edaforge.discovery.relationships import _batch_cohen_d, _cohen_d  # pyright: ignore[reportPrivateUsage]
from edaforge.discovery.stats import FloatArray
from edaforge.link import unit_hint
from edaforge.models import (
    Candidate,
    ChartSpec,
    ColumnRef,
    Confirmation,
    Effect,
    EvidenceDraft,
    Finding,
    FindingKind,
    PatternClass,
)
from edaforge.plugins.sdk import AnalysisData, RunContext, Task
from edaforge.rigor.assumptions import AssumptionSpec

__all__ = ["CrossFile", "unit_hint"]


class CrossFile(BaseAnalyzer):
    name: ClassVar[str] = "across.files"
    pattern_class: ClassVar[PatternClass] = PatternClass.ACROSS_FILES
    label: ClassVar[str] = "Differences between files or groups"
    family: ClassVar[str] = "cross_file"
    template: ClassVar[str] = "cross_file"
    method_summary: ClassVar[str] = (
        "Two-sample Kolmogorov-Smirnov and chi-square tests per column and pair of sources"
    )
    assumptions: ClassVar[Sequence[AssumptionSpec]] = (
        AssumptionSpec(
            name="same_definition",
            description=(
                "The column means the same thing in every source; a shift can be a real "
                "difference or a recording difference."
            ),
            severity="major",
            check=None,
        ),
    )

    def _pairs(self) -> list[tuple[str, str]]:
        env = self.spec.environment
        if env is None:
            return []
        return list(itertools.combinations(self.spec.levels.get(env, ()), 2))[:6]

    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        env = self.spec.environment
        if env is None:
            return []
        numeric, categorical = self.spec.predictors()
        # Columns on different scales in different files are compared here, and only here.
        numeric = [*numeric, *(c for c in self.spec.across_only if c not in numeric)]
        tasks: list[Task] = []
        for a, b in self._pairs():
            tasks.extend(
                Task(
                    key=f"n|{column}|{a}|{b}",
                    params={"column": column, "env": env, "a": a, "b": b, "numeric": True},
                )
                for column in numeric
            )
            tasks.extend(
                Task(
                    key=f"c|{column}|{a}|{b}",
                    params={"column": column, "env": env, "a": a, "b": b, "numeric": False},
                )
                for column in categorical
            )
        self.begin(len(tasks))
        return tasks

    def _split(self, frame: pl.DataFrame, params: dict[str, Any]) -> tuple[pl.Series, pl.Series]:
        column, env = str(params["column"]), str(params["env"])
        rows = frame.select(column, env).drop_nulls()
        labels = rows[env].cast(pl.String)
        return rows[column].filter(labels == str(params["a"])), rows[column].filter(
            labels == str(params["b"])
        )

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        self.tick(ctx)
        params = dict(task.params)
        column, a, b = str(params["column"]), str(params["a"]), str(params["b"])
        numeric = bool(params["numeric"])
        test = "ks_2samp" if numeric else "chi_square"
        hid = ctx.ledger.register(
            hypothesis=f"{column} has the same distribution in {a} and {b}",
            family=["cross_file", "numeric" if numeric else "categorical"],
            test=test,
            params=params,
        )
        sa, sb = self._split(data, params)
        if sa.len() < self.spec.min_cell or sb.len() < self.spec.min_cell:
            return []
        if numeric:
            va, vb = sa.cast(pl.Float64).to_numpy(), sb.cast(pl.Float64).to_numpy()
            res = stats.ks_2samp(va, vb)
            stat, p = float(res.statistic), float(res.pvalue)
        else:
            table = _table(sa, sb)
            if table.shape[1] < 2:
                return []
            chi = stats.chi2_contingency(table, correction=False)
            stat, p = float(chi.statistic), float(chi.pvalue)
        result = ctx.ledger.analytic_test(
            hid, statistic=stat, p_value=p, n_obs=int(sa.len() + sb.len())
        )
        return [
            Candidate(
                key=task.key,
                analyzer=self.name,
                kind=FindingKind.DISTRIBUTION_SHIFT,
                pattern_class=self.pattern_class,
                title=f"{column} differs between {a} and {b}",
                variables=[ColumnRef(column=column), ColumnRef(column=str(params["env"]))],
                hypothesis_id=hid,
                test=test,
                statistic=stat,
                p_value=result.p_value,
                params=params,
                facts={"explore_n": int(sa.len() + sb.len())},
            )
        ]

    def _measure(
        self, cand: Candidate, data: pl.DataFrame, ctx: RunContext, purpose: str
    ) -> tuple[Effect, dict[str, Any], Any, Any]:
        params = dict(cand.params)
        column, a, b = str(params["column"]), str(params["a"]), str(params["b"])
        sa, sb = self._split(data, params)
        facts: dict[str, Any] = {
            "template": self.template,
            "column": column,
            "env": params["env"],
            "a": a,
            "b": b,
            "n_a": int(sa.len()),
            "n_b": int(sb.len()),
            "numeric": bool(params["numeric"]),
            "env_label": self.spec.environment_label,
        }
        if params["numeric"]:
            va, vb = sa.cast(pl.Float64).to_numpy(), sb.cast(pl.Float64).to_numpy()
            ma, mb = float(np.median(va)), float(np.median(vb))
            ratio = mb / ma if ma != 0.0 and np.sign(ma) == np.sign(mb) else None
            d = ctx.ledger.bootstrap(
                purpose=f"{purpose}:{cand.key}:cohen_d",
                samples=[va, vb],
                statistic=_cohen_d,
                batch_statistic=_batch_cohen_d,
                n_resamples=ctx.budget_settings.bootstrap_resamples,
                level=ctx.config.rigor.ci_level,
            )
            ks = stats.ks_2samp(va, vb)
            facts.update(
                {
                    "median_a": ma,
                    "median_b": mb,
                    "mean_a": float(va.mean()),
                    "mean_b": float(vb.mean()),
                    "q1_a": float(np.quantile(va, 0.25)),
                    "q3_a": float(np.quantile(va, 0.75)),
                    "q1_b": float(np.quantile(vb, 0.25)),
                    "q3_b": float(np.quantile(vb, 0.75)),
                    "ratio": ratio,
                    "unit_hint": unit_hint(ratio),
                    "ks_d": float(ks.statistic),
                    "cohen_d": d.estimate,
                    "cohen_d_low": d.low,
                    "cohen_d_high": d.high,
                }
            )
            effect = Effect(
                measure="ks_d",
                estimate=float(ks.statistic),
                ci_low=None,
                ci_high=None,
                split=ctx.split,
            )
            return effect, facts, va, vb
        table = _table(sa, sb)
        levels = _levels(sa, sb)
        shares: list[dict[str, Any]] = []
        for j, lv in enumerate(levels):
            shares.append(
                {
                    "level": lv,
                    "share_a": float(table[0, j] / max(table[0].sum(), 1)),
                    "share_b": float(table[1, j] / max(table[1].sum(), 1)),
                    "n_a": int(table[0, j]),
                    "n_b": int(table[1, j]),
                }
            )
        only_a = [s["level"] for s in shares if s["n_a"] and not s["n_b"]]
        only_b = [s["level"] for s in shares if s["n_b"] and not s["n_a"]]
        chi = stats.chi2_contingency(table, correction=False) if table.shape[1] >= 2 else None
        v = math.sqrt(float(chi.statistic) / table.sum()) if chi is not None else 0.0
        facts.update(
            {
                "shares": sorted(shares, key=lambda s: -abs(s["share_a"] - s["share_b"]))[:10],
                "only_a": only_a[:10],
                "only_b": only_b[:10],
                "cramers_v": v,
            }
        )
        effect = Effect(measure="cramers_v", estimate=v, split=ctx.split)
        return effect, facts, table, None

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        effect, facts, _, _ = self._measure(cand, data, ctx, "refine")
        return cand.model_copy(update={"effect": effect, "facts": {**facts, **cand.facts}})

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        params = dict(cand.params)
        hid = ctx.ledger.register(
            hypothesis=(
                f"{params['column']} has the same distribution in {params['a']} and "
                f"{params['b']} (confirmation)"
            ),
            family=["cross_file", "confirmation"],
            test=cand.test,
            params=params,
            parent_id=cand.hypothesis_id,
        )
        method = "sealed_holdout" if ctx.split == "confirmation" else "cross_fit"
        sa, sb = self._split(sealed, params)
        if sa.len() < self.spec.min_cell or sb.len() < self.spec.min_cell:
            ctx.ledger.mark_untestable(
                hid,
                reason="too few rows of one source set aside for the check",
                n_obs=int(sa.len() + sb.len()),
            )
            return EvidenceDraft(
                test=cand.test,
                statistic=cand.statistic,
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id, hid],
                n=int(sa.len() + sb.len()),
                confirmation=Confirmation(
                    status="not_confirmed", method=method, hypothesis_ids=[hid]
                ),
                caveats=["Too few rows of one source in the data set aside for the check."],
            )
        effect, facts, xa, xb = self._measure(cand, sealed, ctx, "confirm")
        if params["numeric"]:
            va: FloatArray = xa
            vb: FloatArray = xb
            res = stats.ks_2samp(va, vb)
            stat, p = float(res.statistic), float(res.pvalue)
            pooled = np.concatenate([va, vb])
            labels = np.r_[np.zeros(va.size), np.ones(vb.size)]

            def holds(idx: np.ndarray[Any, np.dtype[np.int64]]) -> bool:
                pa, pb = pooled[idx][labels[idx] == 0], pooled[idx][labels[idx] == 1]
                return bool(pa.size >= 5 and pb.size >= 5 and stats.ks_2samp(pa, pb).pvalue < 0.05)

            n = int(pooled.size)
            specs = [
                {"name": "Kolmogorov-Smirnov", "agrees": p < 0.05},
                {
                    "name": "Mann-Whitney U",
                    "agrees": bool(stats.mannwhitneyu(va, vb).pvalue < 0.05),
                },
                {
                    "name": "Welch t-test",
                    "agrees": bool(stats.ttest_ind(va, vb, equal_var=False).pvalue < 0.05),
                },
            ]
        else:
            table: FloatArray = xa
            chi = stats.chi2_contingency(table, correction=False)
            stat, p = float(chi.statistic), float(chi.pvalue)
            n = int(table.sum())
            g = stats.chi2_contingency(table, correction=False, lambda_="log-likelihood")
            rows = np.repeat(np.arange(2), table.sum(axis=1).astype(int))
            counts: np.ndarray[Any, np.dtype[np.int64]] = table.astype(np.int64)
            column_ids = np.arange(int(table.shape[1]))
            cols = np.concatenate([np.repeat(column_ids, row) for row in counts])

            def holds(idx: np.ndarray[Any, np.dtype[np.int64]]) -> bool:
                sub = np.zeros_like(table)
                np.add.at(sub, (rows[idx], cols[idx]), 1)
                sub = sub[:, sub.sum(axis=0) > 0]
                if sub.shape[1] < 2:
                    return False
                return bool(stats.chi2_contingency(sub, correction=False).pvalue < 0.05)

            specs = [
                {"name": "Pearson chi-square", "agrees": p < 0.05},
                {"name": "likelihood-ratio G-test", "agrees": bool(g.pvalue < 0.05)},
            ]
        result = ctx.ledger.analytic_test(hid, statistic=stat, p_value=p, n_obs=n)
        stability = measure_stability(n, stability_rng(ctx, cand.key), holds)
        facts["specs"] = specs
        facts["stability"] = stability
        caveats: list[str] = []
        if facts.get("unit_hint"):
            caveats.append(
                f"The typical values differ by about {facts['unit_hint']}, which often means "
                f"the files record {facts['column']} in "
                "different units (for example cents and dollars). Check before combining them."
            )
        return EvidenceDraft(
            test=cand.test,
            statistic=cand.statistic,
            p_value=cand.p_value,
            hypothesis_ids=[cand.hypothesis_id, hid],
            n=n,
            confirmation=Confirmation(
                status="pending", method=method, p_value=result.p_value, hypothesis_ids=[hid], n=n
            ),
            effect=effect,
            stability=stability,
            specs_consistent=sum(1 for s in specs if s["agrees"]),
            specs_total=len(specs),
            facts=facts,
            caveats=caveats,
        )

    def charts(self, finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
        return charts.cross_file(finding, frame)


def _levels(sa: pl.Series, sb: pl.Series) -> list[str]:
    return sorted(
        {str(v) for v in sa.cast(pl.String).to_list()}
        | {str(v) for v in sb.cast(pl.String).to_list()}
    )


def _table(sa: pl.Series, sb: pl.Series) -> FloatArray:
    levels = _levels(sa, sb)
    index = {lv: j for j, lv in enumerate(levels)}
    table = np.zeros((2, len(levels)))
    for i, series in enumerate((sa, sb)):
        for value in series.cast(pl.String).to_list():
            table[i, index[str(value)]] += 1
    return table
