"""The Insight Feed: ranked, de-duplicated findings with their full detail (milestone 5).

Ranking is a transparent sum (stored with every item and shown in the app):

    score = 0.35·evidence + 0.25·effect + 0.15·coverage + 0.15·robustness + 0.10·relevance

* evidence: the Rigor Kernel's grade (A 1.0, B 0.85, C 0.65, D 0.35, E 0.1); descriptive facts by
  severity (critical 0.75, warning 0.55, info 0.3);
* effect: 1 − exp(−ln 2 · |effect| / SESOI), so 0.5 at the smallest effect size of interest;
* coverage: √(share of rows the finding concerns);
* robustness: mean of stability and specification agreement, 0 when not measured;
* relevance: 1 if the chosen target is involved, 0.4 if a target was chosen but is not involved,
  0.85 when no target was chosen. With a chosen target the weights become 0.30 evidence, 0.20
  effect, 0.10 coverage, 0.10 robustness and 0.30 relevance (``WEIGHTS_TARGET``).

p-values never enter the ranking. Findings about the same columns and pattern type are merged
(the best one is shown; the others are listed under it). Every number on a card is formatted
here from stored engine values.
"""

from __future__ import annotations

import math
from typing import Any

from edaforge.discovery.base import AnalysisSpec
from edaforge.discovery.describe import Observation
from edaforge.explain.language import GRADE_LABEL, GRADE_WORDING, fmt_num, fmt_p
from edaforge.models import ChartSpec, Finding
from edaforge.report.markdown import markdown_to_html

__all__ = ["FAMILY_LABELS", "SESOI", "build_feed"]

SESOI: dict[str, float] = {
    "spearman_rho": 0.10,
    "pearson_r": 0.10,
    "partial_rho": 0.10,
    "cohen_d": 0.20,
    "cliffs_delta": 0.147,  # Romano et al. (2006): below 0.147 is negligible
    "epsilon_squared": 0.01,
    "cramers_v": 0.10,
    "risk_diff": 0.02,
    "interaction_risk_diff": 0.02,
    "mean_diff": 0.0,  # standardized below
    "interaction_mean_diff": 0.0,
    "std_shift": 0.30,
    "ks_d": 0.10,
}
FAMILY_LABELS: dict[str, str] = {
    "association": "Association",
    "nonlinear": "Non-linear relationship",
    "group_difference": "Group difference",
    "subgroup": "Segment",
    "interaction": "Interaction / synergy",
    "conditional": "Explained by another variable",
    "reversal": "Reversal (Simpson's paradox)",
    "time": "Change over time",
    "cross_file": "Difference between files",
    "data_quality": "Data quality",
    "anomalies": "Unusual records",
    "formula": "Exact formula",
}
_GRADE_SCORE = {"A": 1.0, "B": 0.85, "C": 0.65, "D": 0.35, "E": 0.1}
_SEVERITY_SCORE = {"critical": 0.75, "warning": 0.55, "info": 0.3}


def _family(f: Finding) -> str:
    t = f.facts.get("template")
    if t == "numeric_pair":
        return "nonlinear" if f.facts.get("nonlinear") else "association"
    if t == "category_association":
        return "association"
    if t == "conditional":
        return "reversal" if f.facts.get("mode") == "reversal" else "conditional"
    if t == "change_point":
        return "time"
    return str(t or "association")


def _pct(x: Any, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{digits}f}%"


def _signed(x: float) -> str:
    text = fmt_num(x)
    return text if x < 0 or text == "0" else "+" + text


