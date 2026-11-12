"""Shared pieces of the discovery analyzers.

Analyzers implement the kernel's :class:`~edaforge.plugins.sdk.Analyzer` protocol, so the
planner holds the split, the ledger issues every p-value, and the Rigor Kernel grades the
evidence. This module adds what all of them need on top: the run's column roles
(:class:`AnalysisSpec`), complete-case extraction that reports what was excluded, robustness
measurements (stability under subsampling, agreement across reasonable specifications), real
progress events and template rendering.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, cast

import numpy as np
import polars as pl

from edaforge.config import Budget
from edaforge.discovery.grain import (
    ENTITY_COLUMN,
    design_effect,
    icc,
    icc_categorical,
    weighted_cluster_size,
)
from edaforge.explain.render import render_lenses
from edaforge.models import Candidate, ChartSpec, EvidenceDraft, Finding, Lenses, PatternClass
from edaforge.plugins.sdk import AnalysisData, CostEstimate, DataProfile, RunContext, Task
from edaforge.rigor.assumptions import AssumptionSpec, CheckOutcome

__all__ = [
    "AnalysisSpec",
    "BaseAnalyzer",
    "Unit",
    "binary_array",
    "complete",
    "independence_check",
    "measure_stability",
    "widen",
]

TargetKind = Literal["numeric", "binary", "categorical"]


@dataclass(frozen=True)
class AnalysisSpec:
    """How a run may use each column (from the dataset's roles and the user's choices)."""

    dataset_name: str
    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    target: str | None = None
    target_kind: TargetKind | None = None
    positive: str | None = None  # the "yes" level of a binary target
    time_column: str | None = None
    environment: str | None = None
    environment_label: str = "file"
    intent: str = "auto"
    min_support: int = 30
    min_cell: int = 10
    levels: dict[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])
    # Rows that repeat per entity (see edaforge.discovery.grain): the key's name and the columns
    # that describe the entity rather than the row. The analysis frame then has ENTITY_COLUMN.
    entity_key: str | None = None
    entity_columns: frozenset[str] = frozenset()
    # Numeric columns whose appended source files use different scales (×100, ×1,000): compared
    # between the files only and kept out of every other analysis, where they would mix units.
    across_only: tuple[str, ...] = ()
    # Near-copies (see edaforge.discovery.redundancy): column -> the column that represents its
    # cluster. Every column is still tested; findings that differ only by the copy are merged.
    aliases: dict[str, str] = field(default_factory=dict[str, str])

    def predictors(self) -> tuple[list[str], list[str]]:
        numeric = [c for c in self.numeric if c != self.target]
        categorical = [c for c in self.categorical if c not in {self.target, self.environment}]
        return numeric, categorical


@dataclass(frozen=True)
class Unit:
    """The independent units behind one test.

    ``level`` is ``"row"`` (rows are the units), ``"entity"`` (every column of the test describes
    the entity, so the test uses one row per entity) or ``"clustered"`` (rows are kept but repeat
    per entity; tests are corrected with :meth:`deff`).
    """

    level: Literal["row", "entity", "clustered"]
    entity: str | None
    n_rows: int
    n_units: int
    m_w: float = 1.0
    codes: np.ndarray[Any, np.dtype[np.int64]] | None = None
    entity_columns: frozenset[str] = frozenset()

    def side_icc(
        self, column: str | None, values: np.ndarray[Any, Any], *, categorical: bool = False
    ) -> float:
        """ICC of one side of a comparison (1 for an entity-level column)."""
        if self.level != "clustered" or self.codes is None:
            return 0.0
        if column is not None and column in self.entity_columns:
            return 1.0
        return (
            icc_categorical(values, self.codes)
            if categorical
            else icc(np.asarray(values, dtype=np.float64), self.codes)
        )

    def deff(self, icc_a: float, icc_b: float) -> float:
        if self.level != "clustered":
            return 1.0
        return design_effect(self.m_w, icc_a, icc_b)

    def facts(self, deff: float = 1.0, prefix: str = "") -> dict[str, Any]:
        return {
            f"{prefix}unit_level": self.level,
            f"{prefix}unit_entity": self.entity,
            f"{prefix}unit_rows": self.n_rows,
            f"{prefix}unit_n": self.n_units,
            f"{prefix}unit_m_w": self.m_w,
            f"{prefix}deff": deff,
            f"{prefix}n_effective": self.n_rows / deff if deff > 0 else float(self.n_rows),
        }

    def subset(self, mask: np.ndarray[Any, np.dtype[np.bool_]]) -> Unit:
        """The same unit restricted to some rows (for example one group or segment)."""
        if self.level != "clustered" or self.codes is None:
            n = int(mask.sum())
            return Unit(
                level=self.level,
                entity=self.entity,
                n_rows=n,
                n_units=n,
                entity_columns=self.entity_columns,
            )
        codes = self.codes[mask]
        return Unit(
            level="clustered",
            entity=self.entity,
            n_rows=int(codes.size),
            n_units=int(np.unique(codes).size),
            m_w=weighted_cluster_size(codes),
            codes=codes,
            entity_columns=self.entity_columns,
        )


def widen(
    estimate: float, low: float | None, high: float | None, deff: float
) -> tuple[float | None, float | None]:
    """An interval widened by ``sqrt(deff)`` around its estimate (design-effect correction)."""
    if deff <= 1.0 + 1e-12 or low is None or high is None:
        return low, high
    scale = math.sqrt(deff)
    return estimate - (estimate - low) * scale, estimate + (high - estimate) * scale


def unit_rows(
    spec: AnalysisSpec, frame: pl.DataFrame, columns: Sequence[str]
) -> tuple[pl.DataFrame, int, Unit]:
    """Complete rows for a test of ``columns`` at the right unit, and how many were left out.

    One row per entity when every column describes the entity; otherwise the rows themselves,
    with the entity codes needed to correct for repetition. Without an entity key the rows are
    the units.
    """
    cols = list(dict.fromkeys(columns))
    if spec.entity_key is None or ENTITY_COLUMN not in frame.columns:
        rows, missing = complete(frame, cols)
        return (
            rows,
            missing,
            Unit(level="row", entity=None, n_rows=rows.height, n_units=rows.height),
        )
    sub = frame.select([*cols, ENTITY_COLUMN])
    kept = sub.drop_nulls(subset=cols)
    if all(c in spec.entity_columns for c in cols):
        rows = kept.unique(subset=[ENTITY_COLUMN], keep="first", maintain_order=True)
        missing = int(sub[ENTITY_COLUMN].n_unique()) - rows.height
        unit = Unit(
            level="entity",
            entity=spec.entity_key,
            n_rows=rows.height,
            n_units=rows.height,
            entity_columns=spec.entity_columns,
        )
        return rows, missing, unit
    codes = kept[ENTITY_COLUMN].to_numpy().astype(np.int64)
    m_w = weighted_cluster_size(codes)
    n_units = int(np.unique(codes).size)
    if m_w < 1.01:
        return (
            kept,
            sub.height - kept.height,
            Unit(level="row", entity=spec.entity_key, n_rows=kept.height, n_units=kept.height),
        )
    unit = Unit(
        level="clustered",
        entity=spec.entity_key,
        n_rows=kept.height,
        n_units=n_units,
        m_w=m_w,
        codes=codes,
        entity_columns=spec.entity_columns,
    )
    return kept, sub.height - kept.height, unit


def complete(frame: pl.DataFrame, columns: Sequence[str]) -> tuple[pl.DataFrame, int]:
    """Rows where every column is present, and how many rows were excluded."""
    sub = frame.select(list(dict.fromkeys(columns)))
    kept = sub.drop_nulls()
    return kept, sub.height - kept.height


def binary_array(series: pl.Series, positive: str | None) -> np.ndarray[Any, np.dtype[np.float64]]:
    values = series.cast(pl.String)
    if positive is None:
        positive = "true"
    return (values == positive).cast(pl.Float64).to_numpy()


def independence_check(columns: Sequence[str]) -> Callable[[pl.DataFrame, Any], CheckOutcome]:
    """Lag-1 autocorrelation in file order of the analyzed numeric columns (warn at |ρ| ≥ 0.1)."""

    def check(data: pl.DataFrame, params: Any) -> CheckOutcome:
        worst = 0.0
        name = ""
        for key in columns:
            column = cast("dict[str, Any]", params).get(key) if isinstance(params, dict) else None
            if not isinstance(column, str) or column not in data.columns:
                continue
            if not data[column].dtype.is_numeric():
                continue
            v = data[column].drop_nulls().cast(pl.Float64).to_numpy()
            if v.size < 20 or float(v.std()) == 0:
                continue
            c = v - v.mean()
            rho = float(c[:-1] @ c[1:] / (c @ c))
            if abs(rho) > abs(worst):
                worst, name = rho, column
        if not name:
            return CheckOutcome(status="not_checked", detail="no numeric column with enough values")
        status: Literal["pass", "warn"] = "pass" if abs(worst) < 0.1 else "warn"
        return CheckOutcome(
            status=status,
            statistic=worst,
            detail=(
                f"lag-1 autocorrelation of {name} in file order is {worst:.3f} (warn at |ρ| ≥ 0.1)"
            ),
        )

    return check


def measure_stability(
    n: int,
    rng: np.random.Generator,
    holds: Callable[[np.ndarray[Any, np.dtype[np.int64]]], bool],
    rounds: int = 40,
    groups: np.ndarray[Any, np.dtype[np.int64]] | None = None,
) -> float:
    """Share of random half-samples on which the finding still holds (same direction, p < 0.05).

    With ``groups`` (entity codes per row), each half-sample keeps or drops whole entities.
    """
    if n < 40:
        return 0.0
    hits = 0
    half = n // 2
    if groups is not None and groups.size == n:
        uniq, inverse = np.unique(groups, return_inverse=True)
        if uniq.size < 20:
            return 0.0
        for _ in range(rounds):
            chosen = np.zeros(uniq.size, dtype=bool)
            chosen[rng.choice(uniq.size, size=uniq.size // 2, replace=False)] = True
            idx = np.nonzero(chosen[inverse])[0].astype(np.int64)
            if idx.size >= 20 and holds(idx):
                hits += 1
        return hits / rounds
    for _ in range(rounds):
        idx = rng.choice(n, size=half, replace=False)
        if holds(idx):
            hits += 1
    return hits / rounds


def stability_rng(ctx: RunContext, key: str) -> np.random.Generator:
    return ctx.ledger.rng(f"stability:{key}")


class BaseAnalyzer:
    """Common behaviour; subclasses define plan/screen/refine/confirm."""

    name: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    pattern_class: ClassVar[PatternClass] = PatternClass.SHAPE
    requires: ClassVar[frozenset[str]] = frozenset()
    assumptions: ClassVar[Sequence[AssumptionSpec]] = ()
    label: ClassVar[str] = ""
    family: ClassVar[str] = ""
    template: ClassVar[str] = ""
    method_summary: ClassVar[str] = ""

    def __init__(self, spec: AnalysisSpec) -> None:
        self.spec = spec
        self._progress_at = 0.0

    # ------------------------------------------------------------------ protocol
    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        raise NotImplementedError

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        raise NotImplementedError

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        raise NotImplementedError

    # ------------------------------------------------------------------ protocol defaults
    def estimate_cost(self, profile: DataProfile, budget: Budget) -> CostEstimate:
        return CostEstimate(seconds=1.0, memory_mb=10.0)

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        return cand

    def render(self, finding: Finding) -> Lenses:
        template = finding.facts.get("template")
        return render_lenses(
            finding, template=template if isinstance(template, str) else (self.template or None)
        )

    # ------------------------------------------------------------------ extras
    def charts(self, finding: Finding, frame: pl.DataFrame) -> list[ChartSpec]:
        return []

    def unit_rows(
        self, data: pl.DataFrame, columns: Sequence[str]
    ) -> tuple[pl.DataFrame, int, Unit]:
        return unit_rows(self.spec, data, columns)

    def begin(self, total: int) -> None:
        """Start counting the tasks of one screening pass."""
        self._done = 0
        self._total = total
        self._progress_at = 0.0

    def tick(self, ctx: RunContext) -> None:
        self._done = getattr(self, "_done", 0) + 1
        self.progress(ctx, self._done, getattr(self, "_total", self._done))

    def progress(self, ctx: RunContext, done: int, total: int) -> None:
        """Real progress: emitted after a test, at most every 10% (and at the end)."""
        if total <= 0:
            return
        share = done / total
        if done == total or share - self._progress_at >= 0.1 or done == 1:
            self._progress_at = share if done < total else 0.0
            ctx.events.emit(
                "progress",
                f"{self.label}: {done} of {total} tested",
                stage=ctx.split,
                data={
                    "analyzer": self.name,
                    "label": self.label,
                    "done": done,
                    "total": total,
                    "pass": ctx.ledger.scope or ctx.split,
                },
            )


def finite(value: float) -> float | None:
    return value if math.isfinite(value) else None
