"""Vega-Lite chart specifications built from engine results (PROJECT_PROMPT.md section 8).

Charts only display values the engine computed: facts stored on the finding, or the analyzed
rows themselves. Large tables are sampled or binned for display and the subtitle says so; the
statistics in the explanation are always computed on the full data.
"""

from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
import polars as pl

from edaforge.discovery.stats import FloatArray, spline_fit
from edaforge.models import ChartSpec, Finding

__all__ = [
    "category_association",
    "change_point",
    "conditional",
    "cross_file",
    "group_difference",
    "interaction",
    "numeric_pair",
    "subgroup",
]

BRAND = "#4338ca"
SOFT = "#a5b4fc"
GOLD = "#d97706"
GRAY = "#9ca3af"
_MAX_POINTS = 1500


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in cast("dict[Any, Any]", value).items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in cast("list[Any] | tuple[Any, ...]", value)]
    if isinstance(value, np.floating):
        return _clean(float(cast("np.floating[Any]", value)))
    if isinstance(value, np.integer):
        return int(cast("np.integer[Any]", value))
    return value


def _spec(title: str, subtitle: str, body: dict[str, Any], height: int = 260) -> dict[str, Any]:
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "title": {
            "text": title,
            "subtitle": subtitle,
            "anchor": "start",
            "fontSize": 13,
            "subtitleFontSize": 11,
            "subtitleColor": "#5f6b7a",
        },
        "width": "container",
        "height": height,
        "config": {
            "font": "Inter, system-ui, sans-serif",
            "axis": {
                "labelColor": "#39414d",
                "titleColor": "#39414d",
                "gridColor": "#eef1f5",
                "labelFontSize": 11,
                "titleFontSize": 11,
            },
            "legend": {"labelFontSize": 11, "titleFontSize": 11},
            "view": {"stroke": None},
        },
        **body,
    }
    return _clean(spec)


def _chart(title: str, alt: str, spec: dict[str, Any]) -> ChartSpec:
    return ChartSpec(kind="vega-lite", title=title, alt_text=alt, spec=spec)


def _sample(frame: pl.DataFrame, n: int = _MAX_POINTS) -> tuple[pl.DataFrame, bool]:
    if frame.height <= n:
        return frame, False
    return frame.sample(n=n, seed=20261110), True


def _js_round(x: float) -> int:
    """JavaScript's ``Math.round``: halves go up, not to the even neighbour as in Python."""
    low = math.floor(x)
    return low + 1 if x - low >= 0.5 else low


def _vega_bins(lo: float, hi: float, maxbins: int) -> tuple[float, float, float]:
    """``(start, stop, step)`` of Vega's default ``bin`` (steps of 1, 2 or 5 × 10^k) for [lo, hi].

    The arithmetic of vega-statistics ``bin`` and of the Bin transform, so cells counted here
    are the ones Vega-Lite draws when it bins the rows itself.
    """
    logb = math.log(10)
    span = (hi - lo) or abs(lo) or 1.0
    level = math.ceil(math.log(maxbins) / logb)
    step = 10.0 ** (_js_round(math.log(span) / logb) - level)
    while math.ceil(span / step) > maxbins:
        step *= 10
    for divide in (5, 2):
        v = step / divide
        if span / v <= maxbins:
            step = v
    v = math.log(step)
    precision = 0 if v >= 0 else int(-v / logb) + 1
    v = math.floor(lo / step + 10.0 ** (-precision - 1)) * step
    start = v - step if lo < v else v
    stop = math.ceil(hi / step) * step
    if stop == start:
        stop = start + step
    return start, start + math.ceil((stop - start) / step) * step, step


_Bins = tuple[float, float, float]  # start, stop, step