def _effect_text(f: Finding) -> tuple[str | None, str | None, str | None]:
    """(effect label, effect text, direction) for the card, from stored facts."""
    x: dict[str, Any] = f.facts  # engine-computed JSON
    t = x.get("template")
    try:
        if t == "numeric_pair":
            rho = float(x["rho"])
            return (
                "Spearman ρ",
                (
                    f"{fmt_num(rho)} [{fmt_num(x['rho_low'])}, {fmt_num(x['rho_high'])}] · "
                    f"curve R² {_pct(x['r2_spline'], 0)}"
                ),
                "positive" if rho > 0 else "negative",
            )
        if t == "group_difference":
            if "cliffs_delta" in x:
                return (
                    "Cliff's delta",
                    (
                        f"{fmt_num(x['cliffs_delta'])} [{fmt_num(x['cliffs_low'])}, "
                        f"{fmt_num(x['cliffs_high'])}]"
                    ),
                    None,
                )
            if "cohen_d" in x:
                return (
                    "Cohen's d",
                    (
                        f"{fmt_num(x['cohen_d'])} [{fmt_num(x['cohen_d_low'])}, "
                        f"{fmt_num(x['cohen_d_high'])}]"
                    ),
                    None,
                )
            return (
                "Largest gap",
                (
                    f"{fmt_num(x['gap'])} [{fmt_num(x['gap_low'])}, "
                    f"{fmt_num(x['gap_high'])}] ({x['top_level']} vs {x['bottom_level']})"
                ),
                None,
            )
        if t == "category_association":
            return (
                "Cramér's V",
                (
                    f"{fmt_num(x['cramers_v'])} [{fmt_num(x['cramers_v_low'])}, "
                    f"{fmt_num(x['cramers_v_high'])}]"
                ),
                None,
            )
        if t == "subgroup":
            d = float(x["diff"])
            if x.get("binary"):
                return (
                    "Difference",
                    f"{_signed(100 * d)} pts ({_pct(x['value_in'])} vs {_pct(x['value_out'])})",
                    "positive" if d > 0 else "negative",
                )
            return (
                "Difference",
                f"{_signed(d)} [{fmt_num(x['diff_low'])}, {fmt_num(x['diff_high'])}]",
                "positive" if d > 0 else "negative",
            )
        if t == "interaction":
            d = float(x["did"])
            unit = " pts" if x.get("binary") else ""
            return ("Beyond additive", f"{_signed(100 * d if x.get('binary') else d)}{unit}", None)
        if t == "conditional":
            return (
                "Correlation",
                f"{fmt_num(x['rho_marginal'])} → {fmt_num(x['rho_partial'])} after {x['z']}",
                None,
            )
        if t == "change_point":
            pc = x.get("pct_change")
            text = (
                f"{_signed(100 * float(pc))}% from {x['break']}"
                if pc is not None
                else f"{_signed(float(x['diff']))} from {x['break']}"
            )
            return ("Change", text, "positive" if float(x["diff"]) > 0 else "negative")
        if t == "cross_file":
            if x.get("unit_hint"):
                return ("Median ratio", f"{fmt_num(x['ratio'])} ({x['unit_hint']}?)", None)
            if x.get("numeric"):
                return ("Median", f"{fmt_num(x['median_a'])} vs {fmt_num(x['median_b'])}", None)
            return ("Cramér's V", fmt_num(x.get("cramers_v")), None)
    except (KeyError, TypeError, ValueError):
        return None, None, None
    return None, None, None


def _records(f: Finding, n_rows: int) -> tuple[int | None, str | None]:
    x: dict[str, Any] = f.facts  # engine-computed JSON
    t = x.get("template")
    if t == "subgroup":
        k = int(x.get("n_in", 0) or 0)
        return k, f"{k:,} rows in the segment ({_pct(x.get('share_in'))})"
    if t == "interaction":
        cells = x.get("cells")
        k = int(cells.get("both", {}).get("n", 0)) if isinstance(cells, dict) else 0  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        return k, f"{k:,} rows where both hold"
    if t == "change_point":
        return int(x.get("n_periods", 0) or 0), f"{x.get('n_periods')} {x.get('grain')}s"
    if t == "cross_file":
        k = int(x.get("n_a", 0) or 0) + int(x.get("n_b", 0) or 0)
        return k, f"{k:,} rows from two sources"
    n = int(x.get("n", f.evidence.n) or 0)
    return n, f"{n:,} rows analyzed"


def _confirmation_text(f: Finding) -> str:
    c = f.evidence.confirmation
    if c.status == "confirmed":
        return (
            "confirmed on held-out data"
            if c.method == "sealed_holdout"
            else "confirmed by cross-fitting"
        )
    if c.method == "none":
        return "exploratory: too little data to hold some out"
    return "not confirmed on held-out data"


def _effect_component(f: Finding) -> float:
    e = f.effect
    if e is None:
        return 0.0
    measure = e.measure
    estimate = abs(e.estimate)
    if measure in {"mean_diff", "interaction_mean_diff"}:
        std = f.facts.get("std_effect")
        if isinstance(std, int | float):
            estimate, sesoi = abs(float(std)), 0.2
        else:
            return 0.5
    else:
        sesoi = SESOI.get(measure, 0.0)
    if sesoi <= 0:
        return 0.5
    return 1.0 - math.exp(-math.log(2.0) * estimate / sesoi)


