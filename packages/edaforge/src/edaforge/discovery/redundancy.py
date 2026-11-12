"""Near-copy columns: numbers that move together almost perfectly, labels that map one-to-one.

A data set often carries the same information twice (a price in two tables, a code and its
name, a total and the same total in another currency). Each copy would otherwise produce its own
finding, and the feed would fill with repeats. Clusters are found here before the analysis;
every column is still tested (the false-discovery correction counts every test, which is the
conservative choice), and the feed merges findings that differ only by the copy used.

The clustering is descriptive: no p-value is computed and nothing enters the hypothesis ledger.
Thresholds: |Spearman rho| >= 0.95 on at least 30 complete rows; labels whose distinct pairs are
exactly as many as the distinct values of each (a bijection) with at least 2 values.
"""

from __future__ import annotations

import numpy as np
import polars as pl
from scipy.stats import rankdata

__all__ = ["RHO", "find_redundant"]

RHO = 0.95
MIN_ROWS = 30
SAMPLE = 5_000
MAX_COLUMNS = 300
SEED = 20240611


def _clusters(columns: list[str], pairs: list[tuple[str, str]]) -> list[list[str]]:
    parent = {c: c for c in columns}

    def root(c: str) -> str:
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c

    for a, b in pairs:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, list[str]] = {}
    for c in columns:
        groups.setdefault(root(c), []).append(c)
    return [g for g in groups.values() if len(g) > 1]


def _numeric_pairs(frame: pl.DataFrame, numeric: list[str]) -> list[tuple[str, str, float]]:
    cols = numeric[:MAX_COLUMNS]
    if len(cols) < 2:
        return []
    data = frame.select(cols)
    if data.height > SAMPLE:
        data = data.sample(n=SAMPLE, seed=SEED)
    values = {c: data[c].cast(pl.Float64).to_numpy() for c in cols}
    out: list[tuple[str, str, float]] = []
    for i, a in enumerate(cols):
        x = values[a]
        for b in cols[i + 1 :]:
            y = values[b]
            ok = np.isfinite(x) & np.isfinite(y)
            if int(ok.sum()) < MIN_ROWS:
                continue
            rx, ry = rankdata(x[ok]), rankdata(y[ok])
            if rx.std() == 0 or ry.std() == 0:
                continue
            rho = float(np.corrcoef(rx, ry)[0, 1])
            if abs(rho) >= RHO:
                out.append((a, b, rho))
    return out


def _label_pairs(frame: pl.DataFrame, categorical: list[str]) -> list[tuple[str, str]]:
    cols = categorical[:MAX_COLUMNS]
    out: list[tuple[str, str]] = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            both = frame.select(a, b).drop_nulls()
            if both.height < MIN_ROWS:
                continue
            na, nb = both[a].n_unique(), both[b].n_unique()
            if na >= 2 and na == nb and both.n_unique() == na:
                out.append((a, b))
    return out


def find_redundant(
    frame: pl.DataFrame, numeric: list[str], categorical: list[str]
) -> tuple[dict[str, str], list[str]]:
    """``aliases`` (copy -> representative) and one note per cluster for the run log."""
    numeric_pairs = _numeric_pairs(frame, numeric)
    label_pairs = _label_pairs(frame, categorical)
    order = {c: k for k, c in enumerate([*numeric, *categorical])}
    missing = {c: frame[c].null_count() for c in [*numeric, *categorical] if c in frame.columns}
    aliases: dict[str, str] = {}
    notes: list[str] = []
    rho = {frozenset((a, b)): r for a, b, r in numeric_pairs}
    for kind, cols, pairs in (
        ("numeric", numeric, [(a, b) for a, b, _ in numeric_pairs]),
        ("label", categorical, label_pairs),
    ):
        for group in _clusters(cols, pairs):
            lead = min(group, key=lambda c: (missing.get(c, 0), order[c]))
            rest = [c for c in group if c != lead]
            for c in rest:
                aliases[c] = lead
            if kind == "numeric":
                parts = [
                    f"{c} (ρ = {rho[frozenset((lead, c))]:.2f})"
                    if frozenset((lead, c)) in rho
                    else c
                    for c in rest
                ]
                notes.append(
                    f"Near-copies of {lead}: {', '.join(parts)} move together almost "
                    f"perfectly (|Spearman ρ| ≥ {RHO}). "
                    "All are still tested; findings that repeat with a copy are merged under "
                    "the first one."
                )
            else:
                notes.append(
                    f"{lead} and {', '.join(rest)} label the same groups one-to-one. All are "
                    f"still tested; "
                    "findings that repeat with a copy are merged under the first one."
                )
    return aliases, notes
