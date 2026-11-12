"""Exact formulas: columns that are computed from other columns.

A column that equals another column times a constant, or the product, ratio, sum or difference
of two columns (times a constant), carries no information of its own: every association with it
is inherited. Finding the formula is a fact about the table, not an inference, so no p-value is
computed and nothing enters the hypothesis ledger.

Rule: the formula holds within ``TOLERANCE`` (1%) relative error on every complete row, with at
least ``MIN_ROWS`` rows and a fitted constant that is not trivially 0. Rounding in the stored
values (for example revenue in thousands with one decimal) stays well inside the tolerance.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any

import numpy as np
import polars as pl

from edaforge.discovery.describe import Observation
from edaforge.explain.language import fmt_num, md_code

__all__ = ["formulas"]

TOLERANCE = 0.01
MIN_ROWS = 5
MAX_COLUMNS = 40

_Array = np.ndarray[Any, Any]
_OPS: dict[str, tuple[str, Callable[[_Array, _Array], _Array]]] = {
    "times": ("×", lambda x, y: x * y),
    "over": ("÷", lambda x, y: x / y),
    "plus": ("+", lambda x, y: x + y),
    "minus": ("−", lambda x, y: x - y),
}


def _constant(z: np.ndarray[Any, Any], base: np.ndarray[Any, Any]) -> float | None:
    """The constant k with z ≈ k·base, if it holds within the tolerance on every row.

    A short constant (one or two significant digits, such as 0.03 for 30 days / 1,000) is
    preferred when it fits every row as well: the fitted median absorbs rounding in the data.
    """
    ok = np.isfinite(z) & np.isfinite(base) & (base != 0) & (z != 0)
    if int(ok.sum()) < MIN_ROWS or int(ok.sum()) < np.isfinite(z).sum():
        return None
    ratios = z[ok] / base[ok]
    k = float(np.median(ratios))
    if k == 0 or not np.isfinite(k):
        return None
    if float(np.abs(ratios / k - 1.0).max()) > TOLERANCE:
        return None
    for digits in (1, 2):
        short = float(f"{k:.{digits - 1}e}")
        if float(np.abs(ratios / short - 1.0).max()) <= TOLERANCE:
            return short
    return k


def _nice(k: float) -> str:
    for c in (1.0, 10.0, 100.0, 1000.0, 0.1, 0.01, 0.001):
        if abs(k / c - 1.0) < 1e-3:
            return "" if c == 1.0 else f" × {fmt_num(c)}"
    short = f"{k:g}"
    return f" × {short}" if len(short) <= 7 else f" × {fmt_num(k)}"


def _max_error(z: np.ndarray[Any, Any], fit: np.ndarray[Any, Any]) -> float:
    ok = np.isfinite(z) & np.isfinite(fit) & (z != 0)
    return float(np.max(np.abs(fit[ok] / z[ok] - 1.0))) if ok.any() else 0.0


def formulas(frame: pl.DataFrame, numeric: list[str]) -> list[Observation]:
    cols = [c for c in numeric[:MAX_COLUMNS] if c in frame.columns]
    if len(cols) < 2 or frame.height < MIN_ROWS:
        return []
    values = {c: frame[c].cast(pl.Float64).to_numpy() for c in cols}
    explained: set[str] = set()
    used: set[str] = set()
    out: list[Observation] = []
    # Products and sums first (revenue = customers × spend), then rescaled copies (the later
    # column is called the copy), then ratios and differences: the same identity can be written
    # several ways, and the composed column is the natural one to call derived.
    passes: tuple[tuple[tuple[str, ...], bool, list[str]], ...] = (
        (("times", "plus"), False, cols),
        ((), True, cols[::-1]),
        (("over", "minus"), False, cols),
    )
    for ops, rescale, order in passes:
        for target in order:
            if target in explained or target in used:
                continue
            found = _search(target, cols, values, explained, ops, rescale)
            if found is not None:
                explained.add(target)
                used.update(found[3])
                out.append(_observation(target, values[target], *found))
    return out


def _search(
    target: str,
    cols: list[str],
    values: dict[str, np.ndarray[Any, Any]],
    explained: set[str],
    ops: tuple[str, ...],
    rescale: bool,
) -> tuple[str, float, np.ndarray[Any, Any], list[str]] | None:
    z = values[target]
    if np.unique(z[np.isfinite(z)]).size < MIN_ROWS:
        return None
    others = [c for c in cols if c != target and c not in explained]
    if rescale:
        for a in others:  # one column times a constant (a rescaled copy)
            k = _constant(z, values[a])
            if k is not None and abs(k - 1.0) > 1e-9:
                return f"{md_code(a)}{_nice(k)}", k, k * values[a], [a]
    for a, b in itertools.permutations(others, 2):
        for op in ops:
            if op in {"times", "plus"} and a > b:
                continue  # symmetric: each pair once
            sym, fn = _OPS[op]
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                base = fn(values[a], values[b])
            k = _constant(z, base)
            if k is None or (op in {"plus", "minus"} and abs(k - 1.0) > TOLERANCE):
                continue
            k = 1.0 if op in {"plus", "minus"} else k
            return f"{md_code(a)} {sym} {md_code(b)}{_nice(k)}", k, k * base, [a, b]
    return None


def _observation(
    target: str,
    z: np.ndarray[Any, Any],
    text: str,
    k: float,
    fit: np.ndarray[Any, Any],
    inputs: list[str],
) -> Observation:
    err = _max_error(z, fit)
    n = int(np.isfinite(z).sum())
    headline = f"{target} is computed from {' and '.join(inputs)}"
    plain = (
        f"{md_code(target)} = {text}, within {100 * err:.1f}% on every one of the {n:,} rows. "
        f"It is calculated from {'these columns' if len(inputs) > 1 else 'this column'}, not "
        f"measured separately, so any pattern with {md_code(target)} is a pattern with its inputs."
    )
    analyst = (
        f"Deterministic relation {md_code(target)} = {text} (constant {fmt_num(k)}; max "
        f"relative error {100 * err:.2f}%, tolerance {100 * TOLERANCE:.0f}%, n = {n:,}). Treat "
        f"{md_code(target)} as derived: "
        "do not count its associations as separate evidence, and do not use it together with "
        "its inputs as predictors."
    )
    return Observation(
        kind="formula",
        family="formula",
        headline=headline,
        plain=plain,
        analyst=analyst,
        scientist=analyst,
        variables=[target, *inputs],
        severity="warning",
        records=n,
        share=1.0,
        method=(
            "exact formula search: rescaling, product, ratio, sum and difference of two "
            "columns (1% tolerance)"
        ),
        facts={
            "target": target,
            "inputs": inputs,
            "constant": k,
            "max_relative_error": err,
            "formula": text,
        },
        caveats=["A fact about the table (checked on every row), not a statistical inference."],
    )
