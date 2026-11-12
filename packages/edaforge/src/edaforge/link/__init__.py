"""Connecting files: relationship suggestions, join previews and traceable combined tables.

Milestone 3 (PROJECT_PROMPT.md section 3, step 3). Nothing is joined silently:

* :func:`suggest_links` proposes joins, appends and time alignments with the evidence behind
  each (value overlap in both directions, uniqueness, names, types) and classifies pairs that
  share nothing usable as unrelated;
* :func:`preview_link` computes exactly what a link would produce: row counts, matched and
  unmatched records, fan-out, duplicate keys, the share of rows multiplied, and whether shared
  non-key columns agree between the files;
* :func:`build_link` builds the combined table. Every row keeps its origin: appended rows carry
  ``__source__`` and ``__source_row__``; joined rows carry ``__row__<dataset-id>`` for each side.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import polars as pl
from pydantic import BaseModel, Field, field_validator

from edaforge.ingest import ROW_COLUMN, ColumnInfo, ParseIssue, is_internal

__all__ = [
    "KeyPair",
    "LinkError",
    "LinkPreview",
    "LinkSpec",
    "LinkSuggestion",
    "Rescale",
    "Table",
    "UnitMismatch",
    "build_link",
    "preview_link",
    "scale_mismatch",
    "suggest_links",
    "unit_hint",
]

SOURCE_COLUMN = "__source__"
SOURCE_ROW = "__source_row__"
_KEY_ROLES = {"identifier", "categorical", "datetime"}
_SUMMABLE = re.compile(
    r"(amount|revenue|sales|cost|qty|quantity|units|spend|value|total|count|volume|clicks|visits)",
    re.IGNORECASE,
)
_UNIT_FACTORS = (100.0, 1000.0)
_MIN_UNIT_VALUES = 10  # non-missing values needed on each side before comparing scales


def unit_hint(ratio: float | None) -> str | None:
    """'×100' / '×1,000' (or their inverses) when a ratio of medians is within 15% of one.

    A heuristic hint that two sources record a column in different units (cents and dollars,
    grams and kilograms), not a test. Shared by the link review and the cross-file analysis.
    """
    if ratio is None or ratio <= 0 or not math.isfinite(ratio):
        return None
    for factor in _UNIT_FACTORS:
        label = f"{factor:,.0f}"
        for value, text in ((factor, f"×{label}"), (1 / factor, f"÷{label}")):
            if abs(math.log(ratio / value)) <= math.log(1.15):
                return text
    return None


def _factor_of(hint: str) -> float:
    number = float(hint[1:].replace(",", ""))
    return number if hint.startswith("×") else 1 / number


def scale_mismatch(a: pl.Series, b: pl.Series) -> tuple[float, float, float, str] | None:
    """(median of a, median of b, b/a, hint) when the typical values look like different units."""
    va, vb = a.drop_nulls().cast(pl.Float64), b.drop_nulls().cast(pl.Float64)
    if va.len() < _MIN_UNIT_VALUES or vb.len() < _MIN_UNIT_VALUES:
        return None
    ma, mb = va.median(), vb.median()
    if not isinstance(ma, float) or not isinstance(mb, float) or ma == 0.0 or (ma > 0) != (mb > 0):
        return None
    ratio = mb / ma
    hint = unit_hint(ratio)
    return None if hint is None else (ma, mb, ratio, hint)


class LinkError(Exception):
    """A link that cannot be built as specified; the message is shown to the user."""


class KeyPair(BaseModel):
    left: str
    right: str


class Rescale(BaseModel):
    """Multiply one side's values of a column before appending (a unit alignment the user chose)."""

    column: str
    side: Literal["left", "right"]
    factor: float

    @field_validator("factor")
    @classmethod
    def _unit_factor(cls, value: float) -> float:
        allowed = [f for base in _UNIT_FACTORS for f in (base, 1 / base)]
        if not any(math.isclose(value, f, rel_tol=1e-9) for f in allowed):
            msg = "A rescale must multiply or divide by 100 or 1,000 (a unit change)."
            raise ValueError(msg)
        return value


class LinkSpec(BaseModel):
    kind: Literal["join", "append", "time_aligned"]
    left: str
    right: str
    keys: list[KeyPair] = []
    how: Literal["left", "inner"] = "left"
    right_mode: Literal["lookup", "aggregate", "expand"] = "lookup"
    time_grain: Literal["day", "week", "month"] | None = None
    name: str | None = Field(default=None, max_length=160)
    rescale: list[Rescale] = []


class LinkSuggestion(BaseModel):
    id: str
    kind: Literal["join", "append", "time_aligned", "unrelated"]
    left: str
    right: str
    keys: list[KeyPair] = []
    confidence: float
    cardinality: Literal["1:1", "m:1", "1:m", "m:m"] | None = None
    reasons: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, float | int | str | None] = {}
    spec: LinkSpec | None = None
    status: Literal["confirmed", "rejected"] | None = None
    link_id: str | None = None


class PreviewWarning(BaseModel):
    severity: Literal["critical", "warning", "info"]
    message: str


class OverlapColumn(BaseModel):
    column: str
    compared: int
    agree: int
    agree_share: float | None
    examples: list[list[str]] = []  # [key, left value, right value]


class UnitMismatch(BaseModel):
    """A shared numeric column whose typical value differs by about ×100 or ×1,000."""

    column: str
    median_left: float
    median_right: float
    ratio: float  # median_right / median_left, after any rescale already applied
    hint: str
    options: list[Rescale]  # the two rescales that would align the sides
    applied: Rescale | None = None


