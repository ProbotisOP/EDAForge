"""The analyzer plugin SDK (section 12.2).

Differences from the abbreviated protocol in the specification, recorded in
docs/adr/0007-plugin-sdk-and-registry.md:

* ``confirm`` returns an :class:`~edaforge.models.EvidenceDraft`; the Rigor Kernel grades it.
* ``plan`` receives :class:`AnalysisData` (one analysis frame plus its profile). The full
  ``DataUniverse`` arrives with the Link layer in Phase 2.
* Frames are Polars DataFrames. ``screen`` and ``refine`` only ever see exploration rows and
  ``confirm`` only sees sealed rows; the planner, not the analyzer, holds the split.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

import polars as pl
from pydantic import JsonValue

from edaforge.config import Budget, BudgetSettings, EDAForgeConfig
from edaforge.models import (
    Candidate,
    Contract,
    EvidenceDraft,
    Finding,
    Lenses,
    PatternClass,
    SplitName,
)
from edaforge.rigor.assumptions import AssumptionSpec

if TYPE_CHECKING:
    from edaforge.rigor.ledger import LedgerView
    from edaforge.runtime.events import EventBus

__all__ = [
    "AnalysisData",
    "Analyzer",
    "CostEstimate",
    "DataProfile",
    "RunContext",
    "Task",
    "capabilities_met",
    "profile_frame",
]


class Task(Contract):
    key: str
    params: dict[str, JsonValue] = {}


class CostEstimate(Contract):
    seconds: float
    memory_mb: float
    note: str = ""


class DataProfile(Contract):
    n_rows: int
    n_cols: int
    numeric: list[str]
    categorical: list[str]
    environment_column: str | None = None
    environments: list[str] = []
    targets: list[str] = []
    time_column: str | None = None
    # Rows that repeat per entity: splits keep each entity on one side (never on both).
    group_column: str | None = None


@dataclass(frozen=True)
class AnalysisData:
    """One analysis frame with the metadata analyzers need to plan."""

    frame: pl.DataFrame
    name: str
    data_hash: str
    profile: DataProfile


_ID_LIKE = re.compile(r"(^|_)(id|uuid|key)$", re.IGNORECASE)


def profile_frame(
    frame: pl.DataFrame,
    *,
    environment_column: str | None,
    targets: Sequence[str] = (),
    time_column: str | None = None,
    group_column: str | None = None,
) -> DataProfile:
    """A minimal profile for planning (the deep profile is the L3 layer, Phase 1)."""
    numeric: list[str] = []
    categorical: list[str] = []
    for name, dtype in frame.schema.items():
        if name in (environment_column, group_column) or _ID_LIKE.search(name):
            continue
        if dtype.is_numeric() and dtype != pl.Boolean:
            numeric.append(name)
        elif isinstance(dtype, pl.String | pl.Categorical | pl.Boolean | pl.Enum):
            categorical.append(name)
    environments: list[str] = []
    if environment_column is not None and environment_column in frame.columns:
        environments = sorted(
            str(v) for v in frame[environment_column].drop_nulls().unique().to_list()
        )
    return DataProfile(
        n_rows=frame.height,
        n_cols=frame.width,
        numeric=numeric,
        categorical=categorical,
        environment_column=environment_column if environments else None,
        environments=environments,
        targets=[t for t in targets if t in frame.columns],
        time_column=time_column if time_column in frame.columns else None,
        group_column=group_column if group_column in frame.columns else None,
    )


_CAPABILITY = re.compile(r"^(?P<name>[a-z_]+)(?:>=(?P<k>\d+))?$")


def capabilities_met(requires: frozenset[str], profile: DataProfile) -> tuple[bool, list[str]]:
    """Check requirements such as ``"numeric>=2"``, ``"environment>=2"``, ``"target"``."""
    counts = {
        "rows": profile.n_rows,
        "numeric": len(profile.numeric),
        "categorical": len(profile.categorical),
        "environment": len(profile.environments),
        "target": len(profile.targets),
        "time_index": 1 if profile.time_column else 0,
    }
    missing: list[str] = []
    for requirement in sorted(requires):
        match = _CAPABILITY.match(requirement)
        if match is None or match["name"] not in counts:
            missing.append(f"unknown capability {requirement!r}")
            continue
        needed = int(match["k"]) if match["k"] else 1
        if counts[match["name"]] < needed:
            missing.append(f"{requirement} (have {counts[match['name']]})")
    return (not missing), missing


@dataclass
class RunContext:
    """What an analyzer may use during one call. ``ledger`` is bound to analyzer and split."""

    run_id: str
    config: EDAForgeConfig
    budget: Budget
    budget_settings: BudgetSettings
    ledger: LedgerView
    events: EventBus
    split: SplitName
    data_hash: str
    profile: DataProfile
    warnings: list[str] = field(default_factory=list[str])

    def warn(self, code: str, message: str) -> None:
        self.warnings.append(f"{code}: {message}")
        self.events.emit(
            "warning",
            message,
            stage=self.split,
            data={"code": code, "analyzer": self.ledger.analyzer},
        )


@runtime_checkable
class Analyzer(Protocol):
    name: ClassVar[str]  # "reveal.subgroups.emm"
    version: ClassVar[str]
    pattern_class: ClassVar[PatternClass]
    requires: ClassVar[frozenset[str]]  # e.g. {"target", "numeric>=2"} or {"time_index"}
    assumptions: ClassVar[Sequence[AssumptionSpec]]  # executable checks, plus fallbacks

    def estimate_cost(self, profile: DataProfile, budget: Budget) -> CostEstimate: ...
    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]: ...
    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]: ...
    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate: ...
    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft: ...
    def render(self, finding: Finding) -> Lenses: ...  # templates per lens
