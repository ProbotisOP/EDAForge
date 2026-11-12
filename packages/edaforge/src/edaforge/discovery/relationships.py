"""Relationship screens: numbers vs numbers, numbers across groups, categories vs categories.

* :class:`NumericPairs` — any smooth dependence between two numeric columns. Screening statistic:
  the larger R² of a restricted cubic spline fit in either direction, calibrated by permutation
  (valid under exchangeability, robust to outliers and skew). Spearman and Pearson correlations
  are reported as effect sizes; a nested F-test (spline vs straight line) decides whether the
  relationship is called non-linear, and the fitted curve classifies its shape.
* :class:`GroupDifferences` — a numeric column across the levels of a category: Kruskal-Wallis
  (rank-based, outlier-robust), ε² with a BCa interval, group means with t intervals and, for
  two groups, Cohen's d.
* :class:`CategoryAssociations` — two categorical columns: Pearson's chi-square (Monte Carlo
  version when expected counts are small) and Cramér's V.
"""

from __future__ import annotations

import contextlib
import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import numpy as np
import polars as pl
from scipy import stats

from edaforge.discovery import charts
from edaforge.discovery.base import (
    BaseAnalyzer,
    Unit,
    binary_array,
    independence_check,
    measure_stability,
    stability_rng,
    unit_rows,
    widen,
)
from edaforge.discovery.grain import deflate_chi2, deflate_f, deflate_z
from edaforge.discovery.stats import (
    FloatArray,
    bonett_wright_ci,
    fisher_ci,
    rank,
    spearman,
    spline_fit,
    spline_r2_draw,
    spline_r2_pair,
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
from edaforge.rigor.assumptions import AssumptionSpec, CheckOutcome

__all__ = ["CategoryAssociations", "GroupDifferences", "NumericPairs"]

_MIN_N = 30
# Small tables (SMALL_MIN_N to _MIN_N rows): only permutation tests, whose null distribution is
# exact at any size; the kernel's small-sample mode marks every finding exploratory (grade <= D).
SMALL_MIN_N = 8


def _rank_r2_draw(
    x: np.ndarray[Any, Any], y: np.ndarray[Any, Any]
) -> Callable[[np.random.Generator, int], np.ndarray[Any, Any]]:
    """Null draws of Spearman rho squared (permute y against x)."""
    rx, ry = rank(x), rank(y)
    rx, ry = rx - rx.mean(), ry - ry.mean()
    scale = float(np.sqrt((rx @ rx) * (ry @ ry)))

    def draw(rng: np.random.Generator, size: int) -> np.ndarray[Any, Any]:
        perm = rng.permuted(np.tile(ry, (size, 1)), axis=1)
        return ((perm @ rx) / scale) ** 2

    return draw


def _kruskal_draw(
    arrays: list[np.ndarray[Any, Any]],
) -> Callable[[np.random.Generator, int], np.ndarray[Any, Any]]:
    """Null draws of the Kruskal-Wallis H statistic (permute the group labels)."""
    values = np.concatenate(arrays)
    labels = np.concatenate([np.full(a.size, k) for k, a in enumerate(arrays)])
    k = len(arrays)

    def draw(rng: np.random.Generator, size: int) -> np.ndarray[Any, Any]:
        out = np.empty(size)
        for i in range(size):
            lab = rng.permutation(labels)
            h, _ = stats.kruskal(*[values[lab == j] for j in range(k)])
            out[i] = h if math.isfinite(float(h)) else 0.0
        return out

    return draw


def _method(ctx: RunContext) -> Literal["sealed_holdout", "cross_fit"]:
    return "sealed_holdout" if ctx.split == "confirmation" else "cross_fit"


def _n_eff(n: int, deff: float) -> int:
    """Rows counted as independent observations after the design-effect correction."""
    return max(4, round(n / deff)) if deff > 1.0 else n


def unit_caveat(unit: Unit, deff: float) -> list[str]:
    """Plain-language note on how repeated rows were handled (shown with the finding)."""
    if unit.level == "entity" and unit.entity:
        return [
            (
                f"Compared using one row per {unit.entity} ({unit.n_units:,} {unit.entity} "
                f"values), because every column here describes a {unit.entity}."
            )
        ]
    if unit.level == "clustered" and unit.entity and deff > 1.05:
        return [
            (
                f"Rows repeat per {unit.entity} ({unit.n_rows:,} rows from {unit.n_units:,} "
                f"{unit.entity} values), so they are not "
                f"independent: the test counts them as about {_n_eff(unit.n_rows, deff):,} "
                f"independent rows (design effect {deff:.2f})."
            )
        ]
    return []


def _distinct_check(keys: tuple[str, ...], minimum: int = 10) -> AssumptionSpec:
    def check(data: pl.DataFrame, params: Any) -> CheckOutcome:
        worst = None
        for key in keys:
            column = params.get(key)
            if isinstance(column, str) and column in data.columns:
                d = int(data[column].drop_nulls().n_unique())
                worst = d if worst is None else min(worst, d)
        if worst is None:
            return CheckOutcome(status="not_checked", detail="no columns")
        return CheckOutcome(
            status="pass" if worst >= minimum else "fail",
            statistic=float(worst),
            detail=f"fewest distinct values among the analyzed columns: {worst} (need {minimum})",
        )

    return AssumptionSpec(
        name="enough_distinct_values",
        description=f"Each numeric column has at least {minimum} distinct values.",
        severity="major",
        check=check,
    )


# ====================================================================== numbers vs numbers


def _shape(curve: FloatArray, nonlinear: bool) -> str:
    span = float(curve.max() - curve.min())
    d = np.diff(curve)
    if span == 0:
        return "flat"
    tol = 0.02 * span
    up = bool(np.all(d >= -tol))
    down = bool(np.all(d <= tol))
    if not nonlinear:
        return "increasing" if curve[-1] >= curve[0] else "decreasing"
    third = max(1, d.size // 3)
    start, end = abs(float(d[:third].mean())), abs(float(d[-third:].mean()))
    if up or down:
        word = "rises" if up else "falls"
        if end <= 0.35 * start:
            return f"{word} then flattens"
        if start <= 0.35 * end:
            return f"flat, then {word} steeply"
        return f"{word} along a curve"
    i_max, i_min = int(curve.argmax()), int(curve.argmin())
    lo, hi = 0.15 * curve.size, 0.85 * curve.size
    if lo < i_max < hi and curve[i_max] - max(curve[0], curve[-1]) >= 0.25 * span:
        return "inverted U-shaped"
    if lo < i_min < hi and min(curve[0], curve[-1]) - curve[i_min] >= 0.25 * span:
        return "U-shaped"
    return "non-monotonic"


class NumericPairs(BaseAnalyzer):
    name: ClassVar[str] = "relate.numeric_pairs"
    pattern_class: ClassVar[PatternClass] = PatternClass.SHAPE
    label: ClassVar[str] = "Relationships between numeric columns"
    family: ClassVar[str] = "relationships"
    template: ClassVar[str] = "numeric_pair"
    method_summary: ClassVar[str] = (
        "Spline R² in either direction, permutation-calibrated; Spearman and Pearson effect sizes; "
        "nested F-test for non-linearity"
    )
    assumptions: ClassVar[Sequence[AssumptionSpec]] = (
        AssumptionSpec(
            name="exchangeability",
            description=(
                "Under no relationship, the pairing of the two columns is arbitrary (rows "
                "are exchangeable)."
            ),
            severity="major",
            check=None,
        ),
        AssumptionSpec(
            name="independence",
            description="Rows are independent (weak serial dependence in file order).",
            severity="major",
            check=independence_check(("x", "y")),
            on_fail="caveat",
        ),
        _distinct_check(("x", "y")),
    )

    def pairs(self) -> list[tuple[str, str]]:
        numeric = list(self.spec.numeric)
        if self.spec.target and self.spec.target_kind == "numeric" and self.spec.intent == "target":
            return [(x, self.spec.target) for x in numeric if x != self.spec.target]
        return list(itertools.combinations(numeric, 2))

    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        tasks = [Task(key=f"{x}|{y}", params={"x": x, "y": y}) for x, y in self.pairs()]
        self.begin(len(tasks))
        return tasks

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        x_name, y_name = str(task.params["x"]), str(task.params["y"])
        hid = ctx.ledger.register(
            hypothesis=f"{x_name} and {y_name} are independent",
            family=["numeric_pairs"],
            test="spline_r2_permutation",
            params=task.params,
        )
        self.tick(ctx)
        rows, missing, unit = self.unit_rows(data, [x_name, y_name])
        if rows.height < SMALL_MIN_N:
            ctx.ledger.mark_untestable(
                hid, reason=f"fewer than {SMALL_MIN_N} complete rows", n_obs=rows.height
            )
            return []
        x = rows[x_name].cast(pl.Float64).to_numpy()
        y = rows[y_name].cast(pl.Float64).to_numpy()
        if float(x.std()) == 0 or float(y.std()) == 0:
            ctx.ledger.mark_untestable(hid, reason="a column is constant", n_obs=rows.height)
            return []
        rho, _ = spearman(x, y)
        deff = unit.deff(unit.side_icc(x_name, x), unit.side_icc(y_name, y))
        if rows.height < _MIN_N:
            # Too few rows for a flexible curve: test the monotone (rank) association instead.
            observed, r2_yx, r2_xy = rho * rho, rho * rho, rho * rho
            draw = _rank_r2_draw(x, y)
        else:
            observed, r2_yx, r2_xy = spline_r2_pair(x, y)
            draw = spline_r2_draw(x, y)
        # R² behaves like chi-square / n; with repeated rows its null spread grows by the design
        # effect, so the observed value is deflated before comparing it with row permutations.
        result = ctx.ledger.permutation_test(
            hid, observed=observed / deff, draw=draw, n_obs=rows.height
        )
        return [
            Candidate(
                key=task.key,
                analyzer=self.name,
                kind=FindingKind.ASSOCIATION,
                pattern_class=self.pattern_class,
                title=f"{y_name} is associated with {x_name}",
                variables=[ColumnRef(column=x_name), ColumnRef(column=y_name)],
                hypothesis_id=hid,
                test="spline_r2_permutation",
                statistic=observed / deff,
                p_value=result.p_value,
                params=dict(task.params),
                facts={
                    "explore_n": rows.height,
                    "explore_missing": missing,
                    "explore_r2": observed,
                    "explore_rho": rho,
                    "explore_r2_yx": r2_yx,
                    "explore_r2_xy": r2_xy,
                    "explore_distinct_x": int(np.unique(x).size),
                    "explore_distinct_y": int(np.unique(y).size),
                    **unit.facts(deff, prefix="explore_"),
                },
            )
        ]

    def _orient(self, cand: Candidate) -> tuple[str, str]:
        """(predictor, outcome): the target if one is set, else a setting-like column, else the
        better-explained direction.

        A column with few distinct values next to a continuous one (a discount level, a dose, a
        number of days) is read as the predictor: "amount rises with discount", not the reverse.
        """
        x, y = str(cand.params["x"]), str(cand.params["y"])
        if self.spec.target == x:
            return y, x
        if self.spec.target == y:
            return x, y
        dx = int(cand.facts.get("explore_distinct_x", 0) or 0)  # pyright: ignore[reportArgumentType]
        dy = int(cand.facts.get("explore_distinct_y", 0) or 0)  # pyright: ignore[reportArgumentType]
        if 0 < dx <= 25 and dy >= 4 * dx:
            return x, y
        if 0 < dy <= 25 and dx >= 4 * dy:
            return y, x
        a = float(cand.facts.get("explore_r2_yx", 0.0) or 0.0)  # pyright: ignore[reportArgumentType]
        b = float(cand.facts.get("explore_r2_xy", 0.0) or 0.0)  # pyright: ignore[reportArgumentType]
        return (x, y) if a >= b else (y, x)

    def _measure(
        self,
        cand: Candidate,
        data: pl.DataFrame,
        ctx: RunContext,
        purpose: str,
        register_shape: bool,
    ) -> tuple[Effect, dict[str, Any], list[Effect], dict[str, Any]]:
        pred, out = self._orient(cand)
        rows, missing, unit = self.unit_rows(data, [pred, out])
        x = rows[pred].cast(pl.Float64).to_numpy()
        y = rows[out].cast(pl.Float64).to_numpy()
        n = x.size
        deff = unit.deff(unit.side_icc(pred, x), unit.side_icc(out, y))
        n_eff = _n_eff(n, deff)
        rho, _ = spearman(x, y)
        rho_lo, rho_hi = bonett_wright_ci(rho, n_eff)
        r = float(np.corrcoef(x, y)[0, 1]) if n > 2 else 0.0
        r_lo, r_hi = fisher_ci(r, n_eff)
        q05, q95 = (float(v) for v in np.quantile(x, [0.05, 0.95]))
        grid = np.linspace(q05, q95, 60) if q95 > q05 else np.array([q05])
        fit = spline_fit(x, y, grid)
        delta = fit["r2_spline"] - fit["r2_linear"]
        p_nonlinear = None
        nonlinear = False
        extra: dict[str, Any] = {}
        if register_shape and fit["knots"]:
            hid = ctx.ledger.register(
                hypothesis=f"the relationship of {out} with {pred} is a straight line",
                family=["numeric_pairs", "shape"],
                test="nested_F(restricted cubic spline vs linear)",
                params={"x": pred, "y": out},
                parent_id=cand.hypothesis_id,
            )
            df1, df2 = (float(v) for v in fit["df_nonlinear"])
            f_stat, f_p = deflate_f(float(fit["f_nonlinear"]), df1, df2, deff)
            res = ctx.ledger.analytic_test(hid, statistic=f_stat, p_value=f_p, n_obs=n)
            p_nonlinear = res.p_value
            extra["shape_hypothesis_id"] = hid
            nonlinear = bool(
                p_nonlinear is not None
                and p_nonlinear < 0.01
                and delta >= 0.01
                and delta >= 0.1 * fit["r2_spline"]
            )
        shape = _shape(np.asarray(fit["curve"], dtype=np.float64), nonlinear)
        ci_method = "Bonett-Wright (2000) Fisher-z interval"
        if deff > 1.0:
            ci_method += f", effective n {n_eff:,} (design effect {deff:.2f})"
        effect = Effect(
            measure="spearman_rho",
            estimate=rho,
            ci_low=rho_lo,
            ci_high=rho_hi,
            ci_level=0.95,
            ci_method=ci_method,
            split=ctx.split,
        )
        secondary = [
            Effect(
                measure="pearson_r",
                estimate=r,
                ci_low=r_lo,
                ci_high=r_hi,
                ci_method="Fisher z" + (f", effective n {n_eff:,}" if deff > 1.0 else ""),
                split=ctx.split,
            )
        ]
        facts: dict[str, Any] = {
            "template": self.template,
            **unit.facts(deff),
            "x": pred,
            "y": out,
            "n": n,
            "n_missing": missing,
            "rho": rho,
            "rho_low": rho_lo,
            "rho_high": rho_hi,
            "r": r,
            "r_low": r_lo,
            "r_high": r_hi,
            "r2_spline": fit["r2_spline"],
            "r2_linear": fit["r2_linear"],
            "r2_gain": delta,
            "nonlinear": nonlinear,
            "p_nonlinear": p_nonlinear,
            "f_nonlinear": fit["f_nonlinear"],
            "df_nonlinear": list(fit["df_nonlinear"]),
            "shape": shape,
            "knots": fit["knots"],
            "x_low": q05,
            "x_high": q95,
            "y_at_low": float(fit["curve"][0]),
            "y_at_high": float(fit["curve"][-1]),
            "y_min_fit": float(np.min(fit["curve"])),
            "y_max_fit": float(np.max(fit["curve"])),
            "x_at_max": float(grid[int(np.argmax(fit["curve"]))]),
            "x_at_min": float(grid[int(np.argmin(fit["curve"]))]),
            "y_median": float(np.median(y)),
            "kind_label": "Non-linear relationship" if nonlinear else "Association",
        }
        facts.update(extra)
        return (
            effect,
            facts,
            secondary,
            {"x": x, "y": y, "codes": unit.codes, "deff": deff, "unit": unit},
        )

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        effect, facts, _, _ = self._measure(cand, data, ctx, "refine", register_shape=False)
        return cand.model_copy(update={"effect": effect, "facts": {**facts, **cand.facts}})

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        x_name, y_name = str(cand.params["x"]), str(cand.params["y"])
        rows, _, unit = self.unit_rows(sealed, [x_name, y_name])
        hid = ctx.ledger.register(
            hypothesis=f"{x_name} and {y_name} are independent (confirmation)",
            family=["numeric_pairs", "confirmation"],
            test="spline_r2_permutation",
            params=dict(cand.params),
            parent_id=cand.hypothesis_id,
        )
        if rows.height < _MIN_N:
            ctx.ledger.mark_untestable(
                hid, reason="too few rows set aside for the check", n_obs=rows.height
            )
            return EvidenceDraft(
                test="spline_r2_permutation",
                statistic=cand.statistic,
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id, hid],
                n=rows.height,
                confirmation=Confirmation(
                    status="not_confirmed", method=_method(ctx), hypothesis_ids=[hid], n=rows.height
                ),
                caveats=["Too few rows set aside for the check to test it again."],
            )
        x = rows[x_name].cast(pl.Float64).to_numpy()
        y = rows[y_name].cast(pl.Float64).to_numpy()
        observed = spline_r2_pair(x, y)[0]
        deff_c = unit.deff(unit.side_icc(x_name, x), unit.side_icc(y_name, y))
        result = ctx.ledger.permutation_test(
            hid, observed=observed / deff_c, draw=spline_r2_draw(x, y), n_obs=x.size
        )
        effect, facts, _secondary, arrays = self._measure(
            cand, sealed, ctx, "confirm", register_shape=True
        )
        xs, ys = arrays["x"], arrays["y"]
        deff = float(arrays["deff"])
        sign = np.sign(facts["rho"]) or 1.0
        rng = stability_rng(ctx, cand.key)

        def holds(idx: np.ndarray[Any, np.dtype[np.int64]]) -> bool:
            r, p = spearman(xs[idx], ys[idx])
            fit_p = _spline_f_p(xs[idx], ys[idx])
            p, fit_p = deflate_z(p, deff), deflate_z(fit_p, deff)
            return (p < 0.05 and np.sign(r) == sign) or (bool(facts["nonlinear"]) and fit_p < 0.05)

        stability = measure_stability(xs.size, rng, holds, groups=arrays["codes"])
        specs = _pair_specs(xs, ys, sign, bool(facts["nonlinear"]), deff)
        facts["specs"] = specs
        facts["stability"] = stability
        facts["confirm_statistic"] = observed
        caveats: list[str] = unit_caveat(arrays["unit"], deff)
        if facts["n_missing"]:
            caveats.append(
                f"{facts['n_missing']:,} rows with a missing value in either column were left out."
            )
        return EvidenceDraft(
            test="spline_r2_permutation",
            statistic=cand.statistic,
            p_value=cand.p_value,
            hypothesis_ids=[cand.hypothesis_id, hid],
            n=x.size,
            confirmation=Confirmation(
                status="pending",
                method=_method(ctx),
                p_value=result.p_value,
                hypothesis_ids=[hid],
                n=x.size,
            ),
            effect=effect,
            stability=stability,
            specs_consistent=sum(1 for s in specs if s["agrees"]),
            specs_total=len(specs),
            facts=facts,
            caveats=caveats,
            claimed_rung="R1",
        )

    def charts(self, finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
        return charts.numeric_pair(finding, frame)


def _spline_f_p(x: FloatArray, y: FloatArray) -> float:
    if x.size < 20:
        return 1.0
    fit = spline_fit(x, y, np.array([float(x.mean())]))
    k = max(len(fit["knots"]) - 1, 1)
    r2 = max(min(float(fit["r2_spline"]), 0.999999), 0.0)
    df2 = x.size - k - 1
    if df2 <= 0:
        return 1.0
    f = (r2 / k) / ((1 - r2) / df2)
    return float(stats.f.sf(f, k, df2))


def _winsor(v: FloatArray) -> FloatArray:
    lo, hi = np.quantile(v, [0.01, 0.99])
    return np.clip(v, lo, hi)


def _pair_specs(
    x: FloatArray, y: FloatArray, sign: float, nonlinear: bool, deff: float = 1.0
) -> list[dict[str, Any]]:
    """Reasonable alternative analyses; a finding is robust when most of them agree.

    p-values are corrected with the same design effect as the main test.
    """
    out: list[dict[str, Any]] = []
    r, p = stats.pearsonr(x, y) if x.size > 2 else (0.0, 1.0)
    out.append(
        {
            "name": "Pearson correlation",
            "agrees": bool(deflate_z(float(p), deff) < 0.05 and (nonlinear or np.sign(r) == sign)),
        }
    )
    rho, p = spearman(x, y)
    out.append(
        {
            "name": "Spearman correlation",
            "agrees": bool(deflate_z(p, deff) < 0.05 and (nonlinear or np.sign(rho) == sign)),
        }
    )
    out.append(
        {"name": "spline regression F-test", "agrees": deflate_z(_spline_f_p(x, y), deff) < 0.05}
    )
    q1x, q3x = np.quantile(x, [0.25, 0.75])
    q1y, q3y = np.quantile(y, [0.25, 0.75])
    keep = (
        (x >= q1x - 3 * (q3x - q1x))
        & (x <= q3x + 3 * (q3x - q1x))
        & (y >= q1y - 3 * (q3y - q1y))
        & (y <= q3y + 3 * (q3y - q1y))
    )
    if keep.sum() > 20:
        rho, p = spearman(x[keep], y[keep])
        out.append(
            {
                "name": "Spearman without far outliers",
                "agrees": bool(deflate_z(p, deff) < 0.05 and (nonlinear or np.sign(rho) == sign)),
            }
        )
    rw, pw = stats.pearsonr(_winsor(x), _winsor(y)) if x.size > 2 else (0.0, 1.0)
    out.append(
        {
            "name": "Pearson on 1%-winsorized values",
            "agrees": bool(
                deflate_z(float(pw), deff) < 0.05 and (nonlinear or np.sign(rw) == sign)
            ),
        }
    )
    return out


# ====================================================================== numbers across groups


def _epsilon2(*groups: FloatArray) -> float:
    n = sum(g.size for g in groups)
    if n < 3:
        return 0.0
    ranks = rank(np.concatenate(groups))
    mean_rank = (n + 1) / 2.0
    pos = 0
    ss = 0.0
    for g in groups:
        rr = ranks[pos : pos + g.size]
        pos += g.size
        ss += g.size * (float(rr.mean()) - mean_rank) ** 2
    h = 12.0 / (n * (n + 1)) * ss
    return h / (n - 1)


def _batch_epsilon2(*groups: FloatArray) -> FloatArray:
    sizes = [g.shape[1] for g in groups]
    n = sum(sizes)
    ranks = stats.rankdata(np.concatenate(groups, axis=1), axis=1)
    mean_rank = (n + 1) / 2.0
    pos = 0
    ss = np.zeros(ranks.shape[0])
    for size in sizes:
        rr = ranks[:, pos : pos + size]
        pos += size
        ss += size * (rr.mean(axis=1) - mean_rank) ** 2
    return np.asarray(12.0 / (n * (n + 1)) * ss / (n - 1), dtype=np.float64)


def _cohen_d(a: FloatArray, b: FloatArray) -> float:
    na, nb = a.size, b.size
    pooled = ((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / max(na + nb - 2, 1)
    sd = math.sqrt(pooled)
    return 0.0 if sd == 0 else float((b.mean() - a.mean()) / sd)


def _batch_cohen_d(a: FloatArray, b: FloatArray) -> FloatArray:
    na, nb = a.shape[1], b.shape[1]
    pooled = ((na - 1) * a.var(axis=1, ddof=1) + (nb - 1) * b.var(axis=1, ddof=1)) / (na + nb - 2)
    sd = np.sqrt(pooled)
    diff = b.mean(axis=1) - a.mean(axis=1)
    return np.asarray(np.where(sd > 0, diff / np.where(sd > 0, sd, 1.0), 0.0), dtype=np.float64)


def _cliffs_delta(a: FloatArray, b: FloatArray) -> float:
    """P(b > a) − P(b < a): the rank-based effect matching the rank test (−1 to 1, 0 = no shift)."""
    ranks = rank(np.concatenate([a, b]))
    u = float(ranks[a.size :].sum()) - b.size * (b.size + 1) / 2
    return 2.0 * u / (a.size * b.size) - 1.0


def _order_codes(a: FloatArray, b: FloatArray) -> tuple[FloatArray, FloatArray, int]:
    """a and b as the ranks 0, 1, …, k − 1 of their k distinct pooled values, and k.

    Cliff's delta depends only on this order, so it is unchanged, and a bootstrap of the codes
    draws the same resamples as one of the values; :func:`_batch_cliffs_delta` then counts each
    replicate instead of sorting it. NaN stays NaN, so the statistic fails as it does on values.
    """
    pooled = np.concatenate([a, b])
    levels, codes = np.unique(pooled, return_inverse=True)
    out = codes.astype(np.float64)
    out[np.isnan(pooled)] = np.nan
    return out[: a.size], out[a.size :], int(levels.size)


def _batch_cliffs_delta(k: int) -> Callable[[FloatArray, FloatArray], FloatArray]:
    """Batch Cliff's delta for resamples of order codes 0 … k − 1 (see :func:`_order_codes`)."""

    def batch(a: FloatArray, b: FloatArray) -> FloatArray:
        rows, na, nb = a.shape[0], a.shape[1], b.shape[1]
        if np.isnan(a).any() or np.isnan(b).any():
            return np.full(rows, np.nan)
        offset = (np.arange(rows, dtype=np.int64) * k)[:, None]
        cells = rows * k
        ca = np.bincount((a.astype(np.int64) + offset).ravel(), minlength=cells).reshape(rows, k)
        cb = np.bincount((b.astype(np.int64) + offset).ravel(), minlength=cells).reshape(rows, k)
        below = np.cumsum(ca, axis=1) - ca
        # 2U counts 2 for every a value below each b value and 1 for every tie. It is an integer,
        # so U is exact, like the rank sum it replaces, and the result is the same to the bit.
        u = (cb * (2 * below + ca)).sum(axis=1) / 2.0
        return np.asarray(2.0 * u / (na * nb) - 1.0, dtype=np.float64)

    return batch


def _welch_ci(a: FloatArray, b: FloatArray) -> tuple[float, float, float]:
    """(mean(b) − mean(a), low, high) with a Welch t interval."""
    va, vb = np.var(a, ddof=1) / a.size, np.var(b, ddof=1) / b.size
    se = math.sqrt(va + vb)
    diff = float(b.mean() - a.mean())
    if se == 0:
        return diff, diff, diff
    df = (va + vb) ** 2 / (va**2 / (a.size - 1) + vb**2 / (b.size - 1))
    t = float(stats.t.ppf(0.975, df))
    return diff, diff - t * se, diff + t * se


@dataclass
class _Grouped:
    """A numeric column split by the levels of a category, at the right unit of analysis."""

    levels: list[str]
    arrays: list[FloatArray]
    excluded: list[dict[str, Any]]
    missing: int
    unit: Unit
    labels: np.ndarray[Any, np.dtype[np.int64]]  # level index per kept row (row order)
    values: FloatArray  # values per kept row (row order)
    deff: float
    icc_y: float


def _groups(spec: Any, frame: pl.DataFrame, group: str, y: str, min_cell: int) -> _Grouped:
    rows, missing, unit = unit_rows(spec, frame, [group, y])
    labels = rows[group].cast(pl.String).to_numpy()
    values = rows[y].cast(pl.Float64).to_numpy()
    levels: list[str] = []
    arrays: list[FloatArray] = []
    excluded: list[dict[str, Any]] = []
    codes = np.full(rows.height, -1, dtype=np.int64)
    counts = rows[group].cast(pl.String).value_counts(sort=True)
    for level, count in zip(
        counts[counts.columns[0]].to_list(), counts["count"].to_list(), strict=True
    ):
        if int(count) < min_cell:
            excluded.append({"level": str(level), "n": int(count)})
            continue
        mask = labels == level
        codes[mask] = len(levels)
        levels.append(str(level))
        arrays.append(values[mask])
    keep = codes >= 0
    unit = unit.subset(keep)
    kept_codes, kept_values = codes[keep], values[keep]
    icc_g = unit.side_icc(group, kept_codes, categorical=True) if len(levels) >= 2 else 0.0
    icc_y = unit.side_icc(y, kept_values)
    return _Grouped(
        levels,
        arrays,
        excluded,
        missing,
        unit,
        kept_codes,
        kept_values,
        unit.deff(icc_g, icc_y),
        icc_y,
    )


class GroupDifferences(BaseAnalyzer):
    name: ClassVar[str] = "relate.group_differences"
    pattern_class: ClassVar[PatternClass] = PatternClass.SUBGROUP
    label: ClassVar[str] = "Differences between groups"
    family: ClassVar[str] = "group_differences"
    template: ClassVar[str] = "group_difference"
    method_summary: ClassVar[str] = (
        "Kruskal-Wallis test; ε² with BCa interval; group means with t intervals"
    )
    assumptions: ClassVar[Sequence[AssumptionSpec]] = (
        AssumptionSpec(
            name="independence",
            description="Rows are independent (weak serial dependence in file order).",
            severity="major",
            check=independence_check(("y",)),
            on_fail="caveat",
        ),
        AssumptionSpec(
            name="exchangeability",
            description="Under no difference, values are exchangeable between groups.",
            severity="major",
            check=None,
        ),
    )

    def tasks(self) -> list[tuple[str, str]]:
        numeric, categorical = self.spec.predictors()
        t, kind = self.spec.target, self.spec.target_kind
        if t and kind == "numeric":
            return [(g, t) for g in categorical]
        if t and kind in {"binary", "categorical"}:
            return [(t, y) for y in numeric]
        return [(g, y) for g in categorical for y in numeric]

    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        tasks = [Task(key=f"{g}|{y}", params={"group": g, "y": y}) for g, y in self.tasks()]
        self.begin(len(tasks))
        return tasks

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        g, y = str(task.params["group"]), str(task.params["y"])
        hid = ctx.ledger.register(
            hypothesis=f"{y} has the same distribution in every {g} group",
            family=["group_differences"],
            test="kruskal_wallis",
            params=task.params,
        )
        self.tick(ctx)
        grouped = _groups(self.spec, data, g, y, self.spec.min_cell)
        arrays = grouped.arrays
        if len(arrays) < 2 or all(float(np.ptp(a)) == 0 for a in arrays):
            return []
        h, _ = stats.kruskal(*arrays)
        if not math.isfinite(float(h)):
            return []
        n_total = sum(a.size for a in arrays)
        if n_total < _MIN_N and grouped.deff <= 1.0:
            # The chi-square approximation to H is poor for small groups: use its permutation null.
            h_adj = float(h)
            result = ctx.ledger.permutation_test(
                hid, observed=h_adj, draw=_kruskal_draw(arrays), n_obs=n_total
            )
        else:
            h_adj, p = deflate_chi2(float(h), len(arrays) - 1, grouped.deff)
            result = ctx.ledger.analytic_test(hid, statistic=h_adj, p_value=p, n_obs=n_total)
        return [
            Candidate(
                key=task.key,
                analyzer=self.name,
                kind=FindingKind.ASSOCIATION,
                pattern_class=self.pattern_class,
                title=f"{y} differs between {g} groups",
                variables=[ColumnRef(column=g), ColumnRef(column=y)],
                hypothesis_id=hid,
                test="kruskal_wallis",
                statistic=h_adj,
                p_value=result.p_value,
                params=dict(task.params),
                facts={
                    "explore_n": sum(a.size for a in arrays),
                    "explore_groups": len(arrays),
                    **grouped.unit.facts(grouped.deff, prefix="explore_"),
                },
            )
        ]

    def _measure(
        self, cand: Candidate, data: pl.DataFrame, ctx: RunContext, purpose: str
    ) -> tuple[Effect, dict[str, Any], _Grouped]:
        g, y = str(cand.params["group"]), str(cand.params["y"])
        grouped = _groups(self.spec, data, g, y, self.spec.min_cell)
        levels, arrays, excluded, missing = (
            grouped.levels,
            grouped.arrays,
            grouped.excluded,
            grouped.missing,
        )
        deff = grouped.deff
        level = ctx.config.rigor.ci_level
        resamples = ctx.budget_settings.bootstrap_resamples
        rows: list[dict[str, Any]] = []
        for i, (lv, a) in enumerate(zip(levels, arrays, strict=True)):
            m = float(a.mean())
            # A group mean's own design effect: its rows repeat per entity too.
            part = grouped.unit.subset(grouped.labels == i)
            deff_mean = part.deff(1.0, grouped.icc_y) if part.level == "clustered" else 1.0
            se = (
                float(a.std(ddof=1)) / math.sqrt(a.size) * math.sqrt(deff_mean)
                if a.size > 1
                else 0.0
            )
            t = float(stats.t.ppf(0.975, max(_n_eff(a.size, deff_mean) - 1, 1)))
            rows.append(
                {
                    "level": lv,
                    "n": int(a.size),
                    "n_units": part.n_units,
                    "mean": m,
                    "median": float(np.median(a)),
                    "sd": float(a.std(ddof=1)) if a.size > 1 else 0.0,
                    "mean_low": m - t * se,
                    "mean_high": m + t * se,
                    "q1": float(np.quantile(a, 0.25)),
                    "q3": float(np.quantile(a, 0.75)),
                }
            )
        order = sorted(range(len(rows)), key=lambda i: -rows[i]["mean"])
        if len(arrays) == 2 and _cliffs_delta(arrays[order[1]], arrays[order[0]]) < 0:
            # With two groups the direction follows the rank comparison the test makes, not the
            # means (a few extreme values can put the means the other way round).
            order = order[::-1]
        top, bottom = order[0], order[-1]
        gap, gap_lo, gap_hi = _welch_ci(arrays[bottom], arrays[top])
        gap_lo, gap_hi = widen(gap, gap_lo, gap_hi, deff)
        facts: dict[str, Any] = {
            "template": self.template,
            **grouped.unit.facts(deff),
            "group": g,
            "y": y,
            "n": int(sum(a.size for a in arrays)),
            "n_missing": missing,
            "k": len(arrays),
            "groups": [rows[i] for i in order][:12],
            "excluded_groups": excluded,
            "top_level": rows[top]["level"],
            "bottom_level": rows[bottom]["level"],
            "top_mean": rows[top]["mean"],
            "bottom_mean": rows[bottom]["mean"],
            "gap": gap,
            "gap_low": gap_lo,
            "gap_high": gap_hi,
            "overall_mean": float(np.concatenate(arrays).mean()),
            "target_is_group": self.spec.target == g,
        }
        suffix = f", widened ×√{deff:.2f} for repeated {grouped.unit.entity}" if deff > 1.0 else ""
        if len(arrays) == 2:
            a, b = arrays[bottom], arrays[top]
            d_ci = ctx.ledger.bootstrap(
                purpose=f"{purpose}:{cand.key}:cohen_d",
                samples=[a, b],
                statistic=_cohen_d,
                batch_statistic=_batch_cohen_d,
                n_resamples=resamples,
                level=level,
            )
            d_lo, d_hi = widen(d_ci.estimate, d_ci.low, d_ci.high, deff)
            codes_a, codes_b, k = _order_codes(a, b)
            c_ci = ctx.ledger.bootstrap(
                purpose=f"{purpose}:{cand.key}:cliffs_delta",
                samples=[codes_a, codes_b],
                statistic=_cliffs_delta,
                batch_statistic=_batch_cliffs_delta(k),
                n_resamples=min(resamples, 2000),
                level=level,
                method="percentile",
            )
            c_lo, c_hi = widen(c_ci.estimate, c_ci.low, c_ci.high, deff)
            c_lo = None if c_lo is None else max(-1.0, c_lo)
            c_hi = None if c_hi is None else min(1.0, c_hi)
            facts.update(
                {
                    "cohen_d": d_ci.estimate,
                    "cohen_d_low": d_lo,
                    "cohen_d_high": d_hi,
                    "cliffs_delta": c_ci.estimate,
                    "cliffs_low": c_lo,
                    "cliffs_high": c_hi,
                    "prob_superiority": (c_ci.estimate + 1.0) / 2.0,
                }
            )
            effect = Effect(
                measure="cliffs_delta",
                estimate=c_ci.estimate,
                ci_low=c_lo,
                ci_high=c_hi,
                ci_level=level,
                ci_method=f"bootstrap {c_ci.method}{suffix}",
                split=ctx.split,
            )
        else:
            capped = [
                a if a.size <= 4000 else a[np.linspace(0, a.size - 1, 4000).astype(int)]
                for a in arrays
            ]
            e_ci = ctx.ledger.bootstrap(
                purpose=f"{purpose}:{cand.key}:epsilon2",
                samples=capped,
                statistic=_epsilon2,
                batch_statistic=_batch_epsilon2,
                n_resamples=min(resamples, 1000),
                level=level,
                method="percentile",
            )
            e2 = _epsilon2(*arrays)
            e_lo, e_hi = widen(e2, e_ci.low, e_ci.high, deff)
            e_lo = None if e_lo is None else max(0.0, e_lo)
            e_hi = None if e_hi is None else min(1.0, e_hi)
            facts.update({"epsilon2": e2, "epsilon2_low": e_lo, "epsilon2_high": e_hi})
            effect = Effect(
                measure="epsilon_squared",
                estimate=e2,
                ci_low=e_lo,
                ci_high=e_hi,
                ci_level=level,
                ci_method=f"bootstrap {e_ci.method}{suffix}",
                split=ctx.split,
            )
        return effect, facts, grouped

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        effect, facts, _ = self._measure(cand, data, ctx, "refine")
        return cand.model_copy(update={"effect": effect, "facts": {**facts, **cand.facts}})

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        g, y = str(cand.params["group"]), str(cand.params["y"])
        hid = ctx.ledger.register(
            hypothesis=f"{y} has the same distribution in every {g} group (confirmation)",
            family=["group_differences", "confirmation"],
            test="kruskal_wallis",
            params=dict(cand.params),
            parent_id=cand.hypothesis_id,
        )
        checked = _groups(self.spec, sealed, g, y, self.spec.min_cell)
        arrays = checked.arrays
        if len(arrays) < 2:
            ctx.ledger.mark_untestable(
                hid,
                reason="too few rows per group set aside for the check",
                n_obs=sum(a.size for a in arrays),
            )
            return EvidenceDraft(
                test="kruskal_wallis",
                statistic=cand.statistic,
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id, hid],
                n=sum(a.size for a in arrays),
                confirmation=Confirmation(
                    status="not_confirmed", method=_method(ctx), hypothesis_ids=[hid]
                ),
                caveats=["Too few rows per group in the data set aside for the check."],
            )
        h, _ = stats.kruskal(*arrays)
        h_adj, p = deflate_chi2(float(h), len(arrays) - 1, checked.deff)
        result = ctx.ledger.analytic_test(
            hid, statistic=h_adj, p_value=p, n_obs=sum(a.size for a in arrays)
        )
        effect, facts, grouped = self._measure(cand, sealed, ctx, "confirm")
        arrays, levels = grouped.arrays, grouped.levels
        labels, values, deff = grouped.labels, grouped.values, grouped.deff
        top = levels.index(facts["top_level"])
        bottom = levels.index(facts["bottom_level"])

        def holds(idx: np.ndarray[Any, np.dtype[np.int64]]) -> bool:
            parts = [values[idx][labels[idx] == i] for i in range(len(arrays))]
            parts = [q for q in parts if q.size >= 5]
            if len(parts) < 2:
                return False
            hh, _ = stats.kruskal(*parts)
            pp = deflate_chi2(float(hh), len(parts) - 1, deff)[1]
            a_, b_ = values[idx][labels[idx] == bottom], values[idx][labels[idx] == top]
            return bool(pp < 0.05 and a_.size and b_.size and b_.mean() > a_.mean())

        stability = measure_stability(
            values.size, stability_rng(ctx, cand.key), holds, groups=grouped.unit.codes
        )
        specs = _group_specs(arrays, deff)
        facts["specs"] = specs
        facts["stability"] = stability
        n = int(values.size)
        caveats: list[str] = unit_caveat(grouped.unit, deff)
        if facts["excluded_groups"]:
            caveats.append(
                "Groups with fewer than "
                f"{self.spec.min_cell} rows were not compared: "
                + ", ".join(f"{e['level']} ({e['n']})" for e in facts["excluded_groups"][:5])
                + "."
            )
        return EvidenceDraft(
            test="kruskal_wallis",
            statistic=cand.statistic,
            p_value=cand.p_value,
            hypothesis_ids=[cand.hypothesis_id, hid],
            n=n,
            confirmation=Confirmation(
                status="pending",
                method=_method(ctx),
                p_value=result.p_value,
                hypothesis_ids=[hid],
                n=n,
            ),
            effect=effect,
            stability=stability,
            specs_consistent=sum(1 for s in specs if s["agrees"]),
            specs_total=len(specs),
            facts=facts,
            caveats=caveats,
        )

    def charts(self, finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
        return charts.group_difference(finding)


def _group_specs(arrays: list[FloatArray], deff: float = 1.0) -> list[dict[str, Any]]:
    k = len(arrays) - 1
    n = sum(a.size for a in arrays)
    out: list[dict[str, Any]] = []
    out.append(
        {
            "name": "Kruskal-Wallis",
            "agrees": bool(deflate_chi2(float(stats.kruskal(*arrays)[0]), k, deff)[1] < 0.05),
        }
    )
    out.append(
        {
            "name": "one-way ANOVA",
            "agrees": bool(
                deflate_f(float(stats.f_oneway(*arrays)[0]), k, n - k - 1, deff)[1] < 0.05
            ),
        }
    )
    wins = [np.clip(a, *np.quantile(np.concatenate(arrays), [0.01, 0.99])) for a in arrays]
    out.append(
        {
            "name": "ANOVA on 1%-winsorized values",
            "agrees": bool(
                deflate_f(float(stats.f_oneway(*wins)[0]), k, n - k - 1, deff)[1] < 0.05
            ),
        }
    )
    with contextlib.suppress(ValueError):
        out.append(
            {
                "name": "Mood's median test",
                "agrees": bool(
                    deflate_chi2(float(stats.median_test(*arrays)[0]), k, deff)[1] < 0.05
                ),
            }
        )
    return out


# ====================================================================== categories vs categories


def _codes(series: pl.Series) -> tuple[np.ndarray[Any, np.dtype[np.int64]], list[str]]:
    values = series.cast(pl.String)
    levels = sorted(str(v) for v in values.unique().to_list())
    index = {v: i for i, v in enumerate(levels)}
    return np.array([index[str(v)] for v in values.to_list()], dtype=np.int64), levels


def _chi2(
    a: np.ndarray[Any, np.dtype[np.int64]], b: np.ndarray[Any, np.dtype[np.int64]], ka: int, kb: int
) -> float:
    table = np.bincount(a * kb + b, minlength=ka * kb).reshape(ka, kb).astype(float)
    expected = table.sum(1, keepdims=True) * table.sum(0, keepdims=True) / table.sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        cells: FloatArray = (table - expected) ** 2 / np.where(expected > 0, expected, np.nan)
        return float(np.nansum(cells))


def _cramers_v_idx(
    a: np.ndarray[Any, np.dtype[np.int64]], b: np.ndarray[Any, np.dtype[np.int64]], ka: int, kb: int
) -> Any:
    n = a.size

    def stat(idx: FloatArray) -> float:
        i = idx.astype(np.int64)
        chi = _chi2(a[i], b[i], ka, kb)
        return math.sqrt(chi / (n * max(min(ka, kb) - 1, 1)))

    return stat


class CategoryAssociations(BaseAnalyzer):
    name: ClassVar[str] = "relate.category_associations"
    pattern_class: ClassVar[PatternClass] = PatternClass.SHAPE
    label: ClassVar[str] = "Associations between categories"
    family: ClassVar[str] = "relationships"
    template: ClassVar[str] = "category_association"
    method_summary: ClassVar[str] = (
        "Pearson chi-square (Monte Carlo when cells are sparse); Cramér's V with bootstrap interval"
    )
    assumptions: ClassVar[Sequence[AssumptionSpec]] = (
        AssumptionSpec(
            name="independent_rows",
            description="Each row is a separate, independent record.",
            severity="major",
            check=None,
        ),
    )

    def tasks(self) -> list[tuple[str, str]]:
        _, categorical = self.spec.predictors()
        t = self.spec.target
        if t and self.spec.target_kind in {"binary", "categorical"}:
            return [(c, t) for c in categorical]
        if t and self.spec.intent == "target":
            return []
        return list(itertools.combinations(categorical, 2))

    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        tasks = [Task(key=f"{a}|{b}", params={"a": a, "b": b}) for a, b in self.tasks()]
        self.begin(len(tasks))
        return tasks

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        a_name, b_name = str(task.params["a"]), str(task.params["b"])
        rows, _, unit = self.unit_rows(data, [a_name, b_name])
        self.tick(ctx)
        if rows.height < _MIN_N:
            ctx.ledger.register(
                hypothesis=f"{a_name} and {b_name} are independent",
                family=["category_pairs"],
                test="chi_square",
                params=task.params,
            )
            return []
        a, la = _codes(rows[a_name])
        b, lb = _codes(rows[b_name])
        ka, kb = len(la), len(lb)
        table = np.bincount(a * kb + b, minlength=ka * kb).reshape(ka, kb)
        expected = table.sum(1, keepdims=True) * table.sum(0, keepdims=True) / table.sum()
        sparse = float((expected < 5).mean()) > 0.2
        test = "chi_square_monte_carlo" if sparse else "chi_square"
        hid = ctx.ledger.register(
            hypothesis=f"{a_name} and {b_name} are independent",
            family=["category_pairs"],
            test=test,
            params=task.params,
        )
        if ka < 2 or kb < 2:
            return []
        chi = _chi2(a, b, ka, kb)
        deff = unit.deff(
            unit.side_icc(a_name, a, categorical=True), unit.side_icc(b_name, b, categorical=True)
        )
        if sparse:

            def draw(rng: np.random.Generator, size: int) -> FloatArray:
                return np.array(
                    [_chi2(a, rng.permutation(b), ka, kb) for _ in range(size)], dtype=np.float64
                )

            chi_adj = chi / deff
            result = ctx.ledger.permutation_test(
                hid, observed=chi_adj, draw=draw, n_obs=a.size, n_max=2000
            )
        else:
            chi_adj, p = deflate_chi2(chi, (ka - 1) * (kb - 1), deff)
            result = ctx.ledger.analytic_test(hid, statistic=chi_adj, p_value=p, n_obs=a.size)
        return [
            Candidate(
                key=task.key,
                analyzer=self.name,
                kind=FindingKind.ASSOCIATION,
                pattern_class=self.pattern_class,
                title=f"{a_name} and {b_name} are associated",
                variables=[ColumnRef(column=a_name), ColumnRef(column=b_name)],
                hypothesis_id=hid,
                test=test,
                statistic=chi_adj,
                p_value=result.p_value,
                params=dict(task.params),
                facts={"explore_n": a.size, **unit.facts(deff, prefix="explore_")},
            )
        ]

    def _measure(
        self, cand: Candidate, data: pl.DataFrame, ctx: RunContext, purpose: str
    ) -> tuple[Effect, dict[str, Any], Unit, float]:
        a_name, b_name = str(cand.params["a"]), str(cand.params["b"])
        rows, missing, unit = self.unit_rows(data, [a_name, b_name])
        a, la = _codes(rows[a_name])
        b, lb = _codes(rows[b_name])
        ka, kb = len(la), len(lb)
        n = a.size
        deff = unit.deff(
            unit.side_icc(a_name, a, categorical=True), unit.side_icc(b_name, b, categorical=True)
        )
        table = np.bincount(a * kb + b, minlength=ka * kb).reshape(ka, kb).astype(float)
        expected = table.sum(1, keepdims=True) * table.sum(0, keepdims=True) / max(table.sum(), 1)
        chi = _chi2(a, b, ka, kb)
        v = math.sqrt(chi / (n * max(min(ka, kb) - 1, 1))) if n else 0.0
        ci = ctx.ledger.bootstrap(
            purpose=f"{purpose}:{cand.key}:cramers_v",
            samples=[np.arange(n, dtype=np.float64)],
            statistic=_cramers_v_idx(a, b, ka, kb),
            n_resamples=min(ctx.budget_settings.bootstrap_resamples, 1000),
            level=ctx.config.rigor.ci_level,
            method="percentile",
        )
        v_lo, v_hi = widen(v, ci.low, ci.high, deff)
        v_lo = None if v_lo is None else max(0.0, v_lo)
        v_hi = None if v_hi is None else min(1.0, v_hi)
        with np.errstate(divide="ignore", invalid="ignore"):
            resid = (table - expected) / np.sqrt(np.where(expected > 0, expected, np.nan))
        cells: list[dict[str, Any]] = []
        for i, j in zip(
            *np.unravel_index(np.argsort(-np.nan_to_num(resid, nan=-1e9), axis=None), resid.shape),
            strict=True,
        ):
            if (
                len(cells) >= 4
                or not np.isfinite(resid[i, j])
                or resid[i, j] <= 2 * math.sqrt(deff)
            ):
                break
            if table[i, j] < self.spec.min_cell:
                continue
            row_total = table[i].sum()
            cells.append(
                {
                    "a": la[i],
                    "b": lb[j],
                    "observed": int(table[i, j]),
                    "expected": float(expected[i, j]),
                    "row_share": float(table[i, j] / row_total) if row_total else 0.0,
                    "col_share_overall": float(table[:, j].sum() / table.sum()),
                    "ratio": float(table[i, j] / expected[i, j]) if expected[i, j] else None,
                }
            )
        rates: list[dict[str, Any]] = []
        target = self.spec.target
        if target in (a_name, b_name) and self.spec.target_kind == "binary":
            other = b_name if target == a_name else a_name
            tvals = binary_array(rows[target], self.spec.positive)
            labels = rows[other].cast(pl.String).to_numpy()
            for lv in sorted(set(labels.tolist())):
                mask = labels == lv
                k = int(mask.sum())
                if k < self.spec.min_cell:
                    continue
                rate = float(tvals[mask].mean())
                lo, hi = _wilson(rate, _n_eff(k, deff))
                rates.append({"level": lv, "n": k, "rate": rate, "low": lo, "high": hi})
            rates.sort(key=lambda r: -r["rate"])
        facts: dict[str, Any] = {
            "template": self.template,
            **unit.facts(deff),
            "a": a_name,
            "b": b_name,
            "n": n,
            "n_missing": missing,
            "levels_a": ka,
            "levels_b": kb,
            "cramers_v": v,
            "cramers_v_low": v_lo,
            "cramers_v_high": v_hi,
            "chi2": chi,
            "dof": (ka - 1) * (kb - 1),
            "cells": cells,
            "rates": rates,
            "target_rates": bool(rates),
            "positive": self.spec.positive,
            "table": {"rows": la, "cols": lb, "counts": table.astype(int).tolist()},
        }
        suffix = f", widened ×√{deff:.2f} for repeated {unit.entity}" if deff > 1.0 else ""
        effect = Effect(
            measure="cramers_v",
            estimate=v,
            ci_low=v_lo,
            ci_high=v_hi,
            ci_level=ctx.config.rigor.ci_level,
            ci_method=f"bootstrap {ci.method}{suffix}",
            split=ctx.split,
        )
        return effect, facts, unit, deff

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        effect, facts, _, _ = self._measure(cand, data, ctx, "refine")
        return cand.model_copy(update={"effect": effect, "facts": {**facts, **cand.facts}})

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        a_name, b_name = str(cand.params["a"]), str(cand.params["b"])
        rows, _, unit = self.unit_rows(sealed, [a_name, b_name])
        a, la = _codes(rows[a_name])
        b, lb = _codes(rows[b_name])
        ka, kb = len(la), len(lb)
        hid = ctx.ledger.register(
            hypothesis=f"{a_name} and {b_name} are independent (confirmation)",
            family=["category_pairs", "confirmation"],
            test="chi_square",
            params=dict(cand.params),
            parent_id=cand.hypothesis_id,
        )
        if ka < 2 or kb < 2 or a.size < _MIN_N:
            ctx.ledger.mark_untestable(
                hid, reason="too few rows or labels set aside for the check", n_obs=int(a.size)
            )
            return EvidenceDraft(
                test=cand.test,
                statistic=cand.statistic,
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id, hid],
                n=a.size,
                confirmation=Confirmation(
                    status="not_confirmed", method=_method(ctx), hypothesis_ids=[hid]
                ),
                caveats=["Too few rows set aside for the check."],
            )
        chi = _chi2(a, b, ka, kb)
        dof = (ka - 1) * (kb - 1)
        deff = unit.deff(
            unit.side_icc(a_name, a, categorical=True), unit.side_icc(b_name, b, categorical=True)
        )
        chi_adj, p = deflate_chi2(chi, dof, deff)
        result = ctx.ledger.analytic_test(hid, statistic=chi_adj, p_value=p, n_obs=a.size)
        effect, facts, _, _ = self._measure(cand, sealed, ctx, "confirm")

        def holds(idx: np.ndarray[Any, np.dtype[np.int64]]) -> bool:
            c = _chi2(a[idx], b[idx], ka, kb)
            return bool(deflate_chi2(c, dof, deff)[1] < 0.05)

        stability = measure_stability(
            a.size, stability_rng(ctx, cand.key), holds, groups=unit.codes
        )
        table = np.bincount(a * kb + b, minlength=ka * kb).reshape(ka, kb)
        g = stats.chi2_contingency(table, correction=False, lambda_="log-likelihood")
        specs = [
            {"name": "Pearson chi-square", "agrees": p < 0.05},
            {
                "name": "likelihood-ratio G-test",
                "agrees": bool(deflate_chi2(float(g.statistic), dof, deff)[1] < 0.05),
            },
        ]
        facts["specs"] = specs
        facts["stability"] = stability
        return EvidenceDraft(
            test=cand.test,
            statistic=cand.statistic,
            p_value=cand.p_value,
            hypothesis_ids=[cand.hypothesis_id, hid],
            n=a.size,
            confirmation=Confirmation(
                status="pending",
                method=_method(ctx),
                p_value=result.p_value,
                hypothesis_ids=[hid],
                n=a.size,
            ),
            effect=effect,
            stability=stability,
            specs_consistent=sum(1 for s in specs if s["agrees"]),
            specs_total=len(specs),
            facts=facts,
            caveats=unit_caveat(unit, deff),
        )

    def charts(self, finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
        return charts.category_association(finding)


def _wilson(p: float, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)
