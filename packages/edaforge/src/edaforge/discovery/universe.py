"""The Data Universe: a run's findings as a navigable graph of columns and relationships.

Nothing here computes a statistic. Nodes are the columns a run analyzed; edges are its stored
findings, carrying the finding's own evidence grade, confirmation status, ranking effect
component (0-1) and display text. The 3D view only draws what the engine already established:

* pair findings (curves, associations, group gaps, file differences, time) join two columns;
* ``explained_away`` joins x and y *through* the column that absorbs the link (``via``);
* ``reversal`` joins x and y with the column that flips the sign as ``via``;
* segment and interaction findings join each condition column to the outcome;
* descriptive facts (data quality, unusual records) become alerts on their columns;
* exact formulas mark the computed column as derived from its inputs.

Edges carry the finding's direction (+1 up together, -1 one up while the other goes down, 0 for
differences between groups) and its effect estimate. Nodes carry descriptive statistics of the
column (counts, quantiles, a 16-bin histogram or the top labels) and a one-paragraph story built
only from those numbers and the findings: nothing is inferred here.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl

from edaforge.link import SOURCE_COLUMN

__all__ = ["build_universe"]

_PAIR = {"nonlinear", "association", "group_difference", "cross_file", "time", "numeric_pair"}


def _node_id(name: str) -> str:
    return "source file" if name == SOURCE_COLUMN else name


def _sign(item: dict[str, Any], estimate: float | None) -> int:
    d = str(item.get("direction") or "")
    if d in {"positive", "increasing", "up", "higher"}:
        return 1
    if d in {"negative", "decreasing", "down", "lower"}:
        return -1
    if estimate is not None and item.get("effect_label", "").lower().startswith(
        ("spearman", "pearson", "kendall")
    ):
        return 1 if estimate > 0 else -1 if estimate < 0 else 0
    return 0


def _stats(frame: pl.DataFrame | None, name: str) -> dict[str, Any] | None:
    if frame is None or name not in frame.columns:
        return None
    s = frame[name]
    n, missing = s.len(), s.null_count()
    out: dict[str, Any] = {"n": n, "missing": missing, "distinct": int(s.n_unique())}
    if s.dtype.is_numeric() and s.dtype != pl.Boolean:
        v = s.drop_nulls().cast(pl.Float64).to_numpy()
        v = v[np.isfinite(v)]
        if v.size:
            q = np.quantile(v, [0.0, 0.25, 0.5, 0.75, 1.0])
            counts, edges = np.histogram(v, bins=min(16, max(4, int(np.unique(v).size))))
            out.update(
                kind="numeric",
                min=float(q[0]),
                q1=float(q[1]),
                median=float(q[2]),
                q3=float(q[3]),
                max=float(q[4]),
                mean=float(v.mean()),
                std=float(v.std(ddof=1)) if v.size > 1 else 0.0,
                hist=[int(c) for c in counts],
                edges=[float(e) for e in edges],
            )
        return out
    counts = s.drop_nulls().cast(pl.String).value_counts(sort=True)
    top = [{"label": str(r[0]), "count": int(r[1])} for r in counts.head(6).iter_rows()]
    out.update(kind="labels", top=top)
    return out


def _story(nid: str, node: dict[str, Any], links: list[dict[str, Any]], target: str | None) -> str:
    strong = [e for e in links if e.get("grade") in {"A", "B", "C", "D"}]

    def other(e: dict[str, Any]) -> str:
        return e["target"] if e["source"] == nid else e["source"]

    parts: list[str] = []
    if node.get("derived"):
        d = node["derived"]
        parts.append(
            f"{nid} is not measured: it is calculated as {d['formula_text']}, so its "
            f"patterns are those of {', '.join(d['inputs'])}."
        )
    if not strong:
        parts.append(
            f"No relationship of {nid} held up in this run."
            if links
            else f"{nid} has no stored relationship in this run."
        )
    else:
        ups = sorted(
            (e for e in strong if e["sign"] > 0), key=lambda e: -abs(e.get("estimate") or 0)
        )
        downs = sorted(
            (e for e in strong if e["sign"] < 0), key=lambda e: -abs(e.get("estimate") or 0)
        )
        groups = [e for e in strong if e["sign"] == 0]
        role = "a hub" if len(strong) >= 3 else "connected"
        parts.append(
            f"{nid} is {role}: {len(strong)} relationship{'s' if len(strong) != 1 else ''} held up."
        )
        if ups:
            names = ", ".join(other(e) for e in ups[:3])
            parts.append(
                f"When {nid} is higher, {names} tend{'s' if len(ups[:3]) == 1 else ''} "
                f"to be higher too."
            )
        if downs:
            names = ", ".join(other(e) for e in downs[:3])
            parts.append(
                f"When {nid} is higher, {names} tend{'s' if len(downs[:3]) == 1 else ''} "
                f"to be lower."
            )
        if groups:
            parts.append(
                f"It also differs between groups of "
                f"{', '.join(sorted({other(e) for e in groups})[:3])}."
            )
        best = max(strong, key=lambda e: abs(e.get("estimate") or 0) or e.get("strength", 0))
        if best.get("estimate") is not None:
            parts.append(
                f"Strongest link: {other(best)} ({best.get('effect_label') or 'effect'} "
                f"{best['estimate']:+.2f}, grade {best.get('grade')})."
            )
    if target and nid != target and not any(target in (e["source"], e["target"]) for e in strong):
        parts.append(f"No link to the outcome {target} held up.")
    if any(e.get("exploratory") for e in strong):
        parts.append("Exploratory: found without data set aside to check it.")
    return " ".join(parts)


def build_universe(
    payload: dict[str, Any], columns: dict[str, str], frame: pl.DataFrame | None = None
) -> dict[str, Any]:
    """Graph of one completed run. ``columns`` maps column name -> role (from the dataset)."""
    spec = payload.get("spec", {})
    target = spec.get("target")
    nodes: dict[str, dict[str, Any]] = {}

    def node(name: str) -> str:
        nid = _node_id(name)
        if nid not in nodes:
            nodes[nid] = {
                "id": nid,
                "role": "source" if name == SOURCE_COLUMN else columns.get(name, "other"),
                "is_target": name == target,
                "degree": 0,
                "alerts": [],
                "findings": [],
            }
        return nid

    for name in [*spec.get("numeric", []), *spec.get("categorical", [])]:
        node(name)
    if spec.get("time_column"):
        node(spec["time_column"])

    edges: list[dict[str, Any]] = []
    for item in payload.get("feed", []):
        if item.get("merged_into"):
            continue
        variables: list[str] = [v for v in item.get("variables", []) if v]
        ev = item.get("evidence", {})
        if item.get("kind") == "formula":
            facts: dict[str, Any] = (
                payload.get("details", {}).get(item["id"], {}).get("method", {}).get("facts", {})
                or {}
            )
            tgt = _node_id(variables[0]) if variables else None
            if tgt in nodes:
                inputs = list(facts.get("inputs") or variables[1:])
                text = str(facts.get("formula") or "").replace("`", "")
                nodes[tgt]["derived"] = {
                    "finding": item["id"],
                    "inputs": inputs,
                    "formula_text": text,
                }
                edges.extend(
                    {
                        "id": f"{item['id']}:{_node_id(inp)}:{tgt}",
                        "finding": item["id"],
                        "source": _node_id(inp),
                        "target": tgt,
                        "via": None,
                        "kind": "formula",
                        "family": "formula",
                        "family_label": "Exact formula",
                        "headline": item["headline"],
                        "effect_text": f"{tgt} = {text}",
                        "effect_label": None,
                        "sign": 1,
                        "estimate": None,
                        "grade": None,
                        "confirmed": True,
                        "exploratory": False,
                        "strength": 1.0,
                        "score": float(item.get("score", 0.0)),
                        "rank": item.get("rank"),
                    }
                    for inp in inputs
                    if _node_id(inp) in nodes
                )
            continue
        if ev.get("basis") == "descriptive":
            for v in variables:
                if _node_id(v) not in nodes:
                    continue  # alerts decorate analyzed columns; they do not add stars of their own
                nodes[_node_id(v)]["alerts"].append(
                    {
                        "finding": item["id"],
                        "headline": item["headline"],
                        "severity": item.get("severity"),
                    }
                )
            continue
        method: dict[str, Any] = (
            payload.get("details", {}).get(item["id"], {}).get("method", {}) or {}
        )
        effect: dict[str, Any] = method.get("effect") or {}
        estimate = effect.get("estimate")
        estimate = (
            float(estimate)
            if isinstance(estimate, (int, float)) and math.isfinite(estimate)
            else None
        )
        base = {
            "finding": item["id"],
            "sign": _sign(item, estimate),
            "estimate": estimate,
            "effect_label": item.get("effect_label"),
            "family": item["family"],
            "family_label": item["family_label"],
            "headline": item["headline"],
            "effect_text": item.get("effect_text"),
            "grade": ev.get("grade"),
            "confirmed": str(ev.get("confirmation", "")).startswith("confirmed"),
            "exploratory": bool(ev.get("exploratory")),
            "strength": float(item.get("score_components", {}).get("effect", 0.0)),
            "score": float(item.get("score", 0.0)),
            "rank": item.get("rank"),
        }
        pairs: list[tuple[str, str, str | None, str]] = []
        family = item["family"]
        if family in {"conditional", "reversal"} and len(variables) >= 3:
            kind = "reversal" if family == "reversal" else "explained_away"
            pairs.append((variables[0], variables[1], variables[2], kind))
        elif family in {"subgroup", "interaction"} and len(variables) >= 2:
            outcome = variables[0]
            pairs.extend((c, outcome, None, family) for c in variables[1:])
            if family == "interaction" and len(variables) >= 3:
                pairs.append((variables[1], variables[2], None, "synergy"))
        elif len(variables) >= 2:
            pairs.append((variables[0], variables[1], None, "pair" if family in _PAIR else family))
        for a, b, via, kind in pairs:
            na, nb = node(a), node(b)
            if na == nb:
                continue
            edge = {
                **base,
                "id": f"{item['id']}:{na}:{nb}",
                "source": na,
                "target": nb,
                "kind": kind,
                "via": node(via) if via else None,
            }
            edges.append(edge)
            for n in (na, nb):
                nodes[n]["degree"] += 1
                if item["id"] not in nodes[n]["findings"]:
                    nodes[n]["findings"].append(item["id"])
    for nid, nd in nodes.items():
        nd["stats"] = _stats(frame, nid)
        links = [e for e in edges if nid in (e["source"], e["target"]) and e["kind"] != "formula"]
        nd["story"] = _story(nid, nd, links, _node_id(target) if target else None)
        nd.setdefault("derived", None)
    return {
        "target": _node_id(target) if target else None,
        "nodes": list(nodes.values()),
        "edges": edges,
        "rows": spec.get("rows"),
        "dataset": payload.get("manifest", {}).get("inputs", [{}])[0].get("name")
        if payload.get("manifest")
        else None,
    }