def _binned_counts(
    xs: FloatArray, ys: FloatArray, maxbins: tuple[int, int]
) -> tuple[list[dict[str, Any]], list[_Bins]]:
    """Rows per non-empty cell of a Vega-binned 2-D grid, and the bins of each axis.

    Counting here sends one value per cell to the browser instead of every row.
    """
    keep = np.isfinite(xs) & np.isfinite(ys)
    bins: list[_Bins] = []
    index: list[np.ndarray[Any, np.dtype[np.int64]]] = []
    for column, most in ((xs, maxbins[0]), (ys, maxbins[1])):
        finite = column[np.isfinite(column)]
        start, stop, step = _vega_bins(float(finite.min()), float(finite.max()), most)
        # Vega clamps the value to stop - step; clamping the bin number instead keeps the largest
        # values in the last bin when rounding leaves (stop - step - start) / step just below a
        # whole number.
        k = np.floor(1e-14 + (column[keep] - start) / step)
        index.append(np.clip(k, 0, round((stop - start) / step) - 1).astype(np.int64))
        bins.append((start, stop, step))
    n_y = int(index[1].max()) + 1 if index[1].size else 1
    counts = np.bincount(index[0] * n_y + index[1])

    def edges(k: int, axis: _Bins) -> tuple[float, float]:
        start, _, step = axis
        low = start + step * k
        return low, start + step * (1 + (low - start) / step)  # as the Bin transform computes it

    values: list[dict[str, Any]] = []
    for cell in np.flatnonzero(counts):
        kx, ky = divmod(int(cell), n_y)
        (x0, x1), (y0, y1) = edges(kx, bins[0]), edges(ky, bins[1])
        values.append({"x": x0, "x_end": x1, "y": y0, "y_end": y1, "rows": int(counts[cell])})
    return values, bins


def _binned_channel(field: str, title: str, bins: _Bins, extent: str) -> dict[str, Any]:
    """A pre-binned field with the scale bins and tick count Vega-Lite gives a field it bins."""
    start, stop, step = bins
    return {
        "field": field,
        "bin": {"binned": True, "step": step},
        "type": "quantitative",
        "title": title,
        "scale": {"bins": {"start": start, "stop": stop, "step": step}},
        "axis": {"tickCount": {"expr": f"ceil({extent}/10)"}},
    }


# ---------------------------------------------------------------- relationships