def _robustness(f: Finding) -> float:
    parts: list[float] = []
    if f.evidence.stability is not None:
        parts.append(f.evidence.stability)
    if f.evidence.specs_total:
        parts.append((f.evidence.specs_consistent or 0) / f.evidence.specs_total)
    return sum(parts) / len(parts) if parts else 0.0


def _relevance(variables: list[str], spec: AnalysisSpec) -> float:
    if spec.target is None:
        return 0.85
    return 1.0 if spec.target in variables else 0.4


WEIGHTS = {
    "evidence": 0.35,
    "effect": 0.25,
    "coverage": 0.15,
    "robustness": 0.15,
    "relevance": 0.10,
}
# With a chosen outcome, findings about it should lead (PROJECT_PROMPT.md section 8, "practical
# relevance when the user has identified an outcome"); evidence still outweighs it.
WEIGHTS_TARGET = {
    "evidence": 0.30,
    "effect": 0.20,
    "coverage": 0.10,
    "robustness": 0.10,
    "relevance": 0.30,
}


def weights_for(spec: AnalysisSpec) -> dict[str, float]:
    return WEIGHTS_TARGET if spec.target else WEIGHTS


def _score(
    evidence: float,
    effect: float,
    coverage: float,
    robustness: float,
    relevance: float,
    spec: AnalysisSpec,
) -> tuple[float, dict[str, float]]:
    components = {
        "evidence": evidence,
        "effect": effect,
        "coverage": coverage,
        "robustness": robustness,
        "relevance": relevance,
    }
    weights = weights_for(spec)
    return round(sum(weights[k] * v for k, v in components.items()), 4), {
        k: round(v, 4) for k, v in components.items()
    }


def _lenses(plain: str, analyst: str, scientist: str) -> dict[str, dict[str, str]]:
    return {
        "plain": {"markdown": plain, "html": markdown_to_html(plain, heading_offset=1)},
        "analyst": {"markdown": analyst, "html": markdown_to_html(analyst, heading_offset=1)},
        "scientist": {"markdown": scientist, "html": markdown_to_html(scientist, heading_offset=1)},
    }


