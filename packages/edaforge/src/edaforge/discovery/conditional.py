"""Conditional relationships: associations explained away by, or reversed within, a third variable.

For an associated numeric pair (x, y) and a candidate third variable z:

* explained away — x and y are associated, but after accounting for z the remaining (partial)
  association is negligible. Tested as an intersection-union test: the marginal Spearman test
  must reject *and* a TOST equivalence test must show |partial ρ| < 0.1. Both must hold, so the
  p-value is the larger of the two (Berger, 1982). A non-significant partial correlation alone is
  never read as "no association".
* reversal (Simpson's paradox) — the association has one direction overall and the opposite
  direction once z is accounted for: one-sided marginal test in the observed direction and
  one-sided partial test in the opposite direction, combined the same way.

Partial associations are rank-based (Spearman ranks residualized on z: dummy columns for a
category, ranks for a number). For a categorical z the within-group correlations are reported
too (groups under the disclosure minimum are not shown).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from typing import Any, ClassVar, cast

import numpy as np
import polars as pl
from scipy import stats

from edaforge.discovery import charts
from edaforge.discovery.base import BaseAnalyzer, measure_stability, stability_rng
from edaforge.discovery.grain import deflate_z
from edaforge.discovery.relationships import unit_caveat
from edaforge.discovery.stats import (
    FloatArray,
    bonett_wright_ci,
    partial_rank_corr,
    rank,
    spearman,
    tost_corr,
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

__all__ = ["Conditional"]

_DELTA = 0.10  # equivalence margin for "negligible": the SESOI for a correlation
_MAX_PAIRS = 25


def _controls(frame: pl.DataFrame, z: str, categorical: bool) -> FloatArray:
    if categorical:
        labels = frame[z].cast(pl.String).to_numpy()
        levels = sorted(set(labels.tolist()))
        if len(levels) < 2:
            return np.zeros((frame.height, 0))
        return np.column_stack([(labels == lv).astype(float) for lv in levels[1:]])
    return rank(frame[z].cast(pl.Float64).to_numpy())[:, None]


def _one_sided(rho: float, n: int, k: int, direction: float) -> float:
    """P-value of H0: ρ ≤ 0 (direction +1) or ρ ≥ 0 (direction −1), t approximation."""
    df = n - 2 - k
    if df <= 0:
        return 1.0
    if abs(rho) >= 1:
        return 0.0 if np.sign(rho) == direction else 1.0
    t = rho * math.sqrt(df / (1 - rho * rho))
    return float(stats.t.sf(direction * t, df))


class Conditional(BaseAnalyzer):
    name: ClassVar[str] = "condition.third_variable"
    pattern_class: ClassVar[PatternClass] = PatternClass.THIRD_VARIABLE
    label: ClassVar[str] = "Third-variable checks (explained away, reversals)"
    family: ClassVar[str] = "conditional"
    template: ClassVar[str] = "conditional"
    method_summary: ClassVar[str] = (
        "Partial Spearman correlation given z; explained away = marginal test ∩ "
        "TOST(|partial ρ| < 0.1); reversal = opposite-sign one-sided tests"
    )
    assumptions: ClassVar[Sequence[AssumptionSpec]] = (
        AssumptionSpec(
            name="adjustment_is_appropriate",
            description=(
                "z is not itself a consequence of x or y. Adjusting for a consequence (a "
                "mediator or a "
                "collider) can create or remove associations; this cannot be checked from the data."
            ),
            severity="major",
            check=None,
        ),
        AssumptionSpec(
            name="linear_adjustment",
            description=(
                "The rank association with z is roughly linear (numeric z) or captured by "
                "its groups (categorical z)."
            ),
            severity="minor",
            check=None,
        ),
    )

    def _binary(self) -> dict[str, str]:
        """Yes/no columns, coded 1 for the level shown as "yes".

        That level is ``true``, ``1``, or the later label.
        """
        out: dict[str, str] = {}
        for c in self.spec.predictors()[1]:
            levels = self.spec.levels.get(c, ())
            if len(levels) == 2:
                lower = [lv.lower() for lv in levels]
                out[c] = next(
                    (levels[lower.index(y)] for y in ("true", "1", "yes", "y") if y in lower),
                    max(levels),
                )
        return out

    def _values(self, rows: pl.DataFrame, column: str) -> FloatArray:
        positive = self._binary().get(column)
        if positive is not None:
            return (rows[column].cast(pl.String) == positive).cast(pl.Float64).to_numpy()
        return rows[column].cast(pl.Float64).to_numpy()

    def _pairs(self, frame: pl.DataFrame) -> list[tuple[str, str]]:
        numeric = list(self.spec.numeric)
        binary = list(self._binary())
        t = self.spec.target if self.spec.target_kind == "numeric" else None
        if t:
            candidates = [(x, t) for x in [*numeric, *binary] if x != t]
        else:
            candidates = [
                *itertools.combinations(numeric, 2),
                *((b, n) for b in binary for n in numeric),
            ]
        scored: list[tuple[float, str, str]] = []
        for x, y in candidates:
            rows, _, unit = self.unit_rows(frame, [x, y])
            if rows.height < 50:
                continue
            xv, yv = self._values(rows, x), self._values(rows, y)
            rho, p = spearman(xv, yv)
            p = deflate_z(p, unit.deff(unit.side_icc(x, xv), unit.side_icc(y, yv)))
            if abs(rho) >= 0.1 and p < 0.01:
                scored.append((abs(rho), x, y))
        scored.sort(reverse=True)
        return [(x, y) for _, x, y in scored[:_MAX_PAIRS]]

    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        _, categorical = self.spec.predictors()
        tasks: list[Task] = []
        binary = self._binary()
        for x, y in self._pairs(data.frame):
            for z in [*categorical, *self.spec.numeric]:
                if z in {x, y} or (z in binary and x in binary):
                    continue
                is_cat = z in categorical
                if is_cat and not 2 <= len(self.spec.levels.get(z, ())) <= 10:
                    continue
                tasks.append(
                    Task(
                        key=f"{x}|{y}|{z}", params={"x": x, "y": y, "z": z, "z_categorical": is_cat}
                    )
                )
        self.begin(len(tasks))
        return tasks

    def _stats(self, frame: pl.DataFrame, params: dict[str, Any]) -> dict[str, Any] | None:
        x, y, z = str(params["x"]), str(params["y"]), str(params["z"])
        is_cat = bool(params["z_categorical"])
        rows, missing, unit = self.unit_rows(frame, [x, y, z])
        n = rows.height
        if n < 50:
            return None
        xv = self._values(rows, x)
        yv = self._values(rows, y)
        if float(xv.std()) == 0 or float(yv.std()) == 0:
            return None
        controls = _controls(rows, z, is_cat)
        if controls.shape[1] == 0:
            return None
        # Repeated rows per entity: every test below uses the effective number of rows.
        deff = unit.deff(unit.side_icc(x, xv), unit.side_icc(y, yv))
        n_eff = max(4, round(n / deff)) if deff > 1.0 else n
        rho_m, p_m = spearman(xv, yv)
        p_m = deflate_z(p_m, deff)
        rho_p, k = partial_rank_corr(xv, yv, controls)
        within: list[dict[str, Any]] = []
        if is_cat:
            labels = rows[z].cast(pl.String).to_numpy()
            for lv in sorted(set(labels.tolist())):
                mask = labels == lv
                if int(mask.sum()) < max(self.spec.min_cell, 20):
                    continue
                r, _p = spearman(xv[mask], yv[mask])
                lo, hi = bonett_wright_ci(r, max(4, round(int(mask.sum()) / deff)))
                within.append({"level": lv, "n": int(mask.sum()), "rho": r, "low": lo, "high": hi})
        return {
            "x": xv,
            "y": yv,
            "controls": controls,
            "n": n,
            "n_eff": n_eff,
            "deff": deff,
            "unit": unit,
            "missing": missing,
            "rho_m": rho_m,
            "p_m": p_m,
            "rho_p": rho_p,
            "k": k,
            "within": within,
        }

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        self.tick(ctx)
        params = dict(task.params)
        x, y, z = str(params["x"]), str(params["y"]), str(params["z"])
        hid_ea = ctx.ledger.register(
            hypothesis=f"accounting for {z} leaves a non-negligible association of {x} and {y}",
            family=["conditional", "explained_away"],
            test="IUT(spearman, TOST |partial rho| < 0.1)",
            params=params,
        )
        hid_rev = ctx.ledger.register(
            hypothesis=f"the association of {x} and {y} does not reverse after accounting for {z}",
            family=["conditional", "reversal"],
            test="IUT(one-sided marginal, one-sided partial opposite)",
            params=params,
        )
        s = self._stats(data, params)
        if s is None:
            return []
        n, n_eff, k = s["n"], s["n_eff"], s["k"]
        p_ea = max(s["p_m"], tost_corr(s["rho_p"], n_eff, _DELTA, k))
        res_ea = ctx.ledger.analytic_test(hid_ea, statistic=s["rho_p"], p_value=p_ea, n_obs=n)
        direction = float(np.sign(s["rho_m"]) or 1.0)
        p_rev = max(
            _one_sided(s["rho_m"], n_eff, 0, direction),
            _one_sided(s["rho_p"], n_eff, k, -direction),
        )
        res_rev = ctx.ledger.analytic_test(hid_rev, statistic=s["rho_p"], p_value=p_rev, n_obs=n)
        out: list[Candidate] = []
        attenuation = 1 - abs(s["rho_p"]) / abs(s["rho_m"]) if s["rho_m"] else 0.0
        base = {
            "explore_rho_m": s["rho_m"],
            "explore_rho_p": s["rho_p"],
            "explore_n": n,
            **s["unit"].facts(s["deff"], prefix="explore_"),
        }
        if abs(s["rho_m"]) >= 0.1 and attenuation >= 0.5:
            out.append(
                Candidate(
                    key=f"ea|{task.key}",
                    analyzer=self.name,
                    kind=FindingKind.EXPLAINED_AWAY,
                    pattern_class=self.pattern_class,
                    title=f"The link between {x} and {y} is largely accounted for by {z}",
                    variables=[ColumnRef(column=x), ColumnRef(column=y), ColumnRef(column=z)],
                    hypothesis_id=hid_ea,
                    test="IUT(spearman, TOST |partial rho| < 0.1)",
                    statistic=s["rho_p"],
                    p_value=res_ea.p_value,
                    params={**params, "mode": "explained_away"},
                    facts=base,
                )
            )
        if np.sign(s["rho_p"]) == -direction and abs(s["rho_p"]) >= 0.05:
            out.append(
                Candidate(
                    key=f"rev|{task.key}",
                    analyzer=self.name,
                    kind=FindingKind.REVERSAL,
                    pattern_class=self.pattern_class,
                    title=f"The link between {x} and {y} reverses once {z} is accounted for",
                    variables=[ColumnRef(column=x), ColumnRef(column=y), ColumnRef(column=z)],
                    hypothesis_id=hid_rev,
                    test="IUT(one-sided marginal, one-sided partial opposite)",
                    statistic=s["rho_p"],
                    p_value=res_rev.p_value,
                    params={**params, "mode": "reversal"},
                    facts=base,
                )
            )
        return out

    def _facts(
        self, s: dict[str, Any], params: dict[str, Any], mode: str
    ) -> tuple[Effect, dict[str, Any]]:
        n, n_eff, k = s["n"], s["n_eff"], s["k"]
        m_lo, m_hi = bonett_wright_ci(s["rho_m"], n_eff)
        p_lo, p_hi = bonett_wright_ci(s["rho_p"], n_eff, k)
        attenuation = 1 - abs(s["rho_p"]) / abs(s["rho_m"]) if s["rho_m"] else 0.0
        facts: dict[str, Any] = {
            "template": self.template,
            **s["unit"].facts(s["deff"]),
            "mode": mode,
            "x": params["x"],
            "y": params["y"],
            "z": params["z"],
            "z_categorical": bool(params["z_categorical"]),
            "x_binary": params["x"] in self._binary(),
            "x_positive": self._binary().get(str(params["x"])),
            "n": n,
            "n_missing": s["missing"],
            "rho_marginal": s["rho_m"],
            "rho_marginal_low": m_lo,
            "rho_marginal_high": m_hi,
            "rho_partial": s["rho_p"],
            "rho_partial_low": p_lo,
            "rho_partial_high": p_hi,
            "attenuation": attenuation,
            "delta": _DELTA,
            "controls": k,
            "within": s["within"],
            "within_opposite": sum(
                1 for w in s["within"] if np.sign(w["rho"]) == -np.sign(s["rho_m"])
            ),
        }
        method = "Bonett-Wright Fisher-z (partial)" + (
            f", effective n {n_eff:,} (design effect {s['deff']:.2f})" if s["deff"] > 1.0 else ""
        )
        effect = Effect(
            measure="partial_rho", estimate=s["rho_p"], ci_low=p_lo, ci_high=p_hi, ci_method=method
        )
        return effect, facts

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        s = self._stats(data, dict(cand.params))
        if s is None:
            return cand
        effect, facts = self._facts(s, dict(cand.params), str(cand.params["mode"]))
        return cand.model_copy(
            update={
                "effect": effect.model_copy(update={"split": ctx.split}),
                "facts": {**facts, **cand.facts},
            }
        )

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        params = dict(cand.params)
        mode = str(params["mode"])
        hid = ctx.ledger.register(
            hypothesis=f"{cand.title} (confirmation)",
            family=["conditional", mode, "confirmation"],
            test=cand.test,
            params=params,
            parent_id=cand.hypothesis_id,
        )
        method = "sealed_holdout" if ctx.split == "confirmation" else "cross_fit"
        s = self._stats(sealed, params)
        if s is None:
            ctx.ledger.mark_untestable(
                hid, reason="too few complete rows set aside for the check", n_obs=0
            )
            return EvidenceDraft(
                test=cand.test,
                statistic=cand.statistic,
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id, hid],
                n=0,
                confirmation=Confirmation(
                    status="not_confirmed", method=method, hypothesis_ids=[hid]
                ),
                caveats=["Too few complete rows set aside for the check."],
            )
        n, n_eff, k, deff = s["n"], s["n_eff"], s["k"], s["deff"]
        rho_m = float(cast("float", cand.facts.get("explore_rho_m", s["rho_m"])))
        direction = float(np.sign(rho_m)) or 1.0
        if mode == "explained_away":
            p = max(s["p_m"], tost_corr(s["rho_p"], n_eff, _DELTA, k))
        else:
            p = max(
                _one_sided(s["rho_m"], n_eff, 0, direction),
                _one_sided(s["rho_p"], n_eff, k, -direction),
            )
        result = ctx.ledger.analytic_test(hid, statistic=s["rho_p"], p_value=p, n_obs=n)
        effect, facts = self._facts(s, params, mode)
        xv, yv, controls = s["x"], s["y"], s["controls"]

        def holds(idx: np.ndarray[Any, np.dtype[np.int64]]) -> bool:
            m = max(4, round(idx.size / deff)) if deff > 1.0 else idx.size
            rm, pm = spearman(xv[idx], yv[idx])
            rp, kk = partial_rank_corr(xv[idx], yv[idx], controls[idx])
            if mode == "explained_away":
                return bool(deflate_z(pm, deff) < 0.05 and tost_corr(rp, m, _DELTA, kk) < 0.05)
            return bool(
                _one_sided(rm, m, 0, direction) < 0.05 and _one_sided(rp, m, kk, -direction) < 0.05
            )

        stability = measure_stability(
            n, stability_rng(ctx, cand.key), holds, groups=s["unit"].codes
        )
        r_partial_pearson = _partial_pearson(xv, yv, controls)
        specs = [
            {"name": "rank-based (Spearman) partial correlation", "agrees": p < 0.05},
            {
                "name": "Pearson partial correlation",
                "agrees": bool(
                    (abs(r_partial_pearson) < _DELTA)
                    if mode == "explained_away"
                    else (np.sign(r_partial_pearson) == -direction)
                ),
            },
        ]
        if facts["within"]:
            agree = (
                facts["within_opposite"] / len(facts["within"])
                if mode == "reversal"
                else float(np.mean([abs(w["rho"]) < 0.15 for w in facts["within"]]))
            )
            specs.append({"name": "within-group correlations", "agrees": bool(agree >= 0.5)})
        facts["specs"] = specs
        facts["stability"] = stability
        return EvidenceDraft(
            test=cand.test,
            statistic=cand.statistic,
            p_value=cand.p_value,
            hypothesis_ids=[cand.hypothesis_id, hid],
            n=n,
            confirmation=Confirmation(
                status="pending", method=method, p_value=result.p_value, hypothesis_ids=[hid], n=n
            ),
            effect=effect.model_copy(update={"split": ctx.split}),
            stability=stability,
            specs_consistent=sum(1 for sp in specs if sp["agrees"]),
            specs_total=len(specs),
            facts=facts,
            caveats=[
                (
                    f"Whether {params['z']} should be accounted for depends on how the "
                    f"variables come about: if {params['z']} "
                    f"is a result of {params['x']} or {params['y']}, adjusting for it can mislead."
                ),
                *unit_caveat(s["unit"], deff),
            ],
        )

    def charts(self, finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
        return charts.conditional(finding, frame)


def _partial_pearson(x: FloatArray, y: FloatArray, controls: FloatArray) -> float:
    design = np.column_stack([np.ones(x.size), controls])
    rx = x - design @ np.linalg.lstsq(design, x, rcond=None)[0]
    ry = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
    denom = math.sqrt(float(rx @ rx) * float(ry @ ry))
    return float(rx @ ry / denom) if denom > 0 else 0.0