class LinkPreview(BaseModel):
    spec: LinkSpec
    kind: str
    n_left: int
    n_right: int
    n_result: int
    matched_left: int
    matched_right: int
    unmatched_left: int
    unmatched_right: int
    cardinality: str
    max_right_per_key: int
    duplicate_keys_left: int
    duplicate_keys_right: int
    row_multiplication: float
    warnings: list[PreviewWarning]
    overlap_columns: list[OverlapColumn] = []
    unit_mismatches: list[UnitMismatch] = []
    columns: list[str]
    sample: list[list[Any]]
    requires_ack: bool
    ack_reasons: list[str] = []  # what the user acknowledges when confirming


@dataclass(frozen=True)
class Table:
    """A dataset as the link layer sees it."""

    id: str
    name: str
    frame: pl.DataFrame
    columns: list[ColumnInfo]
    fingerprint: str
    sources: tuple[str, ...] = ()

    @property
    def info(self) -> dict[str, ColumnInfo]:
        return {c.name: c for c in self.columns}


# ---------------------------------------------------------------- names


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _tokens(name: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return {t for t in re.split(r"[^a-z0-9]+", spaced.lower()) if t}


def _stem(table_name: str) -> str:
    base = re.split(r"[ ›.]", table_name.strip(), maxsplit=1)[0]
    stem = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    return stem or "right"


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


_KEY_WORDS = {"id", "key", "code", "no", "num", "number", "nr", "ref", "uuid", "guid"}


def name_similarity(a: str, b: str, table_a: str, table_b: str) -> float:
    """1 for the same normalized name, 0.8 for "customer_id" vs "id" in a customers table, ..."""
    if _norm(a) == _norm(b):
        return 1.0
    ta, tb = _tokens(a), _tokens(b)
    core_a, core_b = ta - _KEY_WORDS, tb - _KEY_WORDS
    stems = {_singular(t) for t in _tokens(table_a) | _tokens(table_b)}
    if ta & _KEY_WORDS and tb & _KEY_WORDS:
        if not core_a and {_singular(t) for t in core_b} <= stems | {
            _singular(t) for t in _tokens(table_a)
        }:
            return 0.8
        if not core_b and {_singular(t) for t in core_a} <= stems | {
            _singular(t) for t in _tokens(table_b)
        }:
            return 0.8
    union = ta | tb
    if union and len(ta & tb) / len(union) >= 0.5:
        return 0.5
    return 0.0


# ---------------------------------------------------------------- key values


def _key_kind(info: ColumnInfo) -> str | None:
    if info.dtype in {"date", "datetime"}:
        return "time"
    if info.role not in _KEY_ROLES and not (info.dtype == "integer" and info.role == "numeric"):
        return None
    if info.dtype in {"string", "integer"}:
        return "value"
    return None


def _key_series(frame: pl.DataFrame, column: str, kind: str, grain: str | None) -> pl.Series:
    series = frame[column]
    if kind == "time":
        series = series.cast(pl.Datetime("us")).dt.truncate(
            {"day": "1d", "week": "1w", "month": "1mo"}[grain or "day"]
        )
        return series.cast(pl.Date)
    return series.cast(pl.String).str.strip_chars()


def _grain(series: pl.Series) -> Literal["day", "week", "month"]:
    values = series.drop_nulls().unique().sort()
    if values.len() < 3:
        return "day"
    as_date = values.cast(pl.Date)
    if bool((as_date.dt.day() == 1).all()):
        return "month"
    diffs = as_date.diff().drop_nulls().dt.total_days()
    shortest = int(cast("int | None", diffs.min()) or 0)
    if diffs.len() and shortest >= 7 and bool((diffs % 7 == 0).all()):
        return "week"
    return "day"


@dataclass
class _Candidate:
    left_col: str
    right_col: str
    kind: str  # "value" or "time"
    overlap_left: float  # share of left distinct keys found on the right
    overlap_right: float
    unique_left: float
    unique_right: float
    distinct_left: int
    distinct_right: int
    shared: int
    name_score: float
    score: float
    grain: str | None


def _uniqueness(series: pl.Series) -> tuple[float, int]:
    present = series.drop_nulls()
    if present.len() == 0:
        return 0.0, 0
    distinct = present.n_unique()
    return distinct / present.len(), distinct


def _candidates(a: Table, b: Table) -> list[_Candidate]:
    out: list[_Candidate] = []
    infos_a = [(c, kind) for c in a.columns if (kind := _key_kind(c))]
    infos_b = [(c, kind) for c in b.columns if (kind := _key_kind(c))]
    for ca, kind_a in infos_a:
        for cb, kind_b in infos_b:
            if kind_a != kind_b:
                continue
            name_score = name_similarity(ca.name, cb.name, a.name, b.name)
            both_numeric_ids = ca.dtype == "integer" and cb.dtype == "integer"
            if both_numeric_ids and name_score < 0.5:
                continue  # integer ranges overlap by accident (order 1..n vs customer 1..m)
            grain = None
            if kind_a == "time":
                grain = max(
                    _grain(a.frame[ca.name]),
                    _grain(b.frame[cb.name]),
                    key=["day", "week", "month"].index,
                )
            ka = _key_series(a.frame, ca.name, kind_a, grain)
            kb = _key_series(b.frame, cb.name, kind_a, grain)
            ua, da = _uniqueness(ka)
            ub, db = _uniqueness(kb)
            if da == 0 or db == 0:
                continue
            distinct_a = ka.drop_nulls().unique()
            distinct_b = kb.drop_nulls().unique()
            shared = int(distinct_a.is_in(distinct_b.implode()).sum())
            if shared == 0:
                continue
            ol, orr = shared / da, shared / db
            small = min(da, db)
            if small < 10 and not (name_score == 1.0 and max(ua, ub) >= 0.999):
                continue  # tiny value sets (yes/no, 1..5) overlap by construction
            if kind_a == "time" and min(da, db) < 5:
                continue
            overlap = max(ol, orr)
            key_quality = 1.0 if max(ua, ub) >= 0.999 else 0.35
            score = 0.55 * overlap + 0.25 * name_score + 0.20 * key_quality
            if overlap < 0.3 or score < 0.45:
                continue
            out.append(
                _Candidate(
                    left_col=ca.name,
                    right_col=cb.name,
                    kind=kind_a,
                    overlap_left=ol,
                    overlap_right=orr,
                    unique_left=ua,
                    unique_right=ub,
                    distinct_left=da,
                    distinct_right=db,
                    shared=shared,
                    name_score=name_score,
                    score=score,
                    grain=grain,
                )
            )
    out.sort(key=lambda c: -c.score)
    return out


def _cardinality(unique_left: float, unique_right: float) -> Literal["1:1", "m:1", "1:m", "m:m"]:
    one_left = unique_left >= 0.999
    one_right = unique_right >= 0.999
    if one_left and one_right:
        return "1:1"
    if one_right:
        return "m:1"
    if one_left:
        return "1:m"
    return "m:m"


def _append_suggestion(a: Table, b: Table) -> LinkSuggestion | None:
    cols_a = {c.name: c for c in a.columns}
    cols_b = {c.name: c for c in b.columns}
    shared = sorted(set(cols_a) & set(cols_b))
    union = set(cols_a) | set(cols_b)
    if not shared:
        return None
    jaccard = len(shared) / len(union)
    compatible = [c for c in shared if _family(cols_a[c].dtype) == _family(cols_b[c].dtype)]
    compat = len(compatible) / len(shared)
    if jaccard < 0.7 or compat < 0.8:
        return None
    reasons = [
        f"{len(shared)} of {len(union)} columns have the same name",
        f"{len(compatible)} of {len(shared)} shared columns have compatible types",
    ]
    warnings: list[str] = []
    only_a = sorted(set(cols_a) - set(cols_b))
    only_b = sorted(set(cols_b) - set(cols_a))
    if only_a or only_b:
        warnings.append(
            "Columns found in only one file are kept and are missing for the other file's rows: "
            + ", ".join(only_a + only_b)
        )
    mismatched = [c for c in shared if c not in compatible]
    if mismatched:
        warnings.append("Different types in the two files: " + ", ".join(mismatched))
    for column in compatible:
        if _family(cols_a[column].dtype) != "number":
            continue
        found = scale_mismatch(a.frame[column], b.frame[column])
        if found is not None:
            warnings.append(
                f"{column} is on different scales: typical value {_fmt(found[0])} in "
                f"{a.name} vs {_fmt(found[1])} in "
                f"{b.name} ({found[3]}), possibly different units. Review the link to align them."
            )
    ids = [c for c in shared if cols_a[c].role == "identifier"]
    for column in ids[:2]:
        va = a.frame[column].drop_nulls().cast(pl.String).unique()
        vb = b.frame[column].drop_nulls().cast(pl.String).unique()
        both = int(va.is_in(vb.implode()).sum())
        if both:
            warnings.append(
                f"{both:,} values of {column} appear in both files; appending could "
                f"count those records twice."
            )
        else:
            reasons.append(f"no {column} value appears in both files (no double counting)")
    confidence = round(0.6 * jaccard + 0.4 * compat, 3)
    spec = LinkSpec(kind="append", left=a.id, right=b.id, name=f"{a.name} + {b.name}")
    return LinkSuggestion(
        id="",
        kind="append",
        left=a.id,
        right=b.id,
        confidence=confidence,
        reasons=reasons,
        warnings=warnings,
        evidence={
            "name_jaccard": round(jaccard, 3),
            "type_compatibility": round(compat, 3),
            "shared_columns": len(shared),
        },
        spec=spec,
    )


def _family(dtype: str) -> str:
    return {"integer": "number", "float": "number", "date": "time", "datetime": "time"}.get(
        dtype, dtype
    )


def _join_suggestion(a: Table, b: Table) -> LinkSuggestion | None:
    candidates = _candidates(a, b)
    if not candidates:
        return None
    best = candidates[0]
    card = _cardinality(best.unique_left, best.unique_right)
    keys = [best]
    if card == "m:m" and best.kind == "value":
        composite = _composite(a, b, candidates)
        if composite is not None:
            keys, card = composite
    # Put the "many" side on the left so the default link keeps one row per base record.
    left, right = a, b
    if card == "1:m":
        left, right = b, a
        keys = [_flip(k) for k in keys]
        card = "m:1"
    k0 = keys[0]
    kind: Literal["join", "time_aligned"] = "time_aligned" if k0.kind == "time" else "join"
    if kind == "time_aligned" and card == "m:m":
        return None  # shared dates without a time-indexed side are not an alignment
    reasons = [
        (
            f"{k0.shared:,} {k0.left_col} values in {left.name} also appear as "
            f"{k0.right_col} in {right.name}"
        ),
        (
            f"{k0.overlap_left:.0%} of the {k0.left_col} values in {left.name} are found in "
            f"{right.name}; "
            f"{k0.overlap_right:.0%} of the values in {right.name} are found in {left.name}"
        ),
    ]
    if k0.name_score == 1.0:
        reasons.append("the column names match")
    elif k0.name_score >= 0.8:
        reasons.append("the column names refer to the same thing")
    if len(keys) > 1:
        reasons.append(
            "the combination of " + " and ".join(k.left_col for k in keys) + " identifies the rows"
        )
    warnings: list[str] = []
    if card == "m:1":
        reasons.append(
            f"each {k0.right_col} appears once in {right.name}: many {left.name} rows "
            f"per {right.name} row"
        )
    elif card == "1:1":
        reasons.append("each key appears at most once on both sides")
    else:
        warnings.append(
            "Keys repeat on both sides (many-to-many). A plain join would multiply rows and "
            "double count; summarize one side per key first."
        )
    if k0.overlap_left < 0.95:
        warnings.append(
            f"{1 - k0.overlap_left:.0%} of the {k0.left_col} values in {left.name} have "
            f"no match in {right.name}."
        )
    if kind == "time_aligned":
        reasons.append(f"both files have dates covering the same period (aligned by {k0.grain})")
    confidence = round(min(0.99, k0.score), 3)
    mode: Literal["lookup", "aggregate", "expand"] = (
        "lookup" if card in {"m:1", "1:1"} else "aggregate"
    )
    spec = LinkSpec(
        kind=kind,
        left=left.id,
        right=right.id,
        keys=[KeyPair(left=k.left_col, right=k.right_col) for k in keys],
        how="left",
        right_mode=mode,
        time_grain=k0.grain if kind == "time_aligned" else None,  # pyright: ignore[reportArgumentType]
        name=f"{left.name} + {right.name}",
    )
    return LinkSuggestion(
        id="",
        kind=kind,
        left=left.id,
        right=right.id,
        keys=spec.keys,
        confidence=confidence,
        cardinality=card,
        reasons=reasons,
        warnings=warnings,
        evidence={
            "overlap_left": round(k0.overlap_left, 4),
            "overlap_right": round(k0.overlap_right, 4),
            "unique_left": round(k0.unique_left, 4),
            "unique_right": round(k0.unique_right, 4),
            "shared_values": k0.shared,
            "name_similarity": k0.name_score,
        },
        spec=spec,
    )


def _flip(c: _Candidate) -> _Candidate:
    return _Candidate(
        left_col=c.right_col,
        right_col=c.left_col,
        kind=c.kind,
        overlap_left=c.overlap_right,
        overlap_right=c.overlap_left,
        unique_left=c.unique_right,
        unique_right=c.unique_left,
        distinct_left=c.distinct_right,
        distinct_right=c.distinct_left,
        shared=c.shared,
        name_score=c.name_score,
        score=c.score,
        grain=c.grain,
    )


def _composite(
    a: Table, b: Table, candidates: list[_Candidate]
) -> tuple[list[_Candidate], Literal["1:1", "m:1", "1:m", "m:m"]] | None:
    named = [c for c in candidates if c.name_score == 1.0][:5]
    for i, first in enumerate(named):
        for second in named[i + 1 :]:
            if second.left_col == first.left_col or second.right_col == first.right_col:
                continue
            grain = first.grain or second.grain
            ua = a.frame.select(
                pl.struct(
                    _key_series(a.frame, first.left_col, first.kind, grain),
                    _key_series(a.frame, second.left_col, second.kind, grain),
                )
                .is_unique()
                .all()
            ).item()
            ub = b.frame.select(
                pl.struct(
                    _key_series(b.frame, first.right_col, first.kind, grain),
                    _key_series(b.frame, second.right_col, second.kind, grain),
                )
                .is_unique()
                .all()
            ).item()
            if ua or ub:
                card = _cardinality(1.0 if ua else 0.0, 1.0 if ub else 0.0)
                return [first, second], card
    return None


def suggest_links(
    tables: Sequence[Table], ancestry: Mapping[str, set[str]]
) -> list[LinkSuggestion]:
    """Suggestions for every pair of tables that are not built from one another."""
    suggestions: list[LinkSuggestion] = []
    for i, a in enumerate(tables):
        for b in tables[i + 1 :]:
            if a.id in ancestry.get(b.id, set()) or b.id in ancestry.get(a.id, set()):
                continue
            if ancestry.get(a.id, set()) & ancestry.get(b.id, set()):
                continue  # two tables derived from the same file
            found: list[LinkSuggestion] = []
            append = _append_suggestion(a, b)
            if append is not None:
                found.append(append)
            join = _join_suggestion(a, b)
            if join is not None:
                found.append(join)
            if not found:
                found.append(
                    LinkSuggestion(
                        id="",
                        kind="unrelated",
                        left=a.id,
                        right=b.id,
                        confidence=0.0,
                        reasons=[
                            (
                                "no column pair shares enough values to be a key, and the "
                                "columns are too different to stack the files"
                            )
                        ],
                    )
                )
            suggestions.extend(found)
    for k, s in enumerate(
        sorted(suggestions, key=lambda s: (s.kind == "unrelated", -s.confidence)), start=1
    ):
        s.id = f"S{k:03d}"
    return sorted(suggestions, key=lambda s: s.id)


# ---------------------------------------------------------------- building


def _prepare_keys(
    frame: pl.DataFrame, columns: Sequence[str], infos: Mapping[str, ColumnInfo], grain: str | None
) -> pl.DataFrame:
    exprs: list[pl.Expr] = []
    for i, column in enumerate(columns):
        info = infos.get(column)
        if info is None:
            msg = f"Column {column!r} does not exist."
            raise LinkError(msg)
        kind = "time" if info.dtype in {"date", "datetime"} else "value"
        if info.dtype == "float":
            msg = f"{column} holds decimal numbers and cannot be used as a key."
            raise LinkError(msg)
        exprs.append(pl.lit(_key_series(frame, column, kind, grain)).alias(f"__key{i}__"))
    return frame.with_columns(exprs)


def _row_column(table: Table) -> str:
    return f"{ROW_COLUMN}{table.id}"


def _traced(table: Table) -> pl.DataFrame:
    """The table with its ``__row__`` renamed to ``__row__<id>`` (combined inputs keep theirs)."""
    frame = table.frame
    if ROW_COLUMN in frame.columns:
        frame = frame.rename({ROW_COLUMN: _row_column(table)})
    return frame


def _aggregate(
    right: Table, keys: Sequence[str], stem: str
) -> tuple[pl.DataFrame, list[ColumnInfo], list[str]]:
    infos = right.info
    aggs: list[pl.Expr] = [pl.len().alias(f"{stem}_rows")]
    new: list[ColumnInfo] = [
        ColumnInfo(
            name=f"{stem}_rows",
            original_name=f"{stem}_rows",
            dtype="integer",
            role="numeric",
            role_reason=f"number of {right.name} rows per key",
            n_missing=0,
        )
    ]
    notes = [f"rows → {stem}_rows (count; 0 where there is no match)"]
    for name, info in infos.items():
        if name in keys or info.pii:
            continue
        if info.role == "numeric":
            aggs.append(pl.col(name).cast(pl.Float64).mean().alias(f"{name}_mean"))
            new.append(
                ColumnInfo(
                    name=f"{name}_mean",
                    original_name=name,
                    dtype="float",
                    role="numeric",
                    role_reason=f"mean of {name} per key in {right.name}",
                    n_missing=0,
                )
            )
            summary = "mean"
            if _SUMMABLE.search(name):
                aggs.append(pl.col(name).cast(pl.Float64).sum().alias(f"{name}_sum"))
                new.append(
                    ColumnInfo(
                        name=f"{name}_sum",
                        original_name=name,
                        dtype="float",
                        role="numeric",
                        role_reason=f"sum of {name} per key in {right.name}",
                        n_missing=0,
                    )
                )
                summary = "mean, sum"
            notes.append(f"{name} → {summary}")
        elif info.role == "boolean":
            aggs.append(pl.col(name).cast(pl.Float64).mean().alias(f"{name}_share"))
            new.append(
                ColumnInfo(
                    name=f"{name}_share",
                    original_name=name,
                    dtype="float",
                    role="numeric",
                    role_reason=f"share of true {name} per key in {right.name}",
                    n_missing=0,
                )
            )
            notes.append(f"{name} → share true")
        elif info.role == "datetime":
            aggs.append(pl.col(name).min().alias(f"{name}_first"))
            aggs.append(pl.col(name).max().alias(f"{name}_last"))
            new.extend(
                ColumnInfo(
                    name=f"{name}_{suffix}",
                    original_name=name,
                    dtype=info.dtype,
                    role="datetime",
                    role_reason=f"{suffix} {name} per key in {right.name}",
                    n_missing=0,
                )
                for suffix in ("first", "last")
            )
            notes.append(f"{name} → first, last")
    key_cols = [f"__key{i}__" for i in range(len(keys))]
    grouped = right.frame.group_by(key_cols).agg(aggs)
    return grouped, new, notes


def _column_meta(
    name: str, info: ColumnInfo | None, frame: pl.DataFrame, reason: str | None = None
) -> ColumnInfo:
    n_missing = int(frame[name].null_count())
    if info is None:
        return ColumnInfo(
            name=name,
            original_name=name,
            dtype="string",
            role="categorical",
            role_reason=reason or "",
            n_missing=n_missing,
        )
    update: dict[str, Any] = {"name": name, "n_missing": n_missing}
    if reason:
        update["role_reason"] = reason
    return info.model_copy(update=update)


@dataclass
class BuiltLink:
    frame: pl.DataFrame
    columns: list[ColumnInfo]
    issues: list[ParseIssue]
    preview: LinkPreview
    fingerprint: str


def _fingerprint(spec: LinkSpec, left: Table, right: Table) -> str:
    payload = json.dumps(
        {
            "spec": spec.model_dump(mode="json"),
            "left": left.fingerprint,
            "right": right.fingerprint,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _append(spec: LinkSpec, left: Table, right: Table) -> BuiltLink:
    infos_l, infos_r = left.info, right.info
    shared_numeric = {
        n
        for n in set(infos_l) & set(infos_r)
        if _family(infos_l[n].dtype) == "number" == _family(infos_r[n].dtype)
    }
    rescale: dict[tuple[str, str], Rescale] = {}
    for r in spec.rescale:
        if r.column not in shared_numeric:
            msg = f"{r.column} is not a numeric column of both tables, so it cannot be rescaled."
            raise LinkError(msg)
        if any(c == r.column for c, _ in rescale):
            msg = f"Choose one rescale for {r.column}."
            raise LinkError(msg)
        rescale[(r.column, r.side)] = r
    frames: list[pl.DataFrame] = []
    issues_rescale: list[ParseIssue] = []
    for side, table in (("left", left), ("right", right)):
        frame = table.frame
        for (column, where), r in rescale.items():
            if where == side:
                frame = frame.with_columns(pl.col(column).cast(pl.Float64) * r.factor)
                verb = (
                    f"multiplied by {r.factor:,.0f}"
                    if r.factor > 1
                    else f"divided by {1 / r.factor:,.0f}"
                )
                issues_rescale.append(
                    ParseIssue(
                        level="warning",
                        code="rescaled",
                        column=column,
                        message=(
                            f"{column} values from {table.name} were {verb} at your request, "
                            f"to put both files in the same units."
                        ),
                    )
                )
        if ROW_COLUMN in frame.columns:
            frame = frame.rename({ROW_COLUMN: SOURCE_ROW})
        if SOURCE_COLUMN not in frame.columns:
            frame = frame.with_columns(pl.lit(table.name).alias(SOURCE_COLUMN))
        frames.append(frame)
    warnings: list[PreviewWarning] = []
    mismatches: list[UnitMismatch] = []
    unresolved: list[str] = []
    for name in sorted(shared_numeric):
        found = scale_mismatch(left.frame[name], right.frame[name])
        applied = rescale.get((name, "left")) or rescale.get((name, "right"))
        if found is None:
            if applied is not None:
                warnings.append(
                    PreviewWarning(
                        severity="warning",
                        message=(
                            f"{name} was rescaled although both files already have similar "
                            f"typical values; check that this is intended."
                        ),
                    )
                )
            continue
        ml, mr, ratio, hint = found
        factor = _factor_of(hint)  # right ≈ factor × left
        options = [
            Rescale(column=name, side="right", factor=1 / factor),
            Rescale(column=name, side="left", factor=factor),
        ]
        mismatches.append(
            UnitMismatch(
                column=name,
                median_left=ml,
                median_right=mr,
                ratio=ratio,
                hint=hint,
                options=options,
                applied=applied,
            )
        )
        before = (
            f"the typical value is {_fmt(ml)} in {left.name} and {_fmt(mr)} in {right.name} "
            f"({hint})"
        )
        aligned = applied is not None and any(
            o.side == applied.side and math.isclose(o.factor, applied.factor, rel_tol=1e-9)
            for o in options
        )
        if aligned:
            warnings.append(
                PreviewWarning(
                    severity="info",
                    message=(
                        f"{name}: {before}; the rescale you chose puts both files on the "
                        f"same scale."
                    ),
                )
            )
            continue
        unresolved.append(name)
        warnings.append(
            PreviewWarning(
                severity="critical",
                message=(
                    f"{name}: {before}. A ratio this close to a power of ten usually means "
                    f"the files use different "
                    "units (for example cents and dollars). Stacked as they are, the column "
                    "mixes two scales; analyses then compare it between the files only."
                    if applied is None
                    else (
                        f"{name}: {before}, and the rescale you chose moves the files "
                        f"further apart. Choose the other direction."
                    )
                ),
            )
        )
    for name in sorted(set(infos_l) & set(infos_r)):
        if _family(infos_l[name].dtype) != _family(infos_r[name].dtype):
            warnings.append(
                PreviewWarning(
                    severity="warning",
                    message=f"{name} has different types in the two files; it is stored as text.",
                )
            )
            frames = [f.with_columns(pl.col(name).cast(pl.String)) for f in frames]
        elif (
            infos_l[name].dtype != infos_r[name].dtype
            or (name, "left") in rescale
            or (name, "right") in rescale
        ):
            target = pl.Float64 if _family(infos_l[name].dtype) == "number" else pl.Datetime("us")
            frames = [f.with_columns(pl.col(name).cast(target)) for f in frames]
    combined = pl.concat(frames, how="diagonal_relaxed")
    order = [SOURCE_COLUMN, SOURCE_ROW] + [
        c for c in combined.columns if c not in {SOURCE_COLUMN, SOURCE_ROW}
    ]
    combined = combined.select([c for c in order if c in combined.columns])
    combined = combined.with_columns(
        pl.int_range(1, combined.height + 1, dtype=pl.Int64).alias(ROW_COLUMN)
    ).select([ROW_COLUMN, *[c for c in combined.columns if c != ROW_COLUMN]])
    only = sorted(set(infos_l) ^ set(infos_r))
    if only:
        warnings.append(
            PreviewWarning(
                severity="info",
                message="Columns present in one file only are missing for the other file's rows: "
                + ", ".join(only),
            )
        )
    columns: list[ColumnInfo] = []
    for name in combined.columns:
        if is_internal(name):
            continue
        info = infos_l.get(name) or infos_r.get(name)
        meta = _column_meta(name, info, combined)
        if name in infos_l and name in infos_r and infos_l[name].role != infos_r[name].role:
            meta = meta.model_copy(
                update={"role_reason": f"{meta.role_reason} (roles differ between files)"}
            )
        columns.append(meta)
    for name, info in (infos_l | infos_r).items():
        if info.role == "identifier":
            both = (
                int(
                    left.frame[name]
                    .drop_nulls()
                    .cast(pl.String)
                    .unique()
                    .is_in(right.frame[name].drop_nulls().cast(pl.String).unique().implode())
                    .sum()
                )
                if name in infos_l and name in infos_r
                else 0
            )
            if both:
                warnings.append(
                    PreviewWarning(
                        severity="warning",
                        message=(
                            f"{both:,} {name} values appear in both files; those records may "
                            f"be counted twice."
                        ),
                    )
                )
    user_cols = [c for c in combined.columns if not is_internal(c)]
    ack_reasons = [
        f"{name} is on different scales in the two files; it will be compared between the "
        f"files only, "
        "not used in other analyses, until the units are aligned"
        for name in unresolved
    ]
    preview = LinkPreview(
        spec=spec,
        kind="append",
        n_left=left.frame.height,
        n_right=right.frame.height,
        n_result=combined.height,
        matched_left=left.frame.height,
        matched_right=right.frame.height,
        unmatched_left=0,
        unmatched_right=0,
        cardinality="append",
        max_right_per_key=0,
        duplicate_keys_left=0,
        duplicate_keys_right=0,
        row_multiplication=1.0,
        warnings=warnings,
        unit_mismatches=mismatches,
        columns=[SOURCE_COLUMN, *user_cols],
        sample=[list(r) for r in combined.select([SOURCE_COLUMN, *user_cols]).head(12).rows()]
        + [list(r) for r in combined.select([SOURCE_COLUMN, *user_cols]).tail(8).rows()],
        requires_ack=bool(unresolved),
        ack_reasons=ack_reasons,
    )
    issues = [
        ParseIssue(
            level="info",
            code="appended",
            message=(
                f"Stacked {left.name} ({left.frame.height:,} rows) and {right.name} "
                f"({right.frame.height:,} rows). {SOURCE_COLUMN} names each row's file and "
                f"{SOURCE_ROW} its row number there."
            ),
        ),
        *issues_rescale,
        *[
            ParseIssue(
                level="warning" if w.severity != "info" else "info",
                code="append_warning",
                message=w.message,
            )
            for w in warnings
        ],
    ]
    return BuiltLink(
        frame=combined,
        columns=columns,
        issues=issues,
        preview=preview,
        fingerprint=_fingerprint(spec, left, right),
    )


def _fmt(value: float) -> str:
    """A number for messages: three significant digits, thousands separated."""
    if value == 0 or not math.isfinite(value):
        return f"{value:g}"
    digits = 2 - math.floor(math.log10(abs(value)))
    return f"{round(value, digits):,.{max(0, digits)}f}"


def _join(spec: LinkSpec, left: Table, right: Table) -> BuiltLink:
    if not spec.keys:
        msg = "Choose at least one key column on each side."
        raise LinkError(msg)
    grain = spec.time_grain if spec.kind == "time_aligned" else None
    lkeys = [k.left for k in spec.keys]
    rkeys = [k.right for k in spec.keys]
    for lk, rk in zip(lkeys, rkeys, strict=True):
        lt, rt = left.info.get(lk), right.info.get(rk)
        if lt is None or rt is None:
            msg = f"Unknown key column {lk if lt is None else rk!r}."
            raise LinkError(msg)
        if (_family(lt.dtype) == "time") != (_family(rt.dtype) == "time"):
            msg = f"{lk} and {rk} have incompatible types ({lt.dtype} and {rt.dtype})."
            raise LinkError(msg)
    lframe = _prepare_keys(_traced(left), lkeys, left.info, grain)
    rframe = _prepare_keys(_traced(right), rkeys, right.info, grain)
    key_cols = [f"__key{i}__" for i in range(len(lkeys))]
    stem = _stem(right.name)
    warnings: list[PreviewWarning] = []
    issues: list[ParseIssue] = []

    l_null = int(
        lframe.select(pl.any_horizontal([pl.col(c).is_null() for c in key_cols])).to_series().sum()
    )
    r_counts = (
        rframe.filter(pl.all_horizontal([pl.col(c).is_not_null() for c in key_cols]))
        .group_by(key_cols)
        .len()
    )
    l_counts = (
        lframe.filter(pl.all_horizontal([pl.col(c).is_not_null() for c in key_cols]))
        .group_by(key_cols)
        .len()
    )
    dup_left = int((l_counts["len"] > 1).sum())
    dup_right = int((r_counts["len"] > 1).sum())
    max_right = int(r_counts["len"].max() or 0)  # pyright: ignore[reportArgumentType]
    card = _cardinality(1.0 if dup_left == 0 else 0.0, 1.0 if dup_right == 0 else 0.0)
    matched_keys = l_counts.join(r_counts.select(key_cols), on=key_cols, how="semi")
    matched_left = int(matched_keys["len"].sum() or 0)
    matched_right = int(
        r_counts.join(l_counts.select(key_cols), on=key_cols, how="semi")["len"].sum() or 0
    )
    # Tracing columns of the right side that the left side already has (two combined inputs).
    right_internal = [c for c in rframe.columns if is_internal(c) and c not in key_cols]
    internal_renames = {c: f"{c}{right.id}" for c in right_internal if c in lframe.columns}
    rframe = rframe.rename(internal_renames)
    right_internal = [internal_renames.get(c, c) for c in right_internal]

    # Shared non-key columns: rename the right copy and compare values on matched keys.
    right_user = [c for c in right.frame.columns if not is_internal(c) and c not in rkeys]
    left_names = set(lframe.columns)
    renames: dict[str, str] = {}
    for c in right_user:
        if c in left_names:
            target, k = f"{c}_{stem}", 2
            while target in left_names or target in renames.values():
                target = f"{c}_{stem}{k}"
                k += 1
            renames[c] = target
    overlap: list[OverlapColumn] = []

    if spec.right_mode == "aggregate":
        grouped, new_infos, notes = _aggregate(
            Table(right.id, right.name, rframe, right.columns, right.fingerprint), rkeys, stem
        )
        clash = {c for c in grouped.columns if c in left_names and c not in key_cols}
        if clash:
            grouped = grouped.rename({c: f"{c}_{stem}" for c in clash})
            new_infos = [
                i.model_copy(update={"name": f"{i.name}_{stem}"}) if i.name in clash else i
                for i in new_infos
            ]
        joined = lframe.join(grouped, on=key_cols, how=spec.how, nulls_equal=False, coalesce=True)
        rows_col = new_infos[0].name
        joined = joined.with_columns(pl.col(rows_col).fill_null(0))
        added = new_infos
        issues.append(
            ParseIssue(
                level="info",
                code="aggregated",
                message=f"{right.name} was summarized per {', '.join(rkeys)} before joining: "
                + "; ".join(notes)
                + ".",
            )
        )
        n_result = joined.height
    else:
        payload = rframe.select([*key_cols, *right_internal, *right_user]).rename(renames)
        if spec.right_mode == "lookup" and dup_right:
            msg = (
                f"{dup_right:,} {', '.join(rkeys)} values repeat in {right.name}, so a "
                f"lookup would "
                "multiply rows. Choose 'summarize per key' or acknowledge the row multiplication."
            )
            warnings.append(PreviewWarning(severity="critical", message=msg))
        joined = lframe.join(payload, on=key_cols, how=spec.how, nulls_equal=False, coalesce=True)
        n_result = joined.height
        added = [right.info[c].model_copy(update={"name": renames.get(c, c)}) for c in right_user]
        for original, renamed in renames.items():
            issues.append(
                ParseIssue(
                    level="info",
                    code="column_renamed",
                    message=(
                        f"{original} from {right.name} is called {renamed} here; {original} "
                        f"is the column from {left.name}."
                    ),
                    column=renamed,
                )
            )
            pair = joined.filter(
                pl.col(original).is_not_null() & pl.col(renamed).is_not_null()
            ).select(key_cols[0], original, renamed)
            compared = pair.height
            if compared:
                eq = pair.with_columns(
                    (
                        pl.col(original).cast(pl.String).str.strip_chars()
                        == pl.col(renamed).cast(pl.String).str.strip_chars()
                    ).alias("eq")
                )
                agree = int(eq["eq"].sum())
                bad = eq.filter(~pl.col("eq")).head(5)
                overlap.append(
                    OverlapColumn(
                        column=original,
                        compared=compared,
                        agree=agree,
                        agree_share=agree / compared,
                        examples=[
                            [str(v) for v in r]
                            for r in bad.select(key_cols[0], original, renamed).rows()
                        ],
                    )
                )
                if agree < compared:
                    warnings.append(
                        PreviewWarning(
                            severity="warning",
                            message=(
                                f"{original} disagrees between the files for "
                                f"{compared - agree:,} of {compared:,} "
                                f"matched rows ({1 - agree / compared:.1%})."
                            ),
                        )
                    )
    n_left = left.frame.height
    multiplication = n_result / n_left if n_left else 1.0
    unmatched_left = n_left - matched_left
    if l_null:
        warnings.append(
            PreviewWarning(
                severity="info",
                message=f"{l_null:,} {left.name} rows have a missing key and cannot match.",
            )
        )
    if unmatched_left and spec.how == "left":
        warnings.append(
            PreviewWarning(
                severity="warning" if unmatched_left / max(n_left, 1) > 0.05 else "info",
                message=(
                    f"{unmatched_left:,} {left.name} rows "
                    f"({unmatched_left / max(n_left, 1):.1%}) have no match in "
                    f"{right.name}; they are kept with missing {right.name} columns."
                ),
            )
        )
    if unmatched_left and spec.how == "inner":
        warnings.append(
            PreviewWarning(
                severity="warning",
                message=(
                    f"{unmatched_left:,} {left.name} rows have no match and are dropped by "
                    f"the inner join."
                ),
            )
        )
    unmatched_right = right.frame.height - matched_right
    if unmatched_right and spec.right_mode != "aggregate":
        warnings.append(
            PreviewWarning(
                severity="info",
                message=(
                    f"{unmatched_right:,} {right.name} rows match no {left.name} row and are "
                    f"not used."
                ),
            )
        )
    if card == "m:m" and spec.right_mode == "expand":
        warnings.append(
            PreviewWarning(
                severity="critical",
                message=(
                    "Keys repeat on both sides: rows multiply and values of both files are "
                    "double counted."
                ),
            )
        )
    if multiplication > 1.0 + 1e-9:
        warnings.append(
            PreviewWarning(
                severity="critical",
                message=(
                    f"The result has {n_result:,} rows, {multiplication:.2f}× the {n_left:,} "
                    f"rows of {left.name}. "
                    f"Each {left.name} row is repeated once per matching {right.name} row, "
                    f"so sums and counts over {left.name} columns would be inflated."
                ),
            )
        )
    requires_ack = multiplication > 1.0 + 1e-9 or (card == "m:m" and spec.right_mode != "aggregate")
    ack_reasons: list[str] = []
    if multiplication > 1.0 + 1e-9:
        ack_reasons.append(
            f"the result repeats {left.name} rows ({multiplication:.2f}× its {n_left:,} "
            f"rows), so counts, sums and averages over {left.name} columns are inflated"
        )
    if card == "m:m" and spec.right_mode != "aggregate":
        ack_reasons.append(
            "keys repeat in both tables (many-to-many), so values of both tables can be "
            "double counted"
        )

    joined = joined.drop([c for c in joined.columns if c.startswith("__key") and c.endswith("__")])
    joined = joined.with_columns(
        pl.int_range(1, joined.height + 1, dtype=pl.Int64).alias(ROW_COLUMN)
    )
    internal = [
        ROW_COLUMN,
        *sorted(c for c in joined.columns if is_internal(c) and c != ROW_COLUMN),
    ]
    user = [c for c in joined.columns if not is_internal(c)]
    joined = joined.select(internal + user)
    left_infos = left.info
    added_names = {i.name: i for i in added}
    columns: list[ColumnInfo] = []
    for name in user:
        if name in left_infos:
            columns.append(_column_meta(name, left_infos[name], joined))
        elif name in added_names:
            columns.append(_column_meta(name, added_names[name], joined))
    describe = {
        "lookup": f"added the columns of {right.name} to each {left.name} row",
        "expand": f"joined every matching {right.name} row to each {left.name} row",
        "aggregate": f"added per-key summaries of {right.name} to each {left.name} row",
    }[spec.right_mode]
    keys_text = ", ".join(f"{k.left} = {k.right}" for k in spec.keys)
    issues.insert(
        0,
        ParseIssue(
            level="info",
            code="joined",
            message=(
                f"{'Time-aligned' if spec.kind == 'time_aligned' else 'Joined'} on {keys_text}"
                f"{f' (by {grain})' if grain else ''}: {describe} ({spec.how} join). "
                f"{_row_column(left)} and {_row_column(right)} give each row's origin."
            ),
        ),
    )
    issues.extend(
        ParseIssue(
            level="warning" if w.severity != "info" else "info",
            code="join_warning",
            message=w.message,
        )
        for w in warnings
    )
    sample_cols = user[:14]
    preview = LinkPreview(
        spec=spec,
        kind=spec.kind,
        n_left=n_left,
        n_right=right.frame.height,
        n_result=n_result,
        matched_left=matched_left,
        matched_right=matched_right,
        unmatched_left=unmatched_left,
        unmatched_right=unmatched_right,
        cardinality=card,
        max_right_per_key=max_right,
        duplicate_keys_left=dup_left,
        duplicate_keys_right=dup_right,
        row_multiplication=round(multiplication, 4),
        warnings=warnings,
        overlap_columns=overlap,
        columns=sample_cols,
        sample=[list(r) for r in joined.select(sample_cols).head(20).rows()],
        requires_ack=requires_ack,
        ack_reasons=ack_reasons,
    )
    return BuiltLink(
        frame=joined,
        columns=columns,
        issues=issues,
        preview=preview,
        fingerprint=_fingerprint(spec, left, right),
    )


def build_link(spec: LinkSpec, left: Table, right: Table) -> BuiltLink:
    if left.id == right.id:
        msg = "Choose two different tables."
        raise LinkError(msg)
    if spec.kind == "append":
        return _append(spec, left, right)
    if spec.rescale:
        msg = "Rescaling a column applies to appended files only."
        raise LinkError(msg)
    return _join(spec, left, right)


def preview_link(spec: LinkSpec, left: Table, right: Table) -> LinkPreview:
    return build_link(spec, left, right).preview