def numeric_pair(finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
    f: dict[str, Any] = finding.facts  # engine-computed JSON
    x, y = str(f["x"]), str(f["y"])
    rows = frame.select(x, y).drop_nulls()
    if rows.height < 3:
        return []
    xs = rows[x].cast(pl.Float64).to_numpy()
    ys = rows[y].cast(pl.Float64).to_numpy()
    lo, hi = np.quantile(xs, [0.01, 0.99])
    grid = np.linspace(float(lo), float(hi), 60)
    fit = spline_fit(xs, ys, grid)
    curve = [
        {"x": float(g), "fit": float(c), "low": float(a), "high": float(b)}
        for g, c, a, b in zip(grid, fit["curve"], fit["low"], fit["high"], strict=True)
    ]
    layers: list[dict[str, Any]] = []
    if rows.height > 6000:
        cells, (x_bins, y_bins) = _binned_counts(xs, ys, (40, 30))
        layers.append(
            {
                "data": {"values": cells},
                "mark": {"type": "rect", "opacity": 0.85},
                "encoding": {
                    "x": _binned_channel("x", x, x_bins, "width"),
                    "x2": {"field": "x_end"},
                    "y": _binned_channel("y", y, y_bins, "height"),
                    "y2": {"field": "y_end"},
                    "color": {
                        "field": "rows",
                        "type": "quantitative",
                        "scale": {"scheme": "purples"},
                        "title": "rows",
                    },
                },
            }
        )
        note = f"{rows.height:,} rows binned"
    else:
        shown, sampled = _sample(rows)
        layers.append(
            {
                "data": {"values": [{"x": float(a), "y": float(b)} for a, b in shown.rows()]},
                "mark": {"type": "circle", "size": 14, "opacity": 0.35, "color": GRAY},
                "encoding": {
                    "x": {
                        "field": "x",
                        "type": "quantitative",
                        "title": x,
                        "scale": {"zero": False},
                    },
                    "y": {
                        "field": "y",
                        "type": "quantitative",
                        "title": y,
                        "scale": {"zero": False},
                    },
                    "tooltip": [
                        {"field": "x", "title": x, "format": ",.4~g"},
                        {"field": "y", "title": y, "format": ",.4~g"},
                    ],
                },
            }
        )
        note = (
            f"random sample of {_MAX_POINTS:,} of {rows.height:,} rows"
            if sampled
            else f"all {rows.height:,} rows"
        )
    layers.append(
        {
            "data": {"values": curve},
            "mark": {"type": "area", "opacity": 0.18, "color": BRAND},
            "encoding": {
                "x": {"field": "x", "type": "quantitative"},
                "y": {"field": "low", "type": "quantitative"},
                "y2": {"field": "high"},
            },
        }
    )
    layers.append(
        {
            "data": {"values": curve},
            "mark": {"type": "line", "color": BRAND, "strokeWidth": 2.5},
            "encoding": {
                "x": {"field": "x", "type": "quantitative"},
                "y": {"field": "fit", "type": "quantitative"},
                "tooltip": [
                    {"field": "x", "title": x, "format": ",.4~g"},
                    {"field": "fit", "title": f"typical {y}", "format": ",.4~g"},
                ],
            },
        }
    )
    spec = _spec(
        f"{y} by {x}",
        f"{note}; line: spline fit with 95% band for the average",
        {"layer": layers, "resolve": {"scale": {"color": "independent"}}},
    )
    return [
        _chart(
            f"{y} by {x}",
            f"Scatter of {y} against {x} with a fitted curve ({f.get('shape', '')}).",
            spec,
        )
    ]


def group_difference(finding: Finding) -> list[ChartSpec]:
    f: dict[str, Any] = finding.facts  # engine-computed JSON
    groups = list(f["groups"])
    y, g = str(f["y"]), str(f["group"])
    values = [
        {
            "group": str(r["level"]),
            "mean": r["mean"],
            "low": r["mean_low"],
            "high": r["mean_high"],
            "median": r["median"],
            "q1": r["q1"],
            "q3": r["q3"],
            "n": r["n"],
        }
        for r in groups
    ]
    order = [v["group"] for v in values]
    enc_y = {"field": "group", "type": "nominal", "sort": order, "title": g}
    spec = _spec(
        f"{y} by {g}",
        "dot: mean with 95% interval; bar: middle half of values (25th–75th percentile)",
        {
            "data": {"values": values},
            "layer": [
                {
                    "mark": {"type": "bar", "height": 10, "color": "#e0e7ff"},
                    "encoding": {
                        "y": enc_y,
                        "x": {
                            "field": "q1",
                            "type": "quantitative",
                            "title": y,
                            "scale": {"zero": False},
                        },
                        "x2": {"field": "q3"},
                    },
                },
                {
                    "mark": {"type": "rule", "color": BRAND, "strokeWidth": 2},
                    "encoding": {
                        "y": enc_y,
                        "x": {"field": "low", "type": "quantitative"},
                        "x2": {"field": "high"},
                    },
                },
                {
                    "mark": {"type": "point", "filled": True, "color": BRAND, "size": 70},
                    "encoding": {
                        "y": enc_y,
                        "x": {"field": "mean", "type": "quantitative"},
                        "tooltip": [
                            {"field": "group", "title": g},
                            {"field": "n", "title": "rows", "format": ","},
                            {"field": "mean", "format": ",.4~g"},
                            {"field": "low", "title": "95% low", "format": ",.4~g"},
                            {"field": "high", "title": "95% high", "format": ",.4~g"},
                            {"field": "median", "format": ",.4~g"},
                        ],
                    },
                },
                {
                    "mark": {
                        "type": "text",
                        "align": "left",
                        "dx": 8,
                        "fontSize": 10,
                        "color": "#5f6b7a",
                    },
                    "encoding": {
                        "y": enc_y,
                        "x": {"field": "high", "type": "quantitative"},
                        "text": {"field": "n", "format": ",", "type": "quantitative"},
                    },
                },
            ],
        },
        height=max(140, 26 * len(values)),
    )
    return [_chart(f"{y} by {g}", f"Average {y} per {g} group with 95% intervals.", spec)]


def category_association(finding: Finding) -> list[ChartSpec]:
    f: dict[str, Any] = finding.facts  # engine-computed JSON
    a, b = str(f["a"]), str(f["b"])
    if f.get("rates"):
        rates = list(f["rates"])
        target = b if f.get("positive") is not None and b == finding.variables[-1].column else a
        other = a if target == b else b
        values = [
            {
                "level": r["level"],
                "rate": r["rate"],
                "low": r["low"],
                "high": r["high"],
                "n": r["n"],
            }
            for r in rates
        ]
        order = [v["level"] for v in values]
        spec = _spec(
            f"Share {target} = {f.get('positive')} by {other}",
            "bar: share of rows; line: 95% Wilson interval",
            {
                "data": {"values": values},
                "layer": [
                    {
                        "mark": {"type": "bar", "color": SOFT},
                        "encoding": {
                            "y": {
                                "field": "level",
                                "type": "nominal",
                                "sort": order,
                                "title": other,
                            },
                            "x": {
                                "field": "rate",
                                "type": "quantitative",
                                "axis": {"format": "%"},
                                "title": f"share {target} = {f.get('positive')}",
                            },
                            "tooltip": [
                                {"field": "level"},
                                {"field": "n", "format": ","},
                                {"field": "rate", "format": ".1%"},
                            ],
                        },
                    },
                    {
                        "mark": {"type": "rule", "color": BRAND, "strokeWidth": 2},
                        "encoding": {
                            "y": {"field": "level", "type": "nominal", "sort": order},
                            "x": {"field": "low", "type": "quantitative"},
                            "x2": {"field": "high"},
                        },
                    },
                ],
            },
            height=max(140, 26 * len(values)),
        )
        return [
            _chart(spec["title"]["text"], f"Share of {target} by {other} with intervals.", spec)
        ]
    table = dict(f["table"])
    values: list[dict[str, Any]] = []
    for i, ra in enumerate(table["rows"]):
        total = sum(table["counts"][i]) or 1
        for j, cb in enumerate(table["cols"]):
            values.append(
                {
                    "a": str(ra),
                    "b": str(cb),
                    "share": table["counts"][i][j] / total,
                    "n": table["counts"][i][j],
                }
            )
    spec = _spec(
        f"{b} within each {a}",
        "colour: share of each row's records",
        {
            "data": {"values": values},
            "mark": {"type": "rect"},
            "encoding": {
                "y": {"field": "a", "type": "nominal", "title": a},
                "x": {"field": "b", "type": "nominal", "title": b},
                "color": {
                    "field": "share",
                    "type": "quantitative",
                    "scale": {"scheme": "purples"},
                    "legend": {"format": "%"},
                },
                "tooltip": [
                    {"field": "a", "title": a},
                    {"field": "b", "title": b},
                    {"field": "n", "format": ","},
                    {"field": "share", "format": ".1%"},
                ],
            },
        },
        height=max(140, 24 * len(table["rows"])),
    )
    return [_chart(f"{b} within each {a}", f"Heat map of {b} shares within each {a}.", spec)]


# ---------------------------------------------------------------- segments


def _fmt_value(binary: bool) -> str:
    return ".1%" if binary else ",.4~g"


def subgroup(finding: Finding) -> list[ChartSpec]:
    f: dict[str, Any] = finding.facts  # engine-computed JSON
    binary = bool(f.get("binary"))
    target = str(f["target"])
    values = [
        {"group": "In the segment", "value": f.get("value_in"), "n": f.get("n_in")},
        {"group": "Everyone else", "value": f.get("value_out"), "n": f.get("n_out")},
    ]
    values.extend(
        {"group": f"Only: {p['text']}", "value": p["value_in"], "n": p["n_in"]}
        for p in f.get("parents") or ()
    )
    ylabel = f"share {target} = {f.get('positive')}" if binary else f"average {target}"
    spec = _spec(
        f"{target}: segment vs the rest",
        f"segment: {f.get('text')}; dashed line: all rows",
        {
            "layer": [
                {
                    "data": {"values": values},
                    "mark": {"type": "bar", "cornerRadiusEnd": 3},
                    "encoding": {
                        "y": {"field": "group", "type": "nominal", "sort": None, "title": None},
                        "x": {
                            "field": "value",
                            "type": "quantitative",
                            "title": ylabel,
                            "axis": {"format": ".0%"} if binary else {},
                        },
                        "color": {
                            "field": "group",
                            "type": "nominal",
                            "legend": None,
                            "scale": {"range": [BRAND, GRAY, SOFT, SOFT]},
                        },
                        "tooltip": [
                            {"field": "group"},
                            {"field": "n", "title": "rows", "format": ","},
                            {"field": "value", "format": _fmt_value(binary)},
                        ],
                    },
                },
                {
                    "data": {"values": [{"overall": f.get("overall")}]},
                    "mark": {"type": "rule", "strokeDash": [4, 3], "color": "#111827"},
                    "encoding": {"x": {"field": "overall", "type": "quantitative"}},
                },
            ]
        },
        height=max(110, 34 * len(values)),
    )
    return [
        _chart(
            f"{target}: segment vs the rest",
            f"Bar chart comparing {target} inside and outside the segment.",
            spec,
        )
    ]


def interaction(finding: Finding) -> list[ChartSpec]:
    f: dict[str, Any] = finding.facts  # engine-computed JSON
    cells = dict(f.get("cells", {}))
    if not cells:
        return []
    conds = list(f["conditions"])
    first, second = conds[0]["text"], conds[1]["text"]
    binary = bool(f.get("binary"))
    rows = [
        {
            "first": "no",
            "second": "no",
            "value": cells["neither"]["value"],
            "n": cells["neither"]["n"],
        },
        {
            "first": "yes",
            "second": "no",
            "value": cells["first_only"]["value"],
            "n": cells["first_only"]["n"],
        },
        {
            "first": "no",
            "second": "yes",
            "value": cells["second_only"]["value"],
            "n": cells["second_only"]["n"],
        },
        {"first": "yes", "second": "yes", "value": cells["both"]["value"], "n": cells["both"]["n"]},
    ]
    target = str(f["target"])
    spec = _spec(
        f"{target} for each combination",
        "lines that are not parallel mean the two conditions matter together",
        {
            "data": {"values": rows},
            "layer": [
                {
                    "mark": {
                        "type": "line",
                        "point": {"size": 60, "filled": True},
                        "strokeWidth": 2.5,
                    },
                    "encoding": {
                        "x": {
                            "field": "first",
                            "type": "ordinal",
                            "sort": ["no", "yes"],
                            "title": first,
                        },
                        "y": {
                            "field": "value",
                            "type": "quantitative",
                            "title": (
                                f"share {target} = {f.get('positive')}"
                                if binary
                                else f"average {target}"
                            ),
                            "axis": {"format": ".0%"} if binary else {},
                            "scale": {"zero": False},
                        },
                        "color": {
                            "field": "second",
                            "type": "nominal",
                            "title": second,
                            "scale": {"domain": ["no", "yes"], "range": [GRAY, BRAND]},
                        },
                        "tooltip": [
                            {"field": "first", "title": first},
                            {"field": "second", "title": second},
                            {"field": "n", "format": ","},
                            {"field": "value", "format": _fmt_value(binary)},
                        ],
                    },
                },
            ],
        },
    )
    return [
        _chart(f"{target} for each combination", "Interaction plot of the two conditions.", spec)
    ]


def conditional(finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
    f: dict[str, Any] = finding.facts  # engine-computed JSON
    x, y, z = str(f["x"]), str(f["y"]), str(f["z"])
    rows = [
        {
            "what": "All rows (before)",
            "rho": f["rho_marginal"],
            "low": f["rho_marginal_low"],
            "high": f["rho_marginal_high"],
            "kind": "before",
        },
        {
            "what": f"After accounting for {z}",
            "rho": f["rho_partial"],
            "low": f["rho_partial_low"],
            "high": f["rho_partial_high"],
            "kind": "after",
        },
    ]
    rows.extend(
        {
            "what": f"Only {z} = {w['level']} (n = {w['n']:,})",
            "rho": w["rho"],
            "low": w["low"],
            "high": w["high"],
            "kind": "within",
        }
        for w in f.get("within") or ()
    )
    order = [r["what"] for r in rows]
    spec = _spec(
        f"Association of {x} and {y}, before and after {z}",
        "Spearman correlation with 95% interval; 0 means no monotone association",
        {
            "data": {"values": rows},
            "layer": [
                {
                    "mark": {"type": "rule", "color": "#111827", "strokeDash": [3, 3]},
                    "encoding": {"x": {"datum": 0}},
                },
                {
                    "mark": {"type": "rule", "strokeWidth": 2},
                    "encoding": {
                        "y": {"field": "what", "type": "nominal", "sort": order, "title": None},
                        "x": {
                            "field": "low",
                            "type": "quantitative",
                            "title": "correlation",
                            "scale": {"domain": [-1, 1]},
                        },
                        "x2": {"field": "high"},
                        "color": {
                            "field": "kind",
                            "type": "nominal",
                            "legend": None,
                            "scale": {
                                "domain": ["before", "after", "within"],
                                "range": [GRAY, BRAND, SOFT],
                            },
                        },
                    },
                },
                {
                    "mark": {"type": "point", "filled": True, "size": 70},
                    "encoding": {
                        "y": {"field": "what", "type": "nominal", "sort": order},
                        "x": {"field": "rho", "type": "quantitative"},
                        "color": {
                            "field": "kind",
                            "type": "nominal",
                            "legend": None,
                            "scale": {
                                "domain": ["before", "after", "within"],
                                "range": [GRAY, BRAND, SOFT],
                            },
                        },
                        "tooltip": [
                            {"field": "what"},
                            {"field": "rho", "format": ".3f"},
                            {"field": "low", "format": ".3f"},
                            {"field": "high", "format": ".3f"},
                        ],
                    },
                },
            ],
        },
        height=max(110, 28 * len(rows)),
    )
    charts = [
        _chart(
            spec["title"]["text"],
            "Correlations before and after accounting for the third variable.",
            spec,
        )
    ]
    if f.get("z_categorical") and f.get("mode") == "reversal":
        sub = frame.select(x, y, z).drop_nulls()
        shown, sampled = _sample(sub, 1200)
        scatter = _spec(
            f"{y} vs {x}, coloured by {z}",
            ("random sample of 1,200 rows; " if sampled else "")
            + "lines: straight-line fit per group (coloured) and over all rows (black)",
            {
                "data": {
                    "values": [
                        {"x": float(a), "y": float(b), "z": str(c)} for a, b, c in shown.rows()
                    ]
                },
                "layer": [
                    {
                        "mark": {"type": "circle", "size": 14, "opacity": 0.35},
                        "encoding": {
                            "x": {
                                "field": "x",
                                "type": "quantitative",
                                "title": x,
                                "scale": {"zero": False},
                            },
                            "y": {
                                "field": "y",
                                "type": "quantitative",
                                "title": y,
                                "scale": {"zero": False},
                            },
                            "color": {"field": "z", "type": "nominal", "title": z},
                        },
                    },
                    {
                        "transform": [{"regression": "y", "on": "x", "groupby": ["z"]}],
                        "mark": {"type": "line", "strokeWidth": 2},
                        "encoding": {
                            "x": {"field": "x", "type": "quantitative"},
                            "y": {"field": "y", "type": "quantitative"},
                            "color": {"field": "z", "type": "nominal"},
                        },
                    },
                    {
                        "transform": [{"regression": "y", "on": "x"}],
                        "mark": {
                            "type": "line",
                            "strokeWidth": 2.5,
                            "color": "#111827",
                            "strokeDash": [6, 3],
                        },
                        "encoding": {
                            "x": {"field": "x", "type": "quantitative"},
                            "y": {"field": "y", "type": "quantitative"},
                        },
                    },
                ],
            },
        )
        charts.append(
            _chart(
                scatter["title"]["text"],
                "Scatter coloured by group with per-group trend lines.",
                scatter,
            )
        )
    return charts


# ---------------------------------------------------------------- time and files


def change_point(finding: Finding) -> list[ChartSpec]:
    f: dict[str, Any] = finding.facts  # engine-computed JSON
    points = list(f.get("points", []))
    if not points:
        return []
    label = str(f.get("label"))
    brk = str(f.get("break"))
    segments = [
        {"start": f.get("first_period"), "end": brk, "mean": f.get("mean_before")},
        {"start": brk, "end": f.get("last_period"), "mean": f.get("mean_after")},
    ]
    spec = _spec(
        f"{label} per {f.get('grain')}",
        (
            f"{len(points)} periods; red line: estimated change on {brk}; grey lines: "
            f"average before and after"
        ),
        {
            "layer": [
                {
                    "data": {"values": points},
                    "mark": {"type": "line", "color": BRAND, "point": {"size": 18, "filled": True}},
                    "encoding": {
                        "x": {"field": "period", "type": "temporal", "title": None},
                        "y": {
                            "field": "value",
                            "type": "quantitative",
                            "title": label,
                            "scale": {"zero": False},
                        },
                        "tooltip": [
                            {"field": "period", "type": "temporal"},
                            {"field": "value", "format": ",.4~g"},
                            {"field": "n", "title": "rows", "format": ","},
                        ],
                    },
                },
                {
                    "data": {"values": segments},
                    "mark": {
                        "type": "rule",
                        "color": "#4b5563",
                        "strokeWidth": 2,
                        "strokeDash": [6, 3],
                    },
                    "encoding": {
                        "x": {"field": "start", "type": "temporal"},
                        "x2": {"field": "end"},
                        "y": {"field": "mean", "type": "quantitative"},
                    },
                },
                {
                    "data": {"values": [{"break": brk}]},
                    "mark": {"type": "rule", "color": "#dc2626", "strokeWidth": 2},
                    "encoding": {"x": {"field": "break", "type": "temporal"}},
                },
            ]
        },
    )
    return [
        _chart(
            f"{label} over time", f"Timeline of {label} with the estimated change on {brk}.", spec
        )
    ]


def cross_file(finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
    f: dict[str, Any] = finding.facts  # engine-computed JSON
    column, env = str(f["column"]), str(f["env"])
    a, b = str(f["a"]), str(f["b"])
    rows = frame.select(column, env).drop_nulls().filter(pl.col(env).cast(pl.String).is_in([a, b]))
    if f.get("numeric"):
        values = rows[column].cast(pl.Float64).to_numpy()
        labels = rows[env].cast(pl.String).to_numpy()
        log = bool(f.get("unit_hint")) and bool((values > 0).all())
        v = np.log10(values) if log else values
        lo, hi = np.quantile(v, [0.005, 0.995])
        edges = (
            np.linspace(float(lo), float(hi), 41)
            if hi > lo
            else np.array([float(lo) - 0.5, float(lo) + 0.5])
        )
        data: list[dict[str, Any]] = []
        for lab in (a, b):
            sel = v[labels == lab]
            counts, _ = np.histogram(np.clip(sel, edges[0], edges[-1]), bins=edges)
            total = max(int(sel.size), 1)
            for i in range(counts.size):
                x0, x1 = (10 ** edges[i], 10 ** edges[i + 1]) if log else (edges[i], edges[i + 1])
                data.append(
                    {
                        "source": lab,
                        "x0": float(x0),
                        "x1": float(x1),
                        "share": counts[i] / total,
                        "n": int(counts[i]),
                    }
                )
        spec = _spec(
            f"{column} in each {f.get('env_label', 'file')}",
            ("log scale; " if log else "") + "share of each source's rows per bin",
            {
                "data": {"values": data},
                "mark": {"type": "bar", "opacity": 0.55, "binSpacing": 0},
                "encoding": {
                    "x": {
                        "field": "x0",
                        "type": "quantitative",
                        "title": column,
                        "scale": {"type": "log"} if log else {"zero": False},
                    },
                    "x2": {"field": "x1"},
                    "y": {
                        "field": "share",
                        "type": "quantitative",
                        "stack": None,
                        "axis": {"format": "%"},
                        "title": "share of rows",
                    },
                    "color": {
                        "field": "source",
                        "type": "nominal",
                        "title": None,
                        "scale": {"range": [BRAND, GOLD]},
                    },
                    "tooltip": [
                        {"field": "source"},
                        {"field": "x0", "format": ",.4~g", "title": "from"},
                        {"field": "x1", "format": ",.4~g", "title": "to"},
                        {"field": "n", "format": ","},
                    ],
                },
            },
        )
        return [
            _chart(
                spec["title"]["text"], f"Overlaid distributions of {column} in {a} and {b}.", spec
            )
        ]
    shares = list(f.get("shares", []))
    data = [{"level": s["level"], "source": a, "share": s["share_a"]} for s in shares] + [
        {"level": s["level"], "source": b, "share": s["share_b"]} for s in shares
    ]
    spec = _spec(
        f"{column} in each {f.get('env_label', 'file')}",
        "share of each source's rows",
        {
            "data": {"values": data},
            "mark": {"type": "bar"},
            "encoding": {
                "y": {"field": "level", "type": "nominal", "title": column},
                "yOffset": {"field": "source"},
                "x": {
                    "field": "share",
                    "type": "quantitative",
                    "axis": {"format": "%"},
                    "title": "share of rows",
                },
                "color": {
                    "field": "source",
                    "type": "nominal",
                    "title": None,
                    "scale": {"range": [BRAND, GOLD]},
                },
                "tooltip": [
                    {"field": "level"},
                    {"field": "source"},
                    {"field": "share", "format": ".1%"},
                ],
            },
        },
        height=max(140, 30 * len(shares)),
    )
    return [_chart(spec["title"]["text"], f"Label shares of {column} by source.", spec)]


def histogram(
    values: np.ndarray[Any, np.dtype[np.float64]],
    title: str,
    x_title: str,
    highlight: tuple[float, float] | None = None,
) -> ChartSpec:
    lo, hi = float(values.min()), float(values.max())
    edges = np.linspace(lo, hi, 31) if hi > lo else np.array([lo - 0.5, hi + 0.5])
    counts, _ = np.histogram(values, bins=edges)
    data = [
        {
            "x0": float(edges[i]),
            "x1": float(edges[i + 1]),
            "n": int(counts[i]),
            "flag": bool(highlight and (edges[i + 1] <= highlight[0] or edges[i] >= highlight[1])),
        }
        for i in range(counts.size)
    ]
    spec = _spec(
        title,
        "bars outside the fences are highlighted" if highlight else "",
        {
            "data": {"values": data},
            "mark": {"type": "bar", "binSpacing": 0},
            "encoding": {
                "x": {"field": "x0", "type": "quantitative", "title": x_title},
                "x2": {"field": "x1"},
                "y": {"field": "n", "type": "quantitative", "title": "rows"},
                "color": {
                    "field": "flag",
                    "type": "nominal",
                    "legend": None,
                    "scale": {"domain": [False, True], "range": [SOFT, GOLD]},
                },
                "tooltip": [
                    {"field": "x0", "format": ",.4~g", "title": "from"},
                    {"field": "x1", "format": ",.4~g", "title": "to"},
                    {"field": "n", "format": ","},
                ],
            },
        },
        height=200,
    )
    return _chart(title, f"Histogram of {x_title}.", spec)


def bars(
    rows: list[dict[str, Any]], title: str, x_title: str, y_field: str, x_format: str = ","
) -> ChartSpec:
    spec = _spec(
        title,
        "",
        {
            "data": {"values": rows},
            "mark": {"type": "bar", "color": SOFT, "cornerRadiusEnd": 3},
            "encoding": {
                "y": {"field": y_field, "type": "nominal", "sort": "-x", "title": None},
                "x": {
                    "field": "value",
                    "type": "quantitative",
                    "title": x_title,
                    "axis": {"format": x_format},
                },
                "tooltip": [{"field": y_field}, {"field": "value", "format": x_format}],
            },
        },
        height=max(110, 24 * len(rows)),
    )
    return _chart(title, title, spec)


def anomaly_scatter(
    points: list[dict[str, Any]], x: str, y: str, n_total: int, sampled: bool
) -> ChartSpec:
    spec = _spec(
        f"Unusual records by {x} and {y}",
        ("random sample of ordinary rows; " if sampled else "")
        + f"orange: flagged records (of {n_total:,} rows)",
        {
            "data": {"values": points},
            "mark": {"type": "circle", "opacity": 0.6},
            "encoding": {
                "x": {"field": "x", "type": "quantitative", "title": x, "scale": {"zero": False}},
                "y": {"field": "y", "type": "quantitative", "title": y, "scale": {"zero": False}},
                "color": {
                    "field": "flag",
                    "type": "nominal",
                    "legend": None,
                    "scale": {"domain": [False, True], "range": ["#c7d2fe", GOLD]},
                },
                "size": {
                    "field": "flag",
                    "type": "nominal",
                    "legend": None,
                    "scale": {"domain": [False, True], "range": [14, 60]},
                },
                "tooltip": [
                    {"field": "row", "title": "row"},
                    {"field": "x", "title": x, "format": ",.4~g"},
                    {"field": "y", "title": y, "format": ",.4~g"},
                ],
            },
        },
    )
    return _chart(spec["title"]["text"], "Scatter with unusual records highlighted.", spec)
