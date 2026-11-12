"""Descriptive observations: facts computed exactly, shown next to the tested findings.

They are not hypothesis tests and carry no evidence grade. Each states the rule that produced
it, how many records it concerns and where to look:

* data-quality issues from the profile (critical and warning issues of the analyzed table);
* possible leakage: a column that almost determines the chosen target;
* unusual records: an Isolation Forest (Liu, Ting & Zhou, 2008) over the numeric columns, with
  the 1% most unusual rows listed and explained by their most extreme values (robust z-scores).
  Unusual is not the same as wrong.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import polars as pl
from pydantic import BaseModel

from edaforge.discovery import charts
from edaforge.discovery.base import AnalysisSpec
from edaforge.discovery.stats import rank
from edaforge.explain.language import fmt_num, md_code
from edaforge.models import ChartSpec
from edaforge.profile import DatasetProfile, QualityIssue

__all__ = ["Observation", "anomalies", "leakage", "quality_observations"]

Severity = Literal["critical", "warning", "info"]


class Observation(BaseModel):
    id: str = ""
    kind: Literal["data_quality", "anomaly", "leakage", "formula"]
    family: str
    headline: str
    plain: str
    analyst: str
    scientist: str
    variables: list[str] = []
    severity: Severity
    records: int | None = None
    share: float | None = None
    method: str
    facts: dict[str, Any] = {}
    charts: list[ChartSpec] = []
    caveats: list[str] = []


def _issue_text(issue: QualityIssue) -> tuple[str, str, str]:
    cols = ", ".join(md_code(c) for c in issue.columns) or "the whole table"
    examples = ", ".join(md_code(e) for e in issue.examples[:6])
    rows = ", ".join(str(r) for r in issue.rows[:12])
    plain = (
        f"# {issue.title}\n\n"
        f"- **What was found:** {issue.detail}\n"
        f"- **Where:** {cols}{f'; for example {examples}' if examples else ''}.\n"
        "- **How sure is this?** This is a direct count, not an estimate.\n"
        "- **What this does not mean:** a data check flags patterns that often indicate "
        "errors; the values may still be legitimate. Nothing was changed or removed.\n"
        "- **Sensible next step:** look at the listed rows in the source file and decide "
        "whether to correct them.\n"
    )
    analyst = (
        f"# {issue.title}\n\n"
        f"| Quantity | Value |\n| --- | --- |\n"
        f"| Category | {issue.category} |\n| Severity | {issue.severity} |\n"
        f"| Records affected | {fmt_num(issue.count) if issue.count is not None else 'n/a'} |\n"
        f"| Share of rows | "
        f"{f'{100 * issue.share:.1f}%' if issue.share is not None else 'n/a'} |\n\n"
        f"{issue.detail}\n\n"
        + (f"**Examples:** {examples}\n\n" if examples else "")
        + (
            (
                f"**Row numbers:** "
                f"{rows}{', …' if issue.count and issue.count > len(issue.rows) else ''}\n"
            )
            if rows
            else ""
        )
    )
    scientist = (
        f"# Rule: {issue.title}\n\n"
        f"**Check.** {issue.method}.\n\n"
        "This is a descriptive data check computed on every row of the table. It involves no "
        "statistical test, no p-value and no sampling; the count is exact.\n"
    )
    return plain, analyst, scientist


def quality_observations(profile: DatasetProfile, spec: AnalysisSpec) -> list[Observation]:
    out: list[Observation] = []
    for issue in profile.issues:
        if issue.severity == "info" and issue.category != "outliers":
            continue
        if issue.category == "outliers" and (issue.share or 0.0) < 0.001:
            continue
        plain, analyst, scientist = _issue_text(issue)
        severity: Severity = issue.severity
        out.append(
            Observation(
                kind="data_quality",
                family="data_quality",
                headline=issue.title,
                plain=plain,
                analyst=analyst,
                scientist=scientist,
                variables=issue.columns,
                severity=severity,
                records=issue.count,
                share=issue.share,
                method=issue.method,
                facts={
                    "issue_id": issue.id,
                    "category": issue.category,
                    "examples": issue.examples,
                    "rows": issue.rows,
                },
            )
        )
    return out


def leakage(frame: pl.DataFrame, spec: AnalysisSpec) -> list[Observation]:
    """Columns that almost determine the target: possibly recorded after (or from) the outcome."""
    target = spec.target
    if target is None:
        return []
    out: list[Observation] = []
    numeric, categorical = spec.predictors()
    if spec.target_kind == "numeric":
        t = frame[target]
        for column in numeric:
            rows = frame.select(column, target).drop_nulls()
            if rows.height < 30:
                continue
            x = rows[column].cast(pl.Float64).to_numpy()
            y = rows[target].cast(pl.Float64).to_numpy()
            if float(x.std()) == 0 or float(y.std()) == 0:
                continue
            rho = float(np.corrcoef(rank(x), rank(y))[0, 1])
            if abs(rho) >= 0.95:
                out.append(_leak(column, target, f"Spearman ρ = {fmt_num(rho)}", rows.height))
        del t
    else:
        for column in [*numeric, *categorical]:
            rows = frame.select(column, target).drop_nulls()
            if rows.height < 30:
                continue
            groups = rows.group_by(column).agg(
                pl.col(target).n_unique().alias("k"), pl.len().alias("n")
            )
            pure = int(groups.filter(pl.col("k") == 1)["n"].sum())
            if (
                column in categorical
                and pure / rows.height >= 0.98
                and groups.height < rows.height * 0.5
            ):
                out.append(
                    _leak(
                        column,
                        target,
                        (
                            f"{100 * pure / rows.height:.1f}% of rows have a "
                            f"{md_code(column)} value that always comes with the same "
                            f"{md_code(target)}"
                        ),
                        rows.height,
                    )
                )
    return out


def _leak(column: str, target: str, measure: str, n: int) -> Observation:
    plain = (
        f"# {md_code(column)} almost determines {md_code(target)}: check for leakage\n\n"
        f"- **What was found:** knowing {md_code(column)} nearly fixes {md_code(target)} "
        f"({measure}).\n"
        "- **Why it matters:** a column like this is often recorded after the outcome, or "
        "computed from it. Patterns that use it can look strong and mean nothing for prediction.\n"
        "- **How sure is this?** This is a direct measurement on the data, not a test.\n"
        f"- **What this does not mean:** it does not show that {md_code(column)} explains "
        f"{md_code(target)}.\n"
        f"- **Sensible next step:** check how {md_code(column)} is produced; exclude it if "
        f"it comes after or from the outcome.\n"
    )
    analyst = (
        f"# Possible leakage: {md_code(column)} → {md_code(target)}\n\n- Measure: "
        f"{measure}\n- Rows: {n:,}\n"
    )
    scientist = (
        "# Rule: possible leakage\n\n**Check.** Numeric target: |Spearman ρ| ≥ 0.95 with a "
        "predictor. Categorical target: "
        "≥ 98% of rows have a predictor value that always comes with one target value. "
        "Descriptive check; no test.\n"
    )
    return Observation(
        kind="leakage",
        family="data_quality",
        headline=f"{column} almost determines {target}: possible leakage",
        plain=plain,
        analyst=analyst,
        scientist=scientist,
        variables=[column, target],
        severity="warning",
        records=n,
        method="near-perfect association with the target",
        facts={"column": column, "target": target, "measure": measure},
    )


def anomalies(
    frame: pl.DataFrame, rows: pl.Series, spec: AnalysisSpec, seed: int
) -> list[Observation]:
    """The 1% most unusual records across the numeric columns (Isolation Forest)."""
    numeric = list(spec.numeric)
    if len(numeric) < 2 or frame.height < 200:
        return []
    from sklearn.ensemble import IsolationForest  # pyright: ignore[reportMissingTypeStubs]

    columns: list[str] = []
    scaled: list[np.ndarray[Any, np.dtype[np.float64]]] = []
    raw: dict[str, np.ndarray[Any, np.dtype[np.float64]]] = {}
    imputed = 0
    for c in numeric:
        v = frame[c].cast(pl.Float64).to_numpy()
        present = v[np.isfinite(v)]
        if present.size < frame.height * 0.5:
            continue
        med = float(np.median(present))
        q1, q3 = np.quantile(present, [0.25, 0.75])
        scale = float(q3 - q1) / 1.349 or float(present.std()) or 0.0
        if scale == 0:
            continue
        imputed += int((~np.isfinite(v)).sum())
        filled = np.where(np.isfinite(v), v, med)
        columns.append(c)
        raw[c] = filled
        scaled.append((filled - med) / scale)
    if len(columns) < 2:
        return []
    X = np.column_stack(scaled)
    # scikit-learn ships no complete type information.
    model: Any = IsolationForest(n_estimators=200, random_state=seed, contamination="auto")
    model.fit(X)
    score: np.ndarray[Any, np.dtype[np.float64]] = -model.score_samples(X)
    k = int(min(100, max(5, math.ceil(0.01 * frame.height))))
    top = np.argsort(-score)[:k]
    threshold = float(score[top[-1]])
    records: list[dict[str, Any]] = []
    driver_counts: dict[str, int] = {}
    for i in top:
        z = X[i]
        order = np.argsort(-np.abs(z))[:2]
        drivers: list[dict[str, Any]] = [
            {"column": columns[j], "value": float(raw[columns[j]][i]), "z": float(z[j])}
            for j in order
        ]
        for d in drivers[:1]:
            driver_counts[d["column"]] = driver_counts.get(d["column"], 0) + 1
        records.append({"row": int(rows[int(i)]), "score": float(score[i]), "drivers": drivers})
    main = sorted(driver_counts, key=lambda c: -driver_counts[c])
    xcol = main[0]
    ycol = main[1] if len(main) > 1 else next(c for c in columns if c != xcol)
    flagged = np.zeros(frame.height, dtype=bool)
    flagged[top] = True
    rng = np.random.default_rng(seed)
    normal_idx = np.flatnonzero(~flagged)
    sampled = normal_idx.size > 1500
    if sampled:
        normal_idx = rng.choice(normal_idx, 1500, replace=False)
    points = [
        {
            "x": float(raw[xcol][i]),
            "y": float(raw[ycol][i]),
            "flag": False,
            "row": int(rows[int(i)]),
        }
        for i in normal_idx
    ]
    points += [
        {"x": float(raw[xcol][i]), "y": float(raw[ycol][i]), "flag": True, "row": int(rows[int(i)])}
        for i in top
    ]
    extreme = max(abs(d["z"]) for r in records for d in r["drivers"])
    lines = "\n".join(
        f"| {r['row']} | {fmt_num(r['score'])} | "
        + "; ".join(
            f"{md_code(d['column'])} = {fmt_num(d['value'])} ({fmt_num(d['z'])} robust SD)"
            for d in r["drivers"]
        )
        + " |"
        for r in records[:25]
    )
    plain = (
        f"# {k} records look unusual, mostly because of {md_code(xcol)}\n\n"
        f"- **What was found:** the {k} most unusual of {frame.height:,} rows (1%) stand out "
        f"from the rest across "
        f"{len(columns)} numeric columns; most of them are unusual in {md_code(xcol)}.\n"
        "- **Why it matters:** unusual records are often data-entry errors, special cases or "
        "the most interesting events.\n"
        "- **How sure is this?** This is a ranking of how unusual each row is, not a test; "
        "every dataset has a most unusual 1%.\n"
        "- **What this does not mean:** unusual is not the same as wrong. Nothing was removed.\n"
        "- **Sensible next step:** look up the listed row numbers in the source file.\n"
    )
    analyst = (
        f"# The {k} most unusual records\n\n| Row in file | Unusualness score | Most extreme "
        f"values |\n| --- | --- | --- |\n{lines}\n\n"
        f"Score threshold for the list: {fmt_num(threshold)}. Robust SD = (value − median) / "
        f"(IQR / 1.349).\n"
        + (
            (
                f"\n{imputed:,} missing numeric values were filled with the column median "
                f"for this model only.\n"
            )
            if imputed
            else ""
        )
    )
    scientist = (
        "# Method: Isolation Forest\n\n"
        f"An Isolation Forest (200 trees, seed {seed}) on {len(columns)} numeric columns "
        f"({', '.join(md_code(c) for c in columns)}), each "
        "centred on its median and scaled by IQR / 1.349. The score is the negative mean "
        "path length (higher is more unusual); the "
        f"top 1% (at least 5, at most 100 rows) is listed. Missing values: median-filled for "
        f"the model only ({imputed:,} cells). "
        "This is a descriptive ranking; it has no false-alarm guarantee.\n"
    )
    chart = charts.anomaly_scatter(points, xcol, ycol, frame.height, sampled)
    return [
        Observation(
            kind="anomaly",
            family="anomalies",
            headline=f"{k} records look unusual, mostly because of {xcol}",
            plain=plain,
            analyst=analyst,
            scientist=scientist,
            variables=columns,
            severity="warning" if extreme >= 10 else "info",
            records=k,
            share=k / frame.height,
            method="Isolation Forest over robust-scaled numeric columns; top 1% listed",
            facts={
                "records": records,
                "columns": columns,
                "threshold": threshold,
                "imputed": imputed,
            },
            charts=[chart],
            caveats=[
                "Unusual is not the same as wrong; check the records before changing anything."
            ],
        )
    ]
