"""Interactive visual exploration and multi-level drill-down/up engine.

Computes exact aggregations, quantiles, confidence intervals, multi-grain time
rollups, hierarchies (sunburst/treemap), histograms, scatter+spline trends, and
contingency heatmaps directly from a dataset's Polars DataFrame.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Literal

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from edaforge.discovery.stats import spline_fit
from edaforge.ingest.infer import ColumnInfo

__all__ = [
    "DrillFilter",
    "ExploreQuery",
    "ExploreResponse",
    "explore_dataset",
]

FilterOp = Literal["eq", "in", "range", "date_range"]
ExploreMode = Literal[
    "auto", "group", "boxplot", "hierarchy", "time", "histogram", "scatter", "heatmap"
]
AggKind = Literal["count", "share", "mean", "median", "sum"]
TimeGrain = Literal["auto", "year", "quarter", "month", "week", "day"]

_GRAIN_ORDER: list[Literal["year", "quarter", "month", "week", "day"]] = [
    "year",
    "quarter",
    "month",
    "week",
    "day",
]
_NULL_LABEL = "(missing)"
_MAX_SCATTER = 1600
_MAX_CATS = 24


def _finite(val: float | int | None) -> float | None:
    if val is None:
        return None
    f = float(val)
    return f if math.isfinite(f) else None


class DrillFilter(BaseModel):
    column: str
    op: FilterOp = "eq"
    value: str | float | int | bool | None = None
    values: list[str] = Field(default_factory=list[str])
    low: float | str | None = None
    high: float | str | None = None
    label: str | None = None


class ExploreQuery(BaseModel):
    mode: ExploreMode = "auto"
    x: str | None = None
    y: str | None = None
    group: str | None = None
    dimensions: list[str] = Field(default_factory=list[str])
    agg: AggKind = "mean"
    time_grain: TimeGrain = "auto"
    bins: int = Field(default=28, ge=5, le=80)
    filters: list[DrillFilter] = Field(default_factory=list[DrillFilter])


class ExploreResponse(BaseModel):
    mode: str
    x: str | None = None
    y: str | None = None
    group: str | None = None
    agg: str
    total_rows: int
    matched_rows: int
    title: str
    subtitle: str
    grain_used: str | None = None
    next_grain: str | None = None
    prev_grain: str | None = None
    next_dimensions: list[str] = Field(default_factory=list[str])
    data: dict[str, Any] = Field(default_factory=dict[str, Any])
    summary: dict[str, Any] = Field(default_factory=dict[str, Any])
    sample_columns: list[str] = Field(default_factory=list[str])
    sample_rows: list[list[Any]] = Field(default_factory=list[list[Any]])


def _parse_iso_date(text: str) -> dt.date | None:
    raw = text.strip()[:10]
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


def _date_expr(frame: pl.DataFrame, col: str) -> pl.Expr:
    dtype = frame[col].dtype
    if dtype == pl.Date:
        return pl.col(col)
    if dtype == pl.String:
        return pl.col(col).str.slice(0, 10).str.to_date(strict=False)
    return pl.col(col).cast(pl.Date, strict=False)


def _apply_filters(frame: pl.DataFrame, filters: list[DrillFilter]) -> pl.DataFrame:
    out = frame
    for flt in filters:
        col = flt.column
        if col not in out.columns:
            continue
        series = out[col]
        if flt.op == "eq":
            if flt.value is None or str(flt.value) == _NULL_LABEL:
                out = out.filter(pl.col(col).is_null())
            elif series.dtype == pl.Boolean:
                bval = str(flt.value).lower() in {"true", "1", "yes"}
                out = out.filter(pl.col(col) == bval)
            else:
                out = out.filter(pl.col(col).cast(pl.String) == str(flt.value))
        elif flt.op == "in" and flt.values:
            has_null = _NULL_LABEL in flt.values
            clean_vals = [v for v in flt.values if v != _NULL_LABEL]
            cond = pl.col(col).cast(pl.String).is_in(clean_vals)
            if has_null:
                cond = cond | pl.col(col).is_null()
            out = out.filter(cond)
        elif flt.op == "range":
            expr = pl.lit(True)
            if flt.low is not None:
                expr = expr & (pl.col(col).cast(pl.Float64) >= float(flt.low))
            if flt.high is not None:
                expr = expr & (pl.col(col).cast(pl.Float64) <= float(flt.high))
            out = out.filter(expr)
        elif flt.op == "date_range":
            d_col = _date_expr(out, col)
            expr = pl.lit(True)
            if isinstance(flt.low, str):
                d_lo = _parse_iso_date(flt.low)
                if d_lo is not None:
                    expr = expr & (d_col >= pl.lit(d_lo))
            if isinstance(flt.high, str):
                d_hi = _parse_iso_date(flt.high)
                if d_hi is not None:
                    expr = expr & (d_col < pl.lit(d_hi))
            out = out.filter(expr)
    return out


def _suggest_dimensions(
    frame: pl.DataFrame,
    columns: list[ColumnInfo],
    used: set[str],
) -> list[str]:
    scored: list[tuple[int, str]] = []
    for c in columns:
        if c.pii or c.name in used or c.name not in frame.columns:
            continue
        if c.role in {"categorical", "boolean"}:
            n_u = int(frame[c.name].n_unique())
            if 2 <= n_u <= 40:
                # Prefer crisp 2-12 category dimensions first
                penalty = abs(n_u - 6)
                scored.append((penalty, c.name))
        elif c.role == "datetime":
            scored.append((30, c.name))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [name for _, name in scored[:8]]


def _resolve_mode(
    mode: ExploreMode,
    x_info: ColumnInfo | None,
    y_info: ColumnInfo | None,
    dimensions: list[str],
) -> str:
    if mode != "auto":
        return mode
    if len(dimensions) >= 2:
        return "hierarchy"
    if x_info is None:
        return "group"
    if x_info.role == "datetime":
        return "time"
    if x_info.role == "numeric":
        if y_info is not None and y_info.role == "numeric":
            return "scatter"
        return "histogram"
    if y_info is not None and y_info.role in {"categorical", "boolean"}:
        return "heatmap"
    return "group"


def _numeric_series_stats(arr: np.ndarray[Any, np.dtype[np.float64]]) -> dict[str, Any]:
    clean = arr[np.isfinite(arr)]
    n = int(clean.size)
    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "ci_low": None,
            "ci_high": None,
            "median": None,
            "q1": None,
            "q3": None,
            "min": None,
            "max": None,
            "sum": 0.0,
            "std": None,
        }
    q = np.quantile(clean, [0.0, 0.25, 0.5, 0.75, 1.0])
    mean = float(clean.mean())
    std = float(clean.std(ddof=1)) if n > 1 else 0.0
    se = std / math.sqrt(n) if n > 1 else 0.0
    return {
        "n": n,
        "mean": _finite(mean),
        "ci_low": _finite(mean - 1.96 * se) if n > 1 else _finite(mean),
        "ci_high": _finite(mean + 1.96 * se) if n > 1 else _finite(mean),
        "median": _finite(float(q[2])),
        "q1": _finite(float(q[1])),
        "q3": _finite(float(q[3])),
        "min": _finite(float(q[0])),
        "max": _finite(float(q[4])),
        "sum": _finite(float(clean.sum())),
        "std": _finite(std),
    }


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    z = 1.96
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _build_group(
    sub: pl.DataFrame,
    x: str,
    y: str | None,
    y_info: ColumnInfo | None,
    group: str | None,
    agg: AggKind,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    x_str = sub[x].cast(pl.String).fill_null(_NULL_LABEL)
    work = sub.with_columns(x_str.alias("__x__"))
    total = max(work.height, 1)

    top_levels = (
        work.group_by("__x__").len().sort("len", descending=True).head(_MAX_CATS)["__x__"].to_list()
    )
    work = work.with_columns(
        pl.when(pl.col("__x__").is_in(top_levels))
        .then(pl.col("__x__"))
        .otherwise(pl.lit("(other)"))
        .alias("__x__")
    )

    has_numeric_y = bool(y and y in work.columns and y_info and y_info.role == "numeric")
    has_binary_y = bool(
        y
        and y in work.columns
        and y_info
        and y_info.role in {"boolean", "categorical"}
        and int(work[y].drop_nulls().n_unique()) == 2
    )
    if has_numeric_y:
        eff_agg: str = agg
    elif has_binary_y and agg == "mean":
        eff_agg = "rate"
    else:
        eff_agg = "share" if agg == "share" else "count"

    positive_label: str | None = None
    if has_binary_y and y:
        vals = [str(v) for v in work[y].drop_nulls().cast(pl.String).unique().to_list()]
        vals.sort()
        for pref in ("true", "yes", "1", "returned", "churned"):
            hit = next((v for v in vals if v.lower() == pref), None)
            if hit is not None:
                positive_label = hit
                break
        if positive_label is None and vals:
            positive_label = vals[-1]

    rows_out: list[dict[str, Any]] = []
    if group and group in work.columns and group != x:
        g_str = work[group].cast(pl.String).fill_null(_NULL_LABEL)
        top_g = (
            pl.DataFrame({"__g__": g_str})
            .group_by("__g__")
            .len()
            .sort("len", descending=True)
            .head(8)["__g__"]
            .to_list()
        )
        work = work.with_columns(
            pl.when(g_str.is_in(top_g)).then(g_str).otherwise(pl.lit("(other)")).alias("__g__")
        )
        series_out: list[dict[str, Any]] = []
        for g_val in top_g:
            g_slice = work.filter(pl.col("__g__") == g_val)
            pts: dict[str, dict[str, Any]] = {}
            for x_val in top_levels:
                cell = g_slice.filter(pl.col("__x__") == x_val)
                n_cell = cell.height
                if has_numeric_y and y:
                    arr = cell[y].drop_nulls().cast(pl.Float64).to_numpy()
                    st = _numeric_series_stats(arr)
                    val = st.get(eff_agg if eff_agg in {"mean", "median", "sum"} else "mean")
                    pts[str(x_val)] = {**st, "value": val, "share": n_cell / total}
                elif has_binary_y and y and positive_label is not None:
                    non_null = cell[y].drop_nulls().cast(pl.String)
                    n_nn = non_null.len()
                    k_pos = int((non_null == positive_label).sum()) if n_nn else 0
                    lo, hi = _wilson(k_pos, n_nn)
                    pts[str(x_val)] = {
                        "n": n_nn,
                        "value": (k_pos / n_nn) if n_nn else 0.0,
                        "ci_low": lo,
                        "ci_high": hi,
                    }
                else:
                    pts[str(x_val)] = {
                        "n": n_cell,
                        "value": (n_cell / total) if eff_agg == "share" else n_cell,
                        "share": n_cell / total,
                    }
            series_out.append({"name": str(g_val), "points": pts})
        title = f"{y or 'Records'} by {x}, split by {group}"
        sub_txt = f"{sub.height:,} rows · click any bar to drill down"
        return (
            title,
            sub_txt,
            {
                "categories": [str(v) for v in top_levels],
                "series": series_out,
                "metric_label": (
                    f"{eff_agg} of {y}"
                    if has_numeric_y
                    else f"share {y} = {positive_label}"
                    if has_binary_y
                    else eff_agg
                ),
                "is_percent": eff_agg in {"share", "rate"},
            },
            {"n_groups": len(top_levels), "split_by": group},
        )

    has_other = work.filter(pl.col("__x__") == "(other)").height > 0
    for x_val in [*top_levels, *(["(other)"] if has_other else [])]:
        cell = work.filter(pl.col("__x__") == x_val)
        n_cell = cell.height
        if has_numeric_y and y:
            arr = cell[y].drop_nulls().cast(pl.Float64).to_numpy()
            st = _numeric_series_stats(arr)
            chosen_val = st.get(eff_agg if eff_agg in {"mean", "median", "sum"} else "mean")
            rows_out.append(
                {
                    "category": str(x_val),
                    **st,
                    "value": chosen_val,
                    "share": n_cell / total,
                }
            )
        elif has_binary_y and y and positive_label is not None:
            non_null = cell[y].drop_nulls().cast(pl.String)
            n_nn = non_null.len()
            k_pos = int((non_null == positive_label).sum()) if n_nn else 0
            rate = (k_pos / n_nn) if n_nn else 0.0
            lo, hi = _wilson(k_pos, n_nn)
            rows_out.append(
                {
                    "category": str(x_val),
                    "n": n_nn,
                    "value": rate,
                    "mean": rate,
                    "ci_low": lo,
                    "ci_high": hi,
                    "share": n_cell / total,
                }
            )
        else:
            val = (n_cell / total) if eff_agg == "share" else float(n_cell)
            rows_out.append(
                {
                    "category": str(x_val),
                    "n": n_cell,
                    "value": val,
                    "share": n_cell / total,
                }
            )

    rows_out.sort(key=lambda r: float(r.get("value") or 0.0), reverse=True)
    overall_val: float | None = None
    if has_numeric_y and y:
        all_arr = work[y].drop_nulls().cast(pl.Float64).to_numpy()
        all_st = _numeric_series_stats(all_arr)
        overall_val = all_st.get(eff_agg if eff_agg in {"mean", "median", "sum"} else "mean")
        metric_label = f"{eff_agg} {y}"
    elif has_binary_y and y and positive_label is not None:
        nn = work[y].drop_nulls().cast(pl.String)
        overall_val = float((nn == positive_label).sum() / max(nn.len(), 1))
        metric_label = f"share {y} = {positive_label}"
    else:
        metric_label = "share of rows" if eff_agg == "share" else "rows"

    title = f"{metric_label.capitalize()} by {x}"
    subtitle = f"{sub.height:,} rows across {len(rows_out)} groups · click a bar to drill down"
    return (
        title,
        subtitle,
        {
            "rows": rows_out,
            "categories": [r["category"] for r in rows_out],
            "overall": _finite(overall_val),
            "metric_label": metric_label,
            "is_percent": eff_agg in {"share", "rate"},
            "has_box": has_numeric_y,
        },
        {"n_groups": len(rows_out), "overall": _finite(overall_val)},
    )


def _build_hierarchy(
    sub: pl.DataFrame,
    dims: list[str],
    y: str | None,
    y_info: ColumnInfo | None,
    agg: AggKind,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    valid_dims = [d for d in dims if d in sub.columns][:3]
    has_num = bool(y and y in sub.columns and y_info and y_info.role == "numeric")

    def build_level(df: pl.DataFrame, depth: int) -> list[dict[str, Any]]:
        if depth >= len(valid_dims) or df.height == 0:
            return []
        col = valid_dims[depth]
        s = df[col].cast(pl.String).fill_null(_NULL_LABEL)
        w = df.with_columns(s.alias("__h__"))
        counts = w.group_by("__h__").len().sort("len", descending=True).head(12)
        nodes: list[dict[str, Any]] = []
        for row in counts.iter_rows():
            label = str(row[0])
            n_rows = int(row[1])
            child_df = w.filter(pl.col("__h__") == label)
            if has_num and y:
                arr = child_df[y].drop_nulls().cast(pl.Float64).to_numpy()
                clean = arr[np.isfinite(arr)]
                mean_v = float(clean.mean()) if clean.size else 0.0
                sum_v = float(clean.sum()) if clean.size else 0.0
                val = sum_v if agg == "sum" else (mean_v if agg == "mean" else float(n_rows))
            else:
                mean_v = None
                val = float(n_rows)
            node: dict[str, Any] = {
                "name": label,
                "column": col,
                "value": max(0.0, _finite(val) or 0.0),
                "n": n_rows,
                "mean": _finite(mean_v),
            }
            children = build_level(child_df, depth + 1)
            if children:
                node["children"] = children
            nodes.append(node)
        return nodes

    tree = build_level(sub, 0)
    metric = f"{agg} of {y}" if (has_num and y and agg in {"sum", "mean"}) else "row count"
    title = f"Hierarchy: {' → '.join(valid_dims)}"
    subtitle = (
        f"{sub.height:,} rows · sized by {metric} · "
        "click any sector to drill in, center to drill up"
    )
    return (
        title,
        subtitle,
        {"tree": tree, "dimensions": valid_dims, "metric_label": metric},
        {"levels": len(valid_dims)},
    )


def _choose_time_grain(
    dates: pl.Series, requested: TimeGrain
) -> Literal["year", "quarter", "month", "week", "day"]:
    if requested != "auto":
        return requested
    non_null = dates.drop_nulls()
    if non_null.len() < 2:
        return "month"
    d_min = non_null.min()
    d_max = non_null.max()
    if isinstance(d_min, (dt.date, dt.datetime)) and isinstance(d_max, (dt.date, dt.datetime)):
        d0 = d_min.date() if isinstance(d_min, dt.datetime) else d_min
        d1 = d_max.date() if isinstance(d_max, dt.datetime) else d_max
        span_days = (d1 - d0).days
        if span_days > 365 * 4:
            return "year"
        if span_days > 540:
            return "quarter"
        if span_days > 120:
            return "month"
        if span_days > 28:
            return "week"
    return "day"


def _period_end(
    start: dt.date, grain: Literal["year", "quarter", "month", "week", "day"]
) -> dt.date:
    if grain == "year":
        return dt.date(start.year + 1, 1, 1)
    if grain == "quarter":
        m = start.month + 3
        y = start.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        return dt.date(y, m, 1)
    if grain == "month":
        if start.month == 12:
            return dt.date(start.year + 1, 1, 1)
        return dt.date(start.year, start.month + 1, 1)
    if grain == "week":
        return start + dt.timedelta(days=7)
    return start + dt.timedelta(days=1)


def _build_time(
    sub: pl.DataFrame,
    x: str,
    y: str | None,
    y_info: ColumnInfo | None,
    group: str | None,
    agg: AggKind,
    requested_grain: TimeGrain,
) -> tuple[str, str | None, str | None, str, str, dict[str, Any], dict[str, Any]]:
    d_series = sub.select(_date_expr(sub, x).alias("__d__"))["__d__"]
    grain = _choose_time_grain(d_series, requested_grain)
    idx = _GRAIN_ORDER.index(grain)
    prev_grain = _GRAIN_ORDER[idx - 1] if idx > 0 else None
    next_grain = _GRAIN_ORDER[idx + 1] if idx + 1 < len(_GRAIN_ORDER) else None

    trunc_map = {"year": "1y", "quarter": "1q", "month": "1mo", "week": "1w", "day": "1d"}
    work = sub.with_columns(
        _date_expr(sub, x).dt.truncate(trunc_map[grain]).alias("__t__")
    ).drop_nulls("__t__")
    has_num = bool(y and y in work.columns and y_info and y_info.role == "numeric")
    eff_agg = agg if has_num else "count"

    points: list[dict[str, Any]] = []
    for row_df in work.partition_by("__t__", maintain_order=False):
        t_val = row_df["__t__"][0]
        if not isinstance(t_val, dt.date):
            continue
        p_end = _period_end(t_val, grain)
        n_rows = row_df.height
        if has_num and y:
            arr = row_df[y].drop_nulls().cast(pl.Float64).to_numpy()
            st = _numeric_series_stats(arr)
            val = st.get(eff_agg if eff_agg in {"mean", "median", "sum"} else "mean")
            points.append(
                {
                    "period": t_val.isoformat(),
                    "period_end": p_end.isoformat(),
                    "n": n_rows,
                    "value": val,
                    "ci_low": st["ci_low"],
                    "ci_high": st["ci_high"],
                    "q1": st["q1"],
                    "q3": st["q3"],
                }
            )
        else:
            points.append(
                {
                    "period": t_val.isoformat(),
                    "period_end": p_end.isoformat(),
                    "n": n_rows,
                    "value": float(n_rows),
                    "ci_low": None,
                    "ci_high": None,
                }
            )
    points.sort(key=lambda item: str(item["period"]))

    series_data: list[dict[str, Any]] = []
    if group and group in work.columns and group != x:
        g_col = work[group].cast(pl.String).fill_null(_NULL_LABEL)
        work_g = work.with_columns(g_col.alias("__g__"))
        top_g = (
            work_g.group_by("__g__").len().sort("len", descending=True).head(6)["__g__"].to_list()
        )
        for g_name in top_g:
            g_df = work_g.filter(pl.col("__g__") == g_name)
            by_t: dict[str, float | None] = {}
            for part in g_df.partition_by("__t__", maintain_order=False):
                tv = part["__t__"][0]
                if not isinstance(tv, dt.date):
                    continue
                if has_num and y:
                    arr = part[y].drop_nulls().cast(pl.Float64).to_numpy()
                    st = _numeric_series_stats(arr)
                    key_agg = eff_agg if eff_agg in {"mean", "median", "sum"} else "mean"
                    by_t[tv.isoformat()] = st.get(key_agg)
                else:
                    by_t[tv.isoformat()] = float(part.height)
            series_data.append(
                {
                    "name": str(g_name),
                    "values": [by_t.get(str(p["period"])) for p in points],
                }
            )

    metric = f"{eff_agg} {y}" if (has_num and y) else "rows"
    title = f"{metric.capitalize()} over {x} ({grain})"
    drill_hint = f" · click a {grain} to drill down to {next_grain}" if next_grain else ""
    subtitle = f"{len(points)} {grain}s ({work.height:,} rows){drill_hint}"
    return (
        grain,
        next_grain,
        prev_grain,
        title,
        subtitle,
        {
            "points": points,
            "series": series_data,
            "metric_label": metric,
            "grain": grain,
        },
        {"periods": len(points), "grain": grain},
    )


def _build_histogram(
    sub: pl.DataFrame,
    x: str,
    group: str | None,
    n_bins: int,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    arr = sub[x].drop_nulls().cast(pl.Float64).to_numpy()
    clean = arr[np.isfinite(arr)]
    stats = _numeric_series_stats(clean)
    if clean.size == 0:
        return (f"Distribution of {x}", "No finite values", {"bins": [], "series": []}, stats)

    lo, hi = float(clean.min()), float(clean.max())
    edges = np.linspace(lo, hi, n_bins + 1) if hi > lo else np.array([lo - 0.5, lo + 0.5])
    counts, _ = np.histogram(clean, bins=edges)
    total = max(int(clean.size), 1)
    bins_out = [
        {
            "x0": _finite(float(edges[i])),
            "x1": _finite(float(edges[i + 1])),
            "label": f"{edges[i]:.3g} – {edges[i + 1]:.3g}",
            "count": int(counts[i]),
            "share": float(counts[i] / total),
        }
        for i in range(counts.size)
    ]

    grouped_series: list[dict[str, Any]] = []
    if group and group in sub.columns and group != x:
        w = sub.select(
            pl.col(x).cast(pl.Float64).alias("__v__"),
            pl.col(group).cast(pl.String).fill_null(_NULL_LABEL).alias("__g__"),
        ).drop_nulls("__v__")
        top_g = w.group_by("__g__").len().sort("len", descending=True).head(5)["__g__"].to_list()
        for g_val in top_g:
            g_arr = w.filter(pl.col("__g__") == g_val)["__v__"].to_numpy()
            g_clean = g_arr[np.isfinite(g_arr)]
            g_counts, _ = np.histogram(np.clip(g_clean, edges[0], edges[-1]), bins=edges)
            grouped_series.append(
                {
                    "name": str(g_val),
                    "counts": [int(c) for c in g_counts],
                    "shares": [float(c / max(int(g_clean.size), 1)) for c in g_counts],
                }
            )

    title = f"Distribution of {x}" + (f" by {group}" if grouped_series else "")
    med = stats["median"]
    q1, q3 = stats["q1"], stats["q3"]
    subtitle = (
        f"{clean.size:,} values · median {med:.4g} · "
        f"IQR [{q1:.4g}, {q3:.4g}] · click a bin to zoom in"
    )
    return (
        title,
        subtitle,
        {"bins": bins_out, "series": grouped_series, "stats": stats},
        stats,
    )


def _build_scatter(
    sub: pl.DataFrame,
    x: str,
    y: str,
    group: str | None,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    cols_sel = [
        pl.col(x).cast(pl.Float64).alias("__x__"),
        pl.col(y).cast(pl.Float64).alias("__y__"),
    ]
    if "__row__" in sub.columns:
        cols_sel.append(pl.col("__row__").alias("__r__"))
    else:
        cols_sel.append(pl.int_range(1, sub.height + 1).alias("__r__"))
    if group and group in sub.columns and group not in {x, y}:
        cols_sel.append(pl.col(group).cast(pl.String).fill_null(_NULL_LABEL).alias("__g__"))

    valid = sub.select(cols_sel).drop_nulls(["__x__", "__y__"])
    valid = valid.filter(pl.col("__x__").is_finite() & pl.col("__y__").is_finite())
    n = valid.height
    if n == 0:
        empty_data: dict[str, Any] = {"points": [], "curve": []}
        return (f"{y} vs {x}", "No paired finite observations", empty_data, {"n": 0})

    xs = valid["__x__"].to_numpy()
    ys = valid["__y__"].to_numpy()

    r_val: float | None = None
    if n >= 3 and float(xs.std()) > 0 and float(ys.std()) > 0:
        r_val = _finite(float(np.corrcoef(xs, ys)[0, 1]))

    curve: list[dict[str, Any]] = []
    if n >= 8 and float(xs.max() - xs.min()) > 0:
        lo, hi = np.quantile(xs, [0.01, 0.99])
        if hi > lo:
            grid = np.linspace(float(lo), float(hi), 50)
            fit = spline_fit(xs, ys, grid)
            curve = [
                {
                    "x": _finite(float(gx)),
                    "fit": _finite(float(fc)),
                    "low": _finite(float(fl)),
                    "high": _finite(float(fh)),
                }
                for gx, fc, fl, fh in zip(grid, fit["curve"], fit["low"], fit["high"], strict=True)
            ]

    sampled = valid.sample(n=_MAX_SCATTER, seed=20261119) if n > _MAX_SCATTER else valid
    has_g = "__g__" in sampled.columns
    points = [
        {
            "x": float(row[0]),
            "y": float(row[1]),
            "row": int(row[2]),
            "group": str(row[3]) if has_g else None,
        }
        for row in sampled.iter_rows()
    ]

    corr_txt = f" · Pearson r = {r_val:+.3f}" if r_val is not None else ""
    sample_txt = f"showing {_MAX_SCATTER:,} of {n:,} rows" if n > _MAX_SCATTER else f"{n:,} rows"
    title = f"{y} vs {x}" + (f" (colored by {group})" if has_g else "")
    subtitle = f"{sample_txt}{corr_txt} · drag brush to inspect & drill into a cluster"
    return (
        title,
        subtitle,
        {
            "points": points,
            "curve": curve,
            "x_label": x,
            "y_label": y,
            "group_label": group if has_g else None,
        },
        {"n": n, "pearson_r": r_val, "sampled": n > _MAX_SCATTER},
    )


def _build_heatmap(
    sub: pl.DataFrame,
    x: str,
    y: str,
    z: str | None,
    z_info: ColumnInfo | None,
    agg: AggKind,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    has_z = bool(z and z in sub.columns and z_info and z_info.role == "numeric")
    w = sub.with_columns(
        pl.col(x).cast(pl.String).fill_null(_NULL_LABEL).alias("__x__"),
        pl.col(y).cast(pl.String).fill_null(_NULL_LABEL).alias("__y__"),
    )
    top_x = w.group_by("__x__").len().sort("len", descending=True).head(14)["__x__"].to_list()
    top_y = w.group_by("__y__").len().sort("len", descending=True).head(14)["__y__"].to_list()
    w = w.filter(pl.col("__x__").is_in(top_x) & pl.col("__y__").is_in(top_y))

    cells: list[dict[str, Any]] = []
    row_totals: dict[str, int] = {}
    for y_val in top_y:
        row_totals[str(y_val)] = w.filter(pl.col("__y__") == y_val).height

    for xi, x_val in enumerate(top_x):
        for yi, y_val in enumerate(top_y):
            cell_df = w.filter((pl.col("__x__") == x_val) & (pl.col("__y__") == y_val))
            n_cell = cell_df.height
            r_tot = max(row_totals.get(str(y_val), 1), 1)
            if has_z and z:
                arr = cell_df[z].drop_nulls().cast(pl.Float64).to_numpy()
                clean = arr[np.isfinite(arr)]
                val = float(clean.sum() if agg == "sum" else clean.mean()) if clean.size else None
            else:
                val = (n_cell / r_tot) if agg == "share" else float(n_cell)
            cells.append(
                {
                    "xi": xi,
                    "yi": yi,
                    "x": str(x_val),
                    "y": str(y_val),
                    "n": n_cell,
                    "row_share": n_cell / r_tot,
                    "value": _finite(val),
                }
            )

    metric = f"{agg} of {z}" if (has_z and z) else ("row share" if agg == "share" else "rows")
    title = f"{y} × {x}" + (f" ({metric})" if has_z else "")
    subtitle = f"{w.height:,} rows · click any cell to drill into that intersection"
    return (
        title,
        subtitle,
        {
            "x_categories": [str(v) for v in top_x],
            "y_categories": [str(v) for v in top_y],
            "cells": cells,
            "metric_label": metric,
            "is_percent": not has_z and agg == "share",
        },
        {"x_count": len(top_x), "y_count": len(top_y)},
    )


def explore_dataset(
    frame: pl.DataFrame,
    columns: list[ColumnInfo],
    query: ExploreQuery,
) -> ExploreResponse:
    col_map = {c.name: c for c in columns}
    usable = [c for c in columns if not c.pii and c.name in frame.columns]

    sub = _apply_filters(frame, query.filters)
    total_rows = frame.height
    matched_rows = sub.height

    # Pick smart defaults when x is omitted
    x = query.x if (query.x and query.x in sub.columns) else None
    if x is None and usable:
        cat_first = next((c.name for c in usable if c.role in {"categorical", "boolean"}), None)
        num_first = next((c.name for c in usable if c.role == "numeric"), None)
        x = cat_first or num_first or usable[0].name

    y = query.y if (query.y and query.y in sub.columns) else None
    group = query.group if (query.group and query.group in sub.columns) else None

    x_info = col_map.get(x) if x else None
    y_info = col_map.get(y) if y else None
    mode = _resolve_mode(query.mode, x_info, y_info, query.dimensions)

    used_cols = {flt.column for flt in query.filters}
    if x:
        used_cols.add(x)
    next_dims = _suggest_dimensions(sub if sub.height else frame, columns, used_cols)

    grain_used: str | None = None
    next_grain: str | None = None
    prev_grain: str | None = None

    if mode == "hierarchy":
        dims = [d for d in query.dimensions if d in sub.columns]
        if not dims and x:
            dims = [x, *([group] if group else next_dims[:2])]
        title, subtitle, data, summary = _build_hierarchy(sub, dims, y, y_info, query.agg)
    elif mode == "time" and x:
        grain_used, next_grain, prev_grain, title, subtitle, data, summary = _build_time(
            sub, x, y, y_info, group, query.agg, query.time_grain
        )
    elif mode == "histogram" and x:
        title, subtitle, data, summary = _build_histogram(sub, x, group, query.bins)
    elif mode == "scatter" and x and y:
        title, subtitle, data, summary = _build_scatter(sub, x, y, group)
    elif mode == "heatmap" and x and y:
        g_info = col_map.get(group) if group else None
        z_col = group if (group and g_info and g_info.role == "numeric") else None
        title, subtitle, data, summary = _build_heatmap(
            sub, x, y, z_col, col_map.get(z_col) if z_col else None, query.agg
        )
    elif x:
        title, subtitle, data, summary = _build_group(sub, x, y, y_info, group, query.agg)
    else:
        title, subtitle, data, summary = ("Dataset Empty", "No analyzable columns found", {}, {})

    # Safe sample of drilled records (masking PII columns)
    safe_cols = [c.name for c in columns if not c.pii and c.name in sub.columns][:12]
    if "__row__" in sub.columns:
        safe_cols = ["__row__", *safe_cols]
    sample_df = sub.select(safe_cols).head(25) if safe_cols else pl.DataFrame()

    return ExploreResponse(
        mode=mode,
        x=x,
        y=y,
        group=group,
        agg=query.agg,
        total_rows=total_rows,
        matched_rows=matched_rows,
        title=title,
        subtitle=subtitle,
        grain_used=grain_used,
        next_grain=next_grain,
        prev_grain=prev_grain,
        next_dimensions=next_dims,
        data=data,
        summary=summary,
        sample_columns=sample_df.columns,
        sample_rows=[list(r) for r in sample_df.iter_rows()],
    )
