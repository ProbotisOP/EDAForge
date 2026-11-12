"""Time patterns: changes in level over time.

Rows are aggregated per period (the coarsest of month, week or day that still gives at least 30
periods): the number of rows per period (when rows are events) and the mean of each numeric
column. A CUSUM statistic locates the most likely single change in level; its p-value comes from
a sieve (autoregressive) bootstrap under "no change", which keeps the false-alarm rate near the
nominal level for autocorrelated series. The check on held-out rows tests the *same* date again.
A straight-line trend is compared with the step so that gradual drifts are not called sudden.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, ClassVar, Literal

import numpy as np
import polars as pl
from scipy import stats

from edaforge.discovery import charts
from edaforge.discovery.base import BaseAnalyzer, measure_stability, stability_rng
from edaforge.discovery.stats import (
    FloatArray,
    change_point,
    cusum_null_draw,
    fixed_break_draw,
    fixed_break_stat,
    step_diff_interval,
)
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

__all__ = ["ChangePoints", "choose_grain"]

Grain = Literal["month", "week", "day"]
_MIN_PERIODS = 30
_MIN_PER_PERIOD = 3
ROWS_SERIES = "__rows__"
_TRUNC = {"month": "1mo", "week": "1w", "day": "1d"}


def _period(frame: pl.DataFrame, column: str, grain: Grain) -> pl.Series:
    return frame[column].cast(pl.Datetime("us")).dt.truncate(_TRUNC[grain]).cast(pl.Date)


def choose_grain(frame: pl.DataFrame, column: str) -> tuple[Grain | None, int]:
    """The coarsest grain with at least 30 periods (and, for rows, enough rows per period)."""
    present = frame.filter(pl.col(column).is_not_null())
    if present.height < _MIN_PERIODS * _MIN_PER_PERIOD:
        return None, 0
    for grain in ("month", "week", "day"):
        periods = _period(present, column, grain)
        n = periods.n_unique()
        if n >= _MIN_PERIODS:
            per = present.height / n
            if per >= _MIN_PER_PERIOD or grain == "day":
                return grain, n
    return None, 0


def _series(frame: pl.DataFrame, time: str, value: str, grain: Grain) -> pl.DataFrame:
    periods = _period(frame, time, grain).alias("period")
    data = frame.with_columns(periods).filter(pl.col("period").is_not_null())
    if value == ROWS_SERIES:
        out = (
            data.group_by("period")
            .agg(pl.len().alias("n"))
            .with_columns(pl.col("n").cast(pl.Float64).alias("value"))
        )
    else:
        out = (
            data.filter(pl.col(value).is_not_null())
            .group_by("period")
            .agg(pl.col(value).cast(pl.Float64).mean().alias("value"), pl.len().alias("n"))
            .filter(pl.col("n") >= _MIN_PER_PERIOD)
        )
    return out.sort("period")


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


class ChangePoints(BaseAnalyzer):
    name: ClassVar[str] = "time.change_points"
    pattern_class: ClassVar[PatternClass] = PatternClass.TIME
    label: ClassVar[str] = "Changes over time"
    family: ClassVar[str] = "time"
    template: ClassVar[str] = "change_point"
    method_summary: ClassVar[str] = (
        "CUSUM change in level on per-period means, sieve-bootstrap calibrated; "
        "fixed-date re-test on held-out rows"
    )
    assumptions: ClassVar[Sequence[AssumptionSpec]] = (
        AssumptionSpec(
            name="stationary_noise",
            description=(
                "Apart from a change in level, period-to-period noise is stable "
                "(approximated by an autoregression)."
            ),
            severity="minor",
            check=None,
        ),
        AssumptionSpec(
            name="comparable_periods",
            description=(
                "Every period measures the same thing (no change in definitions or data "
                "collection)."
            ),
            severity="major",
            check=None,
        ),
    )

    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        time = self.spec.time_column
        if time is None:
            return []
        grain, _ = choose_grain(data.frame, time)
        if grain is None:
            return []
        series: list[str] = []
        per = data.frame.height / max(
            _period(data.frame.filter(pl.col(time).is_not_null()), time, grain).n_unique(), 1
        )
        if per >= 2:
            series.append(ROWS_SERIES)
        numeric = list(self.spec.numeric)
        if self.spec.target in numeric:
            numeric.remove(self.spec.target)
            numeric.insert(0, self.spec.target)
        series.extend(numeric[:10])
        tasks = [Task(key=s, params={"series": s, "time": time, "grain": grain}) for s in series]
        self.begin(len(tasks))
        return tasks

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        self.tick(ctx)
        name, time, grain = (
            str(task.params["series"]),
            str(task.params["time"]),
            str(task.params["grain"]),
        )
        label = "number of rows" if name == ROWS_SERIES else f"average {name}"
        hid = ctx.ledger.register(
            hypothesis=f"the {label} per {grain} has a constant level",
            family=["change_points"],
            test="cusum_sieve_bootstrap",
            params=dict(task.params),
        )
        s = _series(data, time, name, grain)  # pyright: ignore[reportArgumentType]
        if s.height < _MIN_PERIODS:
            return []
        y = s["value"].to_numpy()
        if float(np.ptp(y)) == 0:
            return []
        cp = change_point(y)
        result = ctx.ledger.permutation_test(
            hid, observed=float(cp["statistic"]), draw=cusum_null_draw(y), n_obs=int(y.size)
        )
        break_period = _iso(s["period"][int(cp["index"])])
        return [
            Candidate(
                key=task.key,
                analyzer=self.name,
                kind=FindingKind.CHANGE_POINT,
                pattern_class=self.pattern_class,
                title=f"The {label} changed around {break_period}",
                variables=[ColumnRef(column=time)]
                + ([] if name == ROWS_SERIES else [ColumnRef(column=name)]),
                hypothesis_id=hid,
                test="cusum_sieve_bootstrap",
                statistic=float(cp["statistic"]),
                p_value=result.p_value,
                params={**task.params, "break": break_period},
                facts={"explore_periods": int(y.size), "explore_diff": float(cp["diff"])},
            )
        ]

    def _measure(
        self, cand: Candidate, data: pl.DataFrame, ctx: RunContext, purpose: str
    ) -> tuple[Effect | None, dict[str, Any], FloatArray, int]:
        name, time, grain = (
            str(cand.params["series"]),
            str(cand.params["time"]),
            str(cand.params["grain"]),
        )
        brk = date.fromisoformat(str(cand.params["break"]))
        s = _series(data, time, name, grain)  # pyright: ignore[reportArgumentType]
        y = s["value"].to_numpy()
        periods = [_iso(p) for p in s["period"].to_list()]
        k = int(
            np.searchsorted(
                np.array(s["period"].to_list(), dtype="datetime64[D]"), np.datetime64(brk)
            )
        )
        facts: dict[str, Any] = {
            "template": self.template,
            "series": name,
            "rows_series": name == ROWS_SERIES,
            "time": time,
            "grain": grain,
            "break": brk.isoformat(),
            "n_periods": int(y.size),
            "label": "number of rows" if name == ROWS_SERIES else f"average {name}",
            "points": [
                {"period": p, "value": float(v), "n": int(c)}
                for p, v, c in zip(periods, y.tolist(), s["n"].to_list(), strict=True)
            ],
        }
        if k < 5 or y.size - k < 5:
            return None, facts, y, k
        before, after = y[:k], y[k:]
        diff = float(after.mean() - before.mean())
        lo, hi = step_diff_interval(y, k, ctx.ledger.rng(f"{purpose}:{cand.key}:step_ci"))
        sd = float(np.std(y, ddof=1)) or 1.0
        cp = change_point(y)
        facts.update(
            {
                "mean_before": float(before.mean()),
                "mean_after": float(after.mean()),
                "diff": diff,
                "diff_low": lo,
                "diff_high": hi,
                "pct_change": diff / abs(float(before.mean())) if before.mean() != 0 else None,
                "periods_before": int(k),
                "periods_after": int(y.size - k),
                "std_shift": diff / sd,
                "gradual": bool(
                    cp["sse_trend"]
                    < float(
                        np.sum((before - before.mean()) ** 2) + np.sum((after - after.mean()) ** 2)
                    )
                ),
                "first_period": periods[0],
                "last_period": periods[-1],
            }
        )
        effect = Effect(
            measure="std_shift",
            estimate=diff / sd,
            ci_low=lo / sd,
            ci_high=hi / sd,
            ci_method="sieve-bootstrap percentile",
            split=ctx.split,
        )
        return effect, facts, y, k

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        effect, facts, _, _ = self._measure(cand, data, ctx, "refine")
        return cand.model_copy(update={"effect": effect, "facts": {**facts, **cand.facts}})

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        hid = ctx.ledger.register(
            hypothesis=f"no change in level at {cand.params['break']} (confirmation)",
            family=["change_points", "confirmation"],
            test="fixed_break_sieve_bootstrap",
            params=dict(cand.params),
            parent_id=cand.hypothesis_id,
        )
        method = "sealed_holdout" if ctx.split == "confirmation" else "cross_fit"
        effect, facts, y, k = self._measure(cand, sealed, ctx, "confirm")
        if effect is None:
            ctx.ledger.mark_untestable(
                hid, reason="too few periods on one side of the date set aside", n_obs=int(y.size)
            )
            return EvidenceDraft(
                test="cusum_sieve_bootstrap",
                statistic=cand.statistic,
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id, hid],
                n=int(y.size),
                confirmation=Confirmation(
                    status="not_confirmed", method=method, hypothesis_ids=[hid]
                ),
                facts=facts,
                caveats=[
                    "Too few periods on one side of the date in the data set aside for the check."
                ],
            )
        result = ctx.ledger.permutation_test(
            hid,
            observed=fixed_break_stat(y, k),
            draw=fixed_break_draw(y, k),
            n_obs=int(y.size),
            n_max=5000,
        )
        sign = np.sign(effect.estimate) or 1.0
        name, time, grain = (
            str(cand.params["series"]),
            str(cand.params["time"]),
            str(cand.params["grain"]),
        )
        brk = np.datetime64(date.fromisoformat(str(cand.params["break"])))

        def holds(idx: np.ndarray[Any, np.dtype[np.int64]]) -> bool:
            sub = _series(sealed[idx], time, name, grain)  # pyright: ignore[reportArgumentType]
            values = sub["value"].to_numpy()
            kk = int(np.searchsorted(np.array(sub["period"].to_list(), dtype="datetime64[D]"), brk))
            if kk < 3 or values.size - kk < 3:
                return False
            res = stats.mannwhitneyu(values[kk:], values[:kk])
            return bool(
                res.pvalue < 0.05 and np.sign(values[kk:].mean() - values[:kk].mean()) == sign
            )

        stability = measure_stability(sealed.height, stability_rng(ctx, cand.key), holds, rounds=25)
        mw = stats.mannwhitneyu(y[k:], y[:k])
        specs = [
            {"name": "sieve-bootstrap test at the date", "agrees": (result.p_value or 1.0) < 0.05},
            {"name": "Mann-Whitney on periods before vs after", "agrees": bool(mw.pvalue < 0.05)},
            {
                "name": "difference of medians has the same sign",
                "agrees": bool(np.sign(np.median(y[k:]) - np.median(y[:k])) == sign),
            },
        ]
        facts["specs"] = specs
        facts["stability"] = stability
        caveats = [
            "A change in level over time is a description; it does not say why the level changed."
        ]
        if facts.get("gradual"):
            caveats.append(
                "A straight-line trend fits these periods about as well as a sudden "
                "step, so the change may be gradual."
            )
        if facts["rows_series"]:
            caveats.append(
                "Row counts in the check data are a fixed share of the totals; the size "
                "of the change is relative."
            )
        return EvidenceDraft(
            test="cusum_sieve_bootstrap",
            statistic=cand.statistic,
            p_value=cand.p_value,
            hypothesis_ids=[cand.hypothesis_id, hid],
            n=int(y.size),
            confirmation=Confirmation(
                status="pending",
                method=method,
                p_value=result.p_value,
                hypothesis_ids=[hid],
                n=int(y.size),
            ),
            effect=effect,
            stability=stability,
            specs_consistent=sum(1 for s in specs if s["agrees"]),
            specs_total=len(specs),
            facts=facts,
            caveats=caveats,
        )

    def charts(self, finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
        return charts.change_point(finding)
