"""Subgroups and interactions for a chosen outcome (target).

* Single conditions: each category level, and for numeric columns the lowest/highest quarter
  and below/above the median (thresholds from the data the search sees, frozen for checking).
* Pairs of conditions on different columns, combined from the strongest single conditions.
  A pair is reported only when its difference exceeds both of its single conditions; a separate
  hypothesis tests the synergy itself (the 2×2 interaction, HC3-robust).

Every evaluated subgroup is registered in the ledger, so the false-discovery control counts the
whole search, not only the winners. Subgroups smaller than ``min_support`` rows (default 30)
are never tested and never shown.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, ClassVar, cast

import numpy as np
import polars as pl
from scipy import stats

from edaforge.discovery import charts
from edaforge.discovery.base import (
    BaseAnalyzer,
    binary_array,
    measure_stability,
    stability_rng,
)
from edaforge.discovery.stats import FloatArray, hc3_ols
from edaforge.models import (
    Candidate,
    ChartSpec,
    ColumnRef,
    Condition,
    Confirmation,
    Effect,
    EvidenceDraft,
    Finding,
    FindingKind,
    PatternClass,
    Predicate,
)
from edaforge.plugins.sdk import AnalysisData, RunContext, Task
from edaforge.rigor.assumptions import AssumptionSpec

__all__ = ["Subgroups"]

_BEAM = 12


def _round(value: float) -> float:
    if value == 0 or not math.isfinite(value):
        return value
    digits = 3 - math.floor(math.log10(abs(value))) - 1
    return round(value, max(digits, 0))


def _cond_text(cond: dict[str, Any]) -> str:
    value = cond["value"]
    shown = f"{value:g}" if isinstance(value, float) else str(value)
    return f"{cond['column']} {cond['op']} {shown}"


def _mask(frame: pl.DataFrame, cond: dict[str, Any]) -> np.ndarray[Any, np.dtype[np.bool_]]:
    col = frame[cond["column"]]
    op, value = cond["op"], cond["value"]
    if op == "=":
        out = col.cast(pl.String) == str(value)
    elif op == "≤":
        out = col.cast(pl.Float64) <= float(value)
    elif op == ">":
        out = col.cast(pl.Float64) > float(value)
    elif op == "≥":
        out = col.cast(pl.Float64) >= float(value)
    else:  # "<"
        out = col.cast(pl.Float64) < float(value)
    return out.fill_null(False).to_numpy()


def _wilson(p: float, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _newcombe(p1: float, n1: int, p2: float, n2: int) -> tuple[float, float]:
    """Newcombe (1998) hybrid score interval for p1 − p2."""
    l1, u1 = _wilson(p1, n1)
    l2, u2 = _wilson(p2, n2)
    d = p1 - p2
    return d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt(
        (u1 - p1) ** 2 + (p2 - l2) ** 2
    )


class Subgroups(BaseAnalyzer):
    name: ClassVar[str] = "reveal.subgroups"
    pattern_class: ClassVar[PatternClass] = PatternClass.SUBGROUP
    label: ClassVar[str] = "Segments and combinations"
    family: ClassVar[str] = "subgroups"
    template: ClassVar[str] = "subgroup"
    method_summary: ClassVar[str] = (
        "Beam search over single conditions and pairs; Welch t (numeric outcome) or "
        "two-proportion / Fisher exact test (yes/no outcome); HC3 interaction test for synergy"
    )
    assumptions: ClassVar[Sequence[AssumptionSpec]] = (
        AssumptionSpec(
            name="independent_rows",
            description="Rows are independent records of the outcome.",
            severity="major",
            check=None,
        ),
    )

    # ------------------------------------------------------------------ helpers
    def _y(self, frame: pl.DataFrame) -> tuple[FloatArray, np.ndarray[Any, np.dtype[np.bool_]]]:
        target = self.spec.target
        if target is None:
            msg = "a subgroup search needs a target column"
            raise ValueError(msg)
        col = frame[target]
        present = col.is_not_null().to_numpy()
        if self.spec.target_kind == "binary":
            y = binary_array(col.fill_null(""), self.spec.positive)
        else:
            y = col.cast(pl.Float64).fill_null(0.0).to_numpy()
        return y, present

    def _conditions(self, frame: pl.DataFrame) -> list[dict[str, Any]]:
        numeric, categorical = self.spec.predictors()
        conds: list[dict[str, Any]] = []
        for column in categorical:
            counts = frame[column].cast(pl.String).drop_nulls().value_counts(sort=True)
            for level, count in zip(
                counts[counts.columns[0]].to_list(), counts["count"].to_list(), strict=True
            ):
                if (
                    int(count) >= self.spec.min_support
                    and int(count) <= frame.height - self.spec.min_support
                ):
                    conds.append(
                        {
                            "key": f"{column}=={level}",
                            "column": column,
                            "op": "=",
                            "value": str(level),
                            "kind": "category",
                        }
                    )
        for column in numeric:
            values = frame[column].drop_nulls().cast(pl.Float64).to_numpy()
            if values.size < 2 * self.spec.min_support or np.unique(values).size < 4:
                continue
            q1, med, q3 = (float(v) for v in np.quantile(values, [0.25, 0.5, 0.75]))
            for key, op, value in (
                ("le_q25", "≤", q1),
                ("gt_q50", ">", med),
                ("le_q50", "≤", med),
                ("ge_q75", "≥", q3),
            ):
                conds.append(
                    {
                        "key": f"{column}:{key}",
                        "column": column,
                        "op": op,
                        "value": _round(value),
                        "kind": key,
                    }
                )
        return conds

    def _test(
        self,
        y: FloatArray,
        inside: np.ndarray[Any, np.dtype[np.bool_]],
        valid: np.ndarray[Any, np.dtype[np.bool_]],
    ) -> dict[str, Any] | None:
        a = inside & valid
        b = ~inside & valid
        n_in, n_out = int(a.sum()), int(b.sum())
        if n_in < self.spec.min_support or n_out < self.spec.min_support:
            return None
        yi, yo = y[a], y[b]
        if self.spec.target_kind == "binary":
            k_in, k_out = int(yi.sum()), int(yo.sum())
            p_in, p_out = k_in / n_in, k_out / n_out
            pooled = (k_in + k_out) / (n_in + n_out)
            table = [[k_in, n_in - k_in], [k_out, n_out - k_out]]
            expected_min = min(n_in, n_out) * min(pooled, 1 - pooled)
            if expected_min < 5:
                _, p = stats.fisher_exact(table)
                test = "fisher_exact"
                stat = p_in - p_out
            else:
                se = math.sqrt(pooled * (1 - pooled) * (1 / n_in + 1 / n_out)) or 1e-12
                stat = (p_in - p_out) / se
                p = float(2 * stats.norm.sf(abs(stat)))
                test = "two_proportion_z"
            lo, hi = _newcombe(p_in, n_in, p_out, n_out)
            return {
                "n_in": n_in,
                "n_out": n_out,
                "value_in": p_in,
                "value_out": p_out,
                "diff": p_in - p_out,
                "diff_low": lo,
                "diff_high": hi,
                "p": float(p),
                "stat": float(stat),
                "test": test,
                "std": (p_in - p_out) / max(math.sqrt(pooled * (1 - pooled)), 1e-9),
                "ratio": (p_in / p_out) if p_out > 0 else None,
            }
        if float(np.ptp(y[valid])) == 0:
            return None
        res = stats.ttest_ind(yi, yo, equal_var=False)
        va, vb = np.var(yi, ddof=1) / n_in, np.var(yo, ddof=1) / n_out
        se = math.sqrt(va + vb) or 1e-12
        df = (va + vb) ** 2 / max(va**2 / (n_in - 1) + vb**2 / (n_out - 1), 1e-300)
        t = float(stats.t.ppf(0.975, df))
        diff = float(yi.mean() - yo.mean())
        sd = float(np.std(y[valid], ddof=1)) or 1.0
        return {
            "n_in": n_in,
            "n_out": n_out,
            "value_in": float(yi.mean()),
            "value_out": float(yo.mean()),
            "diff": diff,
            "diff_low": diff - t * se,
            "diff_high": diff + t * se,
            "p": float(res.pvalue),
            "stat": float(res.statistic),
            "test": "welch_t",
            "std": diff / sd,
            "ratio": None,
        }

    def _floor(self) -> float:
        return 0.01 if self.spec.target_kind == "binary" else 0.1

    def _effect_size(self, r: dict[str, Any]) -> float:
        return abs(r["diff"]) if self.spec.target_kind == "binary" else abs(r["std"])

    # ------------------------------------------------------------------ protocol
    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        self._conds = self._conditions(data.frame)
        self._results: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        tasks = [Task(key=f"1|{c['key']}", params={"condition": c}) for c in self._conds]
        tasks.append(Task(key="2|pairs", params={}))
        self.begin(len(tasks))
        return tasks

    def _candidate(
        self,
        ctx: RunContext,
        key: str,
        conds: list[dict[str, Any]],
        hid: str,
        r: dict[str, Any],
        kind: FindingKind,
        extra: dict[str, Any],
    ) -> Candidate:
        text = " and ".join(_cond_text(c) for c in conds)
        target = self.spec.target or ""
        return Candidate(
            key=key,
            analyzer=self.name,
            kind=kind,
            pattern_class=PatternClass.COMBINATION
            if kind == FindingKind.INTERACTION
            else self.pattern_class,
            title=f"{target} differs when {text}",
            variables=[ColumnRef(column=target), *[ColumnRef(column=c["column"]) for c in conds]],
            subgroup=Predicate(
                conditions=[
                    Condition(
                        column=ColumnRef(column=c["column"]),
                        op=_kernel_op(c["op"]),
                        value=c["value"],
                    )
                    for c in conds
                ],
                text=text,
            ),
            hypothesis_id=hid,
            test=r["test"],
            statistic=r["stat"],
            p_value=None,
            params={"conditions": [*conds], "kind": kind.value},
            facts={"explore_n_in": r["n_in"], "explore_diff": r["diff"], **extra},
        )

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        self.tick(ctx)
        target = self.spec.target or ""
        y, valid = self._y(data)
        if task.key.startswith("1|"):
            cond = dict(cast("dict[str, Any]", task.params["condition"]))
            hid = ctx.ledger.register(
                hypothesis=f"{target} is the same when {_cond_text(cond)} as otherwise",
                family=["subgroups", "single"],
                test="welch_t" if self.spec.target_kind != "binary" else "two_proportion",
                params={"conditions": [cond]},
            )
            r = self._test(y, _mask(data, cond), valid)
            if r is None:
                return []
            res = ctx.ledger.analytic_test(
                hid, statistic=r["stat"], p_value=r["p"], n_obs=r["n_in"] + r["n_out"]
            )
            self._results[cond["key"]] = (cond, r)
            if self._effect_size(r) < self._floor():
                return []
            cand = self._candidate(
                ctx, f"s|{cond['key']}", [cond], hid, r, FindingKind.SUBGROUP, {"depth": 1}
            )
            return [cand.model_copy(update={"p_value": res.p_value})]
        # Pairs of conditions from the strongest singles.
        ranked = sorted(
            self._results.values(),
            key=lambda cr: (
                -abs(cr[1]["stat"]) * math.sqrt(cr[1]["n_in"] / (cr[1]["n_in"] + cr[1]["n_out"]))
            ),
        )
        beam = ranked[:_BEAM]
        out: list[Candidate] = []
        seen: set[tuple[str, str]] = set()
        for c1, r1 in beam:
            for c2, r2 in self._results.values():
                if c2["column"] == c1["column"]:
                    continue
                pair = tuple(sorted((c1["key"], c2["key"])))
                if pair in seen:
                    continue
                seen.add(pair)
                conds = [c1, c2] if c1["key"] == pair[0] else [c2, c1]
                text = " and ".join(_cond_text(c) for c in conds)
                m1, m2 = _mask(data, conds[0]), _mask(data, conds[1])
                hid = ctx.ledger.register(
                    hypothesis=f"{target} is the same when {text} as otherwise",
                    family=["subgroups", "pairs"],
                    test="welch_t" if self.spec.target_kind != "binary" else "two_proportion",
                    params={"conditions": [*conds]},
                )
                r = self._test(y, m1 & m2, valid)
                if r is None:
                    continue
                res = ctx.ledger.analytic_test(
                    hid, statistic=r["stat"], p_value=r["p"], n_obs=r["n_in"] + r["n_out"]
                )
                hid_ix = ctx.ledger.register(
                    hypothesis=(
                        f"{conds[0]['column']} and {conds[1]['column']} conditions do not "
                        f"interact for {target}"
                    ),
                    family=["subgroups", "interactions"],
                    test="hc3_interaction",
                    params={"conditions": [*conds]},
                )
                ix = _interaction(y, m1, m2, valid, self.spec.min_cell)
                if ix is None:
                    continue
                res_ix = ctx.ledger.analytic_test(
                    hid_ix, statistic=ix["z"], p_value=ix["p"], n_obs=int(valid.sum())
                )
                singles = max(self._effect_size(r1), self._effect_size(r2))
                if self._effect_size(r) > 1.1 * singles and self._effect_size(r) >= self._floor():
                    cand = self._candidate(
                        ctx,
                        f"s|{pair[0]}&{pair[1]}",
                        conds,
                        hid,
                        r,
                        FindingKind.SUBGROUP,
                        {"depth": 2},
                    )
                    out.append(cand.model_copy(update={"p_value": res.p_value}))
                if abs(ix["did"]) >= (
                    self._floor()
                    if self.spec.target_kind == "binary"
                    else 0.1 * (float(np.std(y[valid], ddof=1)) or 1.0)
                ):
                    cand_ix = self._candidate(
                        ctx,
                        f"i|{pair[0]}&{pair[1]}",
                        conds,
                        hid_ix,
                        {**r, "test": "hc3_interaction", "stat": ix["z"]},
                        FindingKind.INTERACTION,
                        {"depth": 2, "explore_did": ix["did"]},
                    )
                    out.append(
                        cand_ix.model_copy(
                            update={
                                "p_value": res_ix.p_value,
                                "test": "hc3_interaction",
                                "statistic": ix["z"],
                            }
                        )
                    )
        return out

    def _measure(
        self, cand: Candidate, data: pl.DataFrame, ctx: RunContext
    ) -> tuple[Effect | None, dict[str, Any], dict[str, Any] | None]:
        conds = list(cast("list[dict[str, Any]]", cand.params["conditions"]))
        y, valid = self._y(data)
        masks = [_mask(data, c) for c in conds]
        inside = masks[0] if len(masks) == 1 else masks[0] & masks[1]
        r = self._test(y, inside, valid)
        binary = self.spec.target_kind == "binary"
        facts: dict[str, Any] = {
            "template": "interaction" if cand.kind == FindingKind.INTERACTION else self.template,
            "target": self.spec.target,
            "binary": binary,
            "positive": self.spec.positive,
            "conditions": [{**c, "text": _cond_text(c)} for c in conds],
            "text": " and ".join(_cond_text(c) for c in conds),
            "n": int(valid.sum()),
            "overall": float(y[valid].mean()) if valid.any() else 0.0,
            "depth": len(conds),
        }
        if r is None:
            return None, facts, None
        facts.update(
            {
                k: r[k]
                for k in (
                    "n_in",
                    "n_out",
                    "value_in",
                    "value_out",
                    "diff",
                    "diff_low",
                    "diff_high",
                    "ratio",
                    "test",
                )
            }
        )
        facts["share_in"] = r["n_in"] / max(int(valid.sum()), 1)
        if len(conds) == 2:
            parents: list[dict[str, Any]] = []
            for c, m in zip(conds, masks, strict=True):
                pr = self._test(y, m, valid)
                if pr is not None:
                    parents.append(
                        {
                            "text": _cond_text(c),
                            "n_in": pr["n_in"],
                            "value_in": pr["value_in"],
                            "diff": pr["diff"],
                        }
                    )
            facts["parents"] = parents
        measure = "risk_diff" if binary else "mean_diff"
        effect = Effect(
            measure=measure,
            estimate=r["diff"],
            ci_low=r["diff_low"],
            ci_high=r["diff_high"],
            ci_method="Newcombe hybrid score" if binary else "Welch t",
            split=ctx.split,
            units="percentage points" if binary else None,
        )
        ix = None
        if cand.kind == FindingKind.INTERACTION:
            ix = _interaction(y, masks[0], masks[1], valid, self.spec.min_cell)
            if ix is not None:
                facts.update(
                    {
                        "did": ix["did"],
                        "did_low": ix["low"],
                        "did_high": ix["high"],
                        "cells": ix["cells"],
                    }
                )
                effect = Effect(
                    measure="interaction_" + measure,
                    estimate=ix["did"],
                    ci_low=ix["low"],
                    ci_high=ix["high"],
                    ci_method="HC3 robust normal interval",
                    split=ctx.split,
                )
        facts["std_effect"] = r["std"]
        return effect, facts, ix

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        effect, facts, _ = self._measure(cand, data, ctx)
        return cand.model_copy(update={"effect": effect, "facts": {**facts, **cand.facts}})

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        conds = list(cast("list[dict[str, Any]]", cand.params["conditions"]))
        text = " and ".join(_cond_text(c) for c in conds)
        is_ix = cand.kind == FindingKind.INTERACTION
        hid = ctx.ledger.register(
            hypothesis=(
                f"no interaction of {text} for {self.spec.target}"
                if is_ix
                else f"{self.spec.target} is the same when {text} (confirmation)"
            ),
            family=["subgroups", "confirmation"],
            test=cand.test,
            params=dict(cand.params),
            parent_id=cand.hypothesis_id,
        )
        effect, facts, ix = self._measure(cand, sealed, ctx)
        method = "sealed_holdout" if ctx.split == "confirmation" else "cross_fit"
        if effect is None or (is_ix and ix is None):
            ctx.ledger.mark_untestable(
                hid,
                reason=f"segment has fewer than {self.spec.min_support} rows in the data set aside",
                n_obs=int(facts["n"]),
            )
            return EvidenceDraft(
                test=cand.test,
                statistic=cand.statistic,
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id, hid],
                n=facts["n"],
                confirmation=Confirmation(
                    status="not_confirmed", method=method, hypothesis_ids=[hid]
                ),
                facts=facts,
                caveats=[
                    (
                        f"The segment has fewer than {self.spec.min_support} rows in the "
                        f"data set aside for the check."
                    )
                ],
            )
        y, valid = self._y(sealed)
        masks = [_mask(sealed, c) for c in conds]
        inside = masks[0] if len(masks) == 1 else masks[0] & masks[1]
        if is_ix and ix is not None:
            stat_value, p_value = float(ix["z"]), float(ix["p"])
        else:
            r = self._test(y, inside, valid)
            if r is None:  # unreachable: _measure ran the same test and returned an effect
                msg = "the confirmation test lost its support between measuring and testing"
                raise ValueError(msg)
            stat_value, p_value = float(r["stat"]), float(r["p"])
        result = ctx.ledger.analytic_test(
            hid, statistic=stat_value, p_value=p_value, n_obs=int(valid.sum())
        )
        sign = np.sign(effect.estimate) or 1.0
        idx_all = np.arange(y.size)

        def holds(idx: np.ndarray[Any, np.dtype[np.int64]]) -> bool:
            sub_valid = np.zeros(y.size, dtype=bool)
            sub_valid[idx_all[idx]] = True
            sub_valid &= valid
            if is_ix:
                res = _interaction(y, masks[0], masks[1], sub_valid, self.spec.min_cell)
                return bool(res is not None and res["p"] < 0.05 and np.sign(res["did"]) == sign)
            res2 = self._test(y, inside, sub_valid)
            return bool(res2 is not None and res2["p"] < 0.05 and np.sign(res2["diff"]) == sign)

        stability = measure_stability(y.size, stability_rng(ctx, cand.key), holds)
        a, b = y[inside & valid], y[~inside & valid]
        specs: list[dict[str, Any]] = []
        if is_ix and ix is not None:
            specs.append({"name": "HC3 interaction test", "agrees": ix["p"] < 0.05})
            specs.append(
                {"name": "classical OLS interaction test", "agrees": ix["p_classic"] < 0.05}
            )
        elif self.spec.target_kind == "binary":
            specs.append({"name": "two-proportion z-test", "agrees": p_value < 0.05})
            table = [[int(a.sum()), int(a.size - a.sum())], [int(b.sum()), int(b.size - b.sum())]]
            specs.append(
                {"name": "Fisher exact test", "agrees": bool(stats.fisher_exact(table)[1] < 0.05)}
            )
        else:
            specs.append({"name": "Welch t-test", "agrees": p_value < 0.05})
            specs.append(
                {"name": "Mann-Whitney U", "agrees": bool(stats.mannwhitneyu(a, b).pvalue < 0.05)}
            )
        facts["specs"] = specs
        facts["stability"] = stability
        return EvidenceDraft(
            test=cand.test,
            statistic=cand.statistic,
            p_value=cand.p_value,
            hypothesis_ids=[cand.hypothesis_id, hid],
            n=int(valid.sum()),
            confirmation=Confirmation(
                status="pending",
                method=method,
                p_value=result.p_value,
                hypothesis_ids=[hid],
                n=int(valid.sum()),
            ),
            effect=effect,
            stability=stability,
            specs_consistent=sum(1 for s in specs if s["agrees"]),
            specs_total=len(specs),
            facts=facts,
            caveats=[
                (
                    "Segments were found by searching many combinations; the check on data "
                    "the search did not see guards against chance finds."
                )
            ],
        )

    def charts(self, finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
        if finding.kind == FindingKind.INTERACTION:
            return charts.interaction(finding)
        return charts.subgroup(finding)


def _kernel_op(op: str) -> Any:
    return {"=": "==", "≤": "<=", ">": ">", "≥": ">=", "<": "<"}[op]


def _interaction(
    y: FloatArray,
    a: np.ndarray[Any, np.dtype[np.bool_]],
    b: np.ndarray[Any, np.dtype[np.bool_]],
    valid: np.ndarray[Any, np.dtype[np.bool_]],
    min_cell: int,
) -> dict[str, Any] | None:
    """2×2 interaction of two conditions: difference in differences with HC3 inference."""
    ya, aa, bb = y[valid], a[valid].astype(float), b[valid].astype(float)
    cells: dict[str, dict[str, Any]] = {}
    for name, mask in (
        ("both", (aa == 1) & (bb == 1)),
        ("first_only", (aa == 1) & (bb == 0)),
        ("second_only", (aa == 0) & (bb == 1)),
        ("neither", (aa == 0) & (bb == 0)),
    ):
        k = int(mask.sum())
        if k < min_cell:
            return None
        cells[name] = {"n": k, "value": float(ya[mask].mean())}
    design = np.column_stack([np.ones(ya.size), aa, bb, aa * bb])
    beta, se = hc3_ols(design, ya)
    did = float(beta[3])
    z = did / se[3] if se[3] > 0 else 0.0
    resid = ya - design @ beta
    sigma2 = float(resid @ resid) / max(ya.size - 4, 1)
    se_classic = math.sqrt(max(sigma2 * float(np.linalg.pinv(design.T @ design)[3, 3]), 0))
    t_classic = did / se_classic if se_classic > 0 else 0.0
    return {
        "did": did,
        "z": float(z),
        "p": float(2 * stats.norm.sf(abs(z))),
        "p_classic": float(2 * stats.t.sf(abs(t_classic), max(ya.size - 4, 1))),
        "low": did - 1.959964 * float(se[3]),
        "high": did + 1.959964 * float(se[3]),
        "cells": cells,
    }