def _finding_item(
    f: Finding,
    charts: list[ChartSpec],
    spec: AnalysisSpec,
    n_rows: int,
    dataset: str,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    family = _family(f)
    if family == "cross_file" and f.facts.get("unit_hint"):
        family_label = "Cross-file mismatch (units?)"
    else:
        family_label = FAMILY_LABELS.get(family, family)
    variables = [
        v.column for v in f.variables if v.column != spec.environment or family == "cross_file"
    ]
    label, text, direction = _effect_text(f)
    records, records_label = _records(f, n_rows)
    grade = f.evidence.grade
    evidence = _GRADE_SCORE[grade]
    coverage = (
        math.sqrt(min(1.0, (records or 0) / max(n_rows, 1)))
        if f.facts.get("template") in {"subgroup", "interaction"}
        else 1.0
    )
    score, components = _score(
        evidence, _effect_component(f), coverage, _robustness(f), _relevance(variables, spec), spec
    )
    conf = f.evidence.confirmation
    item: dict[str, Any] = {
        "id": f.id,
        "kind": f.kind.value,
        "family": family,
        "family_label": family_label,
        "headline": f.lenses.plain.headline.replace("`", ""),
        "summary": f.lenses.analyst.headline.replace("`", ""),
        "variables": variables,
        "datasets": [dataset],
        "effect_label": label,
        "effect_text": text,
        "direction": direction,
        "records": records,
        "records_label": records_label,
        "evidence": {
            "basis": "inferential",
            "grade": grade,
            "label": GRADE_LABEL[grade],
            "wording": GRADE_WORDING[grade],
            "confirmation": _confirmation_text(f),
            "q_value": conf.q_value,
            "exploratory": f.evidence.exploratory,
        },
        "severity": None,
        "caveats": f.caveats[:4],
        "score": score,
        "score_components": components,
        "chart": charts[0].model_dump(mode="json") if charts else None,
        "merged": [],
    }
    entries = [
        e
        for e in ledger.get("entries", [])
        if e.get("hypothesis_id") in set(f.provenance.hypothesis_ids)
    ]
    detail = {
        **item,
        "lenses": _lenses(
            f.lenses.plain.markdown, f.lenses.analyst.markdown, f.lenses.scientist.markdown
        ),
        "charts": [c.model_dump(mode="json") for c in charts],
        "method": {
            "analyzer": f.provenance.analyzer,
            "analyzer_version": f.provenance.analyzer_version,
            "test": f.evidence.test,
            "statistic": f.evidence.statistic,
            "p_value": f.evidence.p_value,
            "p_text": fmt_p(f.evidence.p_value),
            "q_value": f.evidence.q_value,
            "n": f.evidence.n,
            "effect": f.effect.model_dump(mode="json") if f.effect else None,
            "secondary_effects": [e.model_dump(mode="json") for e in f.secondary_effects],
            "assumptions": [a.model_dump(mode="json") for a in f.evidence.assumptions],
            "confirmation": conf.model_dump(mode="json"),
            "grade_reasons": f.evidence.grade_reasons,
            "rung": f.evidence.rung,
            "rung_reasons": f.evidence.rung_reasons,
            "stability": f.evidence.stability,
            "specs_consistent": f.evidence.specs_consistent,
            "specs_total": f.evidence.specs_total,
            "params": f.provenance.params,
            "hypothesis_ids": f.provenance.hypothesis_ids,
            "ledger": entries,
            "facts": {k: v for k, v in f.facts.items() if k not in {"points", "table", "groups"}},
        },
        "provenance": f.provenance.model_dump(mode="json"),
    }
    return {"item": item, "detail": detail}


def _observation_item(
    o: Observation, spec: AnalysisSpec, n_rows: int, dataset: str
) -> dict[str, Any]:
    evidence = _SEVERITY_SCORE[o.severity]
    share = o.share if o.share is not None else ((o.records or 0) / max(n_rows, 1))
    effect = min(1.0, 0.3 + 2 * share)
    score, components = _score(
        evidence, effect, math.sqrt(min(1.0, share)), 0.0, _relevance(o.variables, spec), spec
    )
    label = "Possible leakage" if o.kind == "leakage" else FAMILY_LABELS[o.family]
    records_label = (
        f"{o.records:,} rows" + (f" ({100 * share:.1f}%)" if o.share is not None else "")
        if o.records is not None
        else None
    )
    item: dict[str, Any] = {
        "id": o.id,
        "kind": o.kind,
        "family": o.family,
        "family_label": label,
        "headline": o.headline,
        "summary": o.method,
        "variables": o.variables,
        "datasets": [dataset],
        "effect_label": None,
        "effect_text": None,
        "direction": None,
        "records": o.records,
        "records_label": records_label,
        "evidence": {
            "basis": "descriptive",
            "grade": None,
            "label": "fact",
            "wording": "exact count, no inference",
            "confirmation": "descriptive check",
            "q_value": None,
            "exploratory": False,
        },
        "severity": o.severity,
        "caveats": o.caveats,
        "score": score,
        "score_components": components,
        "chart": o.charts[0].model_dump(mode="json") if o.charts else None,
        "merged": [],
    }
    detail = {
        **item,
        "lenses": _lenses(o.plain, o.analyst, o.scientist),
        "charts": [c.model_dump(mode="json") for c in o.charts],
        "method": {
            "analyzer": f"describe.{o.kind}",
            "analyzer_version": "1.0.0",
            "test": None,
            "statistic": None,
            "p_value": None,
            "p_text": "n/a",
            "q_value": None,
            "n": n_rows,
            "effect": None,
            "secondary_effects": [],
            "assumptions": [],
            "confirmation": {"status": "not_applicable", "method": "none"},
            "grade_reasons": [
                (
                    "Descriptive check: computed exactly on every row; no hypothesis test, "
                    "so no evidence grade."
                )
            ],
            "rung": "R0",
            "rung_reasons": [],
            "params": {},
            "hypothesis_ids": [],
            "ledger": [],
            "facts": o.facts,
            "rule": o.method,
        },
        "provenance": {},
    }
    return {"item": item, "detail": detail}


def _topic(
    item: dict[str, Any], aliases: dict[str, str] | None = None
) -> tuple[str, frozenset[str]]:
    family: str = item["family"]
    group = {"nonlinear": "association"}.get(family, family)
    columns: list[str] = item["variables"]
    names = [(aliases or {}).get(v, v) for v in columns]
    variables = frozenset(names)
    if family == "cross_file":
        variables = frozenset(names[:1])
    return group, variables


def build_feed(
    findings: list[Finding],
    charts_by_id: dict[str, list[ChartSpec]],
    observations: list[Observation],
    spec: AnalysisSpec,
    n_rows: int,
    dataset: str,
    ledger: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    built = [
        _finding_item(f, charts_by_id.get(f.id, []), spec, n_rows, dataset, ledger)
        for f in findings
    ]
    mismatched = {
        str(f.facts.get("column")): f.id
        for f in findings
        if f.facts.get("template") == "cross_file"
        and f.facts.get("unit_hint")
        and f.evidence.grade in {"A", "B", "C"}
    }
    for b in built:
        item = b["item"]
        if item["family"] == "cross_file":
            continue
        for column, fid in mismatched.items():
            if column in item["variables"]:
                note = (
                    f"{column} may be recorded in different units in the combined files "
                    f"({fid}); results that pool "
                    "the files may be distorted."
                )
                item["caveats"] = [note, *item["caveats"]]
                b["detail"]["caveats"] = item["caveats"]
    derived = {
        str(o.facts["target"]): set(o.facts["inputs"]) for o in observations if o.kind == "formula"
    }
    for b in built:
        item = b["item"]
        names = set(item["variables"])
        hit = next(((t, ins) for t, ins in derived.items() if t in names and names & ins), None)
        if hit is not None and len(names) == 2:
            t, ins = hit
            note = (
                f"{t} is calculated from {', '.join(sorted(ins))} (see the exact formula), "
                f"so part of this pattern is built in."
            )
            item["caveats"] = [note, *item["caveats"]]
            b["detail"]["caveats"] = item["caveats"]
            item["score"] = round(item["score"] - 0.15, 4)
            item["score_components"]["redundancy"] = -0.15
    for k, o in enumerate(observations, start=1):
        o.id = f"D-{k:03d}"
        built.append(_observation_item(o, spec, n_rows, dataset))
    built.sort(key=lambda b: (-b["item"]["score"], b["item"]["id"]))
    leaders: dict[tuple[str, frozenset[str]], dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    for b in built:
        item, detail = b["item"], b["detail"]
        key = _topic(item, spec.aliases)
        copies = [v for v in item["variables"] if v in spec.aliases]
        if (
            len(item["variables"]) == 2
            and len({spec.aliases.get(v, v) for v in item["variables"]}) == 1
        ):
            note = (
                "These two columns are near-copies of each other, so this pattern is "
                "expected and says little on its own."
            )
            item["caveats"] = [note, *item["caveats"]]
            b["detail"]["caveats"] = item["caveats"]
            item["score"] = round(item["score"] - 0.15, 4)
            item["score_components"]["redundancy"] = -0.15
        lead = leaders.get(key)
        if lead is not None and item["evidence"]["basis"] == lead["evidence"]["basis"]:
            lead["merged"].append(item["id"])
            item["merged_into"] = lead["id"]
            if copies:
                item["caveats"] = [
                    (
                        f"Repeats {lead['id']} with a near-copy column "
                        f"({', '.join(f'{c} ≈ {spec.aliases[c]}' for c in copies)})."
                    ),
                    *item["caveats"],
                ]
                b["detail"]["caveats"] = item["caveats"]
            item["score"] = round(item["score"] - 0.15, 4)
            item["score_components"]["redundancy"] = -0.15
        else:
            leaders[key] = item
        items.append(item)
        details[item["id"]] = detail
    items.sort(key=lambda i: (-i["score"], i["id"]))
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
        details[item["id"]].update(
            {
                "rank": rank,
                "score": item["score"],
                "score_components": item["score_components"],
                "score_weights": weights_for(spec),
                "merged": item["merged"],
            }
        )
    by_vars = {i["id"]: set(i["variables"]) for i in items}
    for item in items:
        related: list[dict[str, str]] = []
        for other in items:
            if other["id"] == item["id"]:
                continue
            shared = by_vars[item["id"]] & by_vars[other["id"]]
            if other["id"] in item["merged"] or item.get("merged_into") == other["id"]:
                related.append(
                    {"id": other["id"], "type": "duplicates", "headline": other["headline"]}
                )
            elif len(shared) >= 2 or (len(shared) == 1 and len(by_vars[item["id"]]) == 1):
                related.append(
                    {"id": other["id"], "type": "same columns", "headline": other["headline"]}
                )
        details[item["id"]]["related"] = related[:8]
    return items, details
