"""Unit of analysis: rows that repeat per entity (PROJECT_PROMPT.md section 6, "Data handling").

A table often holds several rows per entity: orders joined to their customers, visits per patient,
readings per sensor. Columns copied from the entity (a customer's region, plan, age) then repeat
on every row of that entity, and treating those rows as independent observations inflates the
evidence: 7,000 order rows are not 7,000 independent customers.

:func:`detect_grain` finds such structure from the data itself, so it works for joined tables and
for files that arrive already denormalized. An identifier column qualifies as an *entity key*
when a substantial share of rows repeats a value; the *entity-level columns* are those that are
constant within every entity that has two or more values (and enough such entities to make the
check meaningful).

The analyzers then use one rule (see :class:`edaforge.discovery.base.Unit`):

* every column of a test describes the entity -> the test uses one row per entity (exact);
* otherwise rows are kept and the test is corrected with the design effect
  ``deff = 1 + (m_w - 1) * icc_a * icc_b`` (Kish 1965; Donner & Klar 2000), where ``m_w`` is the
  size-weighted mean number of rows per entity and ``icc`` the intra-entity correlation of each
  side of the comparison (1 for an entity-level column). Chi-square-type statistics are divided by
  ``deff`` and z-type statistics by its square root (a first-order Rao & Scott 1981 correction);
  intervals are widened by ``sqrt(deff)``.

The confirmation split holds out whole entities, so an entity never informs both the search and
the check.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray
from scipy import stats

from edaforge.ingest import ColumnInfo, is_internal

__all__ = [
    "ENTITY_COLUMN",
    "Grain",
    "deflate_chi2",
    "deflate_f",
    "deflate_z",
    "design_effect",
    "detect_grain",
    "entity_codes",
    "icc",
    "icc_categorical",
    "weighted_cluster_size",
]

ENTITY_COLUMN = "__entity__"
_MIN_REPEAT_SHARE = 0.2  # rows in entities with 2+ rows, as a share of all keyed rows
_MIN_ENTITIES = 20
_MIN_EVIDENCE = 10  # entities with 2+ non-missing values needed to call a column entity-level

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class Grain:
    """Rows of the table repeat per value of ``key``."""

    key: str
    n_rows: int  # rows with a key value
    n_entities: int
    mean_rows: float  # rows per entity
    columns: frozenset[str]  # columns constant within each entity (entity-level)

    def describe(self) -> str:
        return (
            f"{self.n_rows:,} rows describe {self.n_entities:,} distinct {self.key} values "
            f"({self.mean_rows:.1f} rows each on average)"
        )


def _candidate_keys(frame: pl.DataFrame, infos: dict[str, ColumnInfo]) -> list[str]:
    keys: list[str] = []
    for name, info in infos.items():
        if name not in frame.columns or info.role != "identifier":
            continue
        keys.append(name)
    # Non-personal keys first; personal-data identifiers (an e-mail) are a last resort.
    return sorted(keys, key=lambda k: (infos[k].pii is not None, k))


def detect_grain(
    frame: pl.DataFrame, columns: list[ColumnInfo], *, extra: tuple[str, ...] = ()
) -> Grain | None:
    """The entity key whose repetition matters most, with its entity-level columns, or ``None``.

    ``extra`` names internal columns (such as the source-file column) to test as well.
    """
    infos = {c.name: c for c in columns}
    analyzable = [
        c.name
        for c in columns
        if c.name in frame.columns and c.role not in {"empty", "text"} and not is_internal(c.name)
    ]
    analyzable += [e for e in extra if e in frame.columns]
    best: tuple[tuple[bool, bool, int, float], Grain] | None = None
    for key in _candidate_keys(frame, infos):
        keyed = frame.filter(pl.col(key).is_not_null())
        if keyed.height < 2 * _MIN_ENTITIES:
            continue
        sizes = keyed.group_by(key).len()["len"]
        n_entities = sizes.len()
        repeated_rows = int(sizes.filter(sizes >= 2).sum())
        if n_entities < _MIN_ENTITIES or repeated_rows < _MIN_REPEAT_SHARE * keyed.height:
            continue
        others = [c for c in analyzable if c != key]
        if not others:
            continue
        agg = keyed.group_by(key).agg(
            *[pl.col(c).drop_nulls().n_unique().alias(f"u:{c}") for c in others],
            *[pl.col(c).count().alias(f"n:{c}") for c in others],
        )
        dependent: list[str] = []
        for c in others:
            multi = agg.filter(pl.col(f"n:{c}") >= 2)
            if multi.height >= _MIN_EVIDENCE and int(multi[f"u:{c}"].max() or 0) <= 1:  # pyright: ignore[reportArgumentType]
                dependent.append(c)
        grain = Grain(
            key=key,
            n_rows=keyed.height,
            n_entities=n_entities,
            mean_rows=keyed.height / n_entities,
            columns=frozenset(dependent),
        )
        # A key that carries entity-level columns beats one that does not; among those a
        # non-personal key (customer_id) always beats a personal one (an e-mail address that
        # identifies the same customers), so personal data never names the unit of analysis
        # when an alternative exists.
        score = (bool(dependent), infos[key].pii is None, len(dependent), grain.mean_rows)
        if best is None or score > best[0]:
            best = (score, grain)
    return None if best is None else best[1]


def entity_codes(series: pl.Series) -> pl.Series:
    """Integer entity codes; rows without a key each form their own entity."""
    codes = series.cast(pl.String).rank("dense").cast(pl.Int64)
    n_known = int(codes.max() or 0)  # pyright: ignore[reportArgumentType]
    missing = codes.is_null()
    filler = pl.Series(np.arange(n_known + 1, n_known + 1 + series.len(), dtype=np.int64))
    return (
        pl.select(pl.when(missing).then(filler).otherwise(codes)).to_series().alias(ENTITY_COLUMN)
        - 1
    )


def _dense(codes: NDArray[Any]) -> tuple[IntArray, int]:
    _, inverse = np.unique(codes, return_inverse=True)
    inv = inverse.astype(np.int64).ravel()
    return inv, int(inv.max()) + 1 if inv.size else 0


def weighted_cluster_size(codes: NDArray[Any]) -> float:
    """Size-weighted mean rows per entity, ``sum(m_g^2) / N`` (1.0 when no entity repeats)."""
    if codes.size == 0:
        return 1.0
    inv, k = _dense(codes)
    sizes = np.bincount(inv, minlength=k).astype(np.float64)
    return float((sizes**2).sum() / sizes.sum())


def icc(values: FloatArray, codes: NDArray[Any]) -> float:
    """One-way ANOVA estimate of the intra-entity correlation, clipped to [0, 1].

    Unbalanced-design estimator ``(MSB - MSW) / (MSB + (n0 - 1) MSW)`` with
    ``n0 = (N - sum(n_g^2)/N) / (G - 1)``. Returns 0 when no entity has two rows.
    """
    v = np.asarray(values, dtype=np.float64)
    n = v.size
    if n < 3:
        return 0.0
    inv, g = _dense(codes)
    if g < 2 or g == n:
        return 0.0
    sizes = np.bincount(inv, minlength=g).astype(np.float64)
    sums = np.bincount(inv, weights=v, minlength=g)
    means = sums / sizes
    grand = float(v.mean())
    ssb = float((sizes * (means - grand) ** 2).sum())
    ssw = float(((v - means[inv]) ** 2).sum())
    msb = ssb / (g - 1)
    msw = ssw / (n - g)
    n0 = (n - float((sizes**2).sum()) / n) / (g - 1)
    if msw <= 1e-15 * max(msb, 1e-300):
        return 1.0 if msb > 0 else 0.0
    denominator = msb + (n0 - 1) * msw
    if denominator <= 0:
        return 0.0
    return float(min(1.0, max(0.0, (msb - msw) / denominator)))


def icc_categorical(labels: NDArray[Any], codes: NDArray[Any]) -> float:
    """Variance-weighted mean ICC of the level indicators of a categorical column."""
    lab, k = _dense(np.asarray(labels))
    if k < 2:
        return 0.0
    total = 0.0
    weight = 0.0
    for level in range(k):
        indicator = (lab == level).astype(np.float64)
        p = float(indicator.mean())
        w = p * (1 - p)
        if p < 0.01 or w == 0:
            continue
        total += w * icc(indicator, codes)
        weight += w
    return total / weight if weight > 0 else 0.0


def design_effect(m_w: float, icc_a: float, icc_b: float) -> float:
    """Variance inflation of an association test between two sides with the given ICCs."""
    if not (math.isfinite(m_w) and math.isfinite(icc_a) and math.isfinite(icc_b)):
        return 1.0
    return max(1.0, 1.0 + (m_w - 1.0) * max(0.0, icc_a) * max(0.0, icc_b))


def _clamp(p: float) -> float:
    return min(1.0, max(float(p), 1e-300))


def deflate_z(p: float, deff: float, *, two_sided: bool = True) -> float:
    """A z-type p-value as it would be with the statistic divided by ``sqrt(deff)``."""
    if deff <= 1.0 + 1e-12 or not math.isfinite(p):
        return p
    p = _clamp(p)
    scale = math.sqrt(deff)
    if two_sided:
        z = float(stats.norm.isf(p / 2))
        return float(min(1.0, 2 * stats.norm.sf(z / scale)))
    z = float(stats.norm.isf(p))
    return float(stats.norm.sf(z / scale))


def deflate_chi2(statistic: float, df: float, deff: float) -> tuple[float, float]:
    """(statistic / deff, its chi-square p-value)."""
    adjusted = statistic / max(deff, 1.0)
    return adjusted, float(stats.chi2.sf(adjusted, df))


def deflate_f(statistic: float, df1: float, df2: float, deff: float) -> tuple[float, float]:
    adjusted = statistic / max(deff, 1.0)
    return adjusted, float(stats.f.sf(adjusted, df1, df2))
