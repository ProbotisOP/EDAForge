"""Core data contracts (section 12.1).

The specification lists these contracts in abbreviated form. Two additions protect the Rigor
Kernel and are recorded in docs/adr/0005-evidence-grading-and-confirmation-tiers.md:

* :class:`EvidenceDraft` is what an analyzer returns from ``confirm``. Only the Rigor Kernel turns
  a draft into :class:`Evidence` (which carries the grade and the causal rung), so an analyzer
  can never grade its own finding.
* Every p-value on a :class:`Candidate`, :class:`Evidence` or :class:`Confirmation` carries the
  Hypothesis Ledger IDs it came from, so the kernel can verify that it was ledgered (Law 2).

All contracts are immutable, forbid unknown fields and reject NaN or infinite floats.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

__all__ = [
    "PATTERN_CLASS_INFO",
    "AnalyzerRef",
    "AssumptionCheck",
    "Candidate",
    "ChartSpec",
    "ColumnRef",
    "Condition",
    "Confirmation",
    "Contract",
    "DataInput",
    "Effect",
    "Evidence",
    "EvidenceDraft",
    "Finding",
    "FindingKind",
    "Grade",
    "LedgerEntry",
    "LensText",
    "Lenses",
    "PatternClass",
    "Predicate",
    "Probability",
    "Provenance",
    "RefutationResult",
    "Relation",
    "ResamplingRecord",
    "RunManifest",
    "Rung",
    "Score",
    "SplitName",
    "SplitRecord",
]


class Contract(BaseModel):
    """Base class for engine contracts: immutable, strict, finite floats only."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        validate_default=True,
        str_strip_whitespace=False,
    )


Probability = Annotated[float, Field(ge=0.0, le=1.0)]
Grade = Literal["A", "B", "C", "D", "E"]
Rung = Literal["R0", "R1", "R1+", "R2", "R3"]
SplitName = Literal["exploration", "confirmation", "cross_fit", "full"]

GRADE_ORDER: tuple[Grade, ...] = ("A", "B", "C", "D", "E")
RUNG_ORDER: tuple[Rung, ...] = ("R0", "R1", "R1+", "R2", "R3")


class PatternClass(StrEnum):
    """The twelve places patterns hide (section 4)."""

    SHAPE = "shape"
    THIRD_VARIABLE = "third_variable"
    SUBGROUP = "subgroup"
    COMBINATION = "combination"
    TIME = "time"
    EXTREMES = "extremes"
    UNMEASURED = "unmeasured"
    GEOMETRY = "geometry"
    RULES_AND_LAWS = "rules_and_laws"
    ERRORS = "errors"
    ACROSS_FILES = "across_files"
    SPACE_TEXT_NETWORKS = "space_text_networks"


PATTERN_CLASS_INFO: dict[PatternClass, tuple[int, str]] = {
    PatternClass.SHAPE: (1, "In the shape"),
    PatternClass.THIRD_VARIABLE: (2, "Behind a third variable"),
    PatternClass.SUBGROUP: (3, "Inside a subgroup"),
    PatternClass.COMBINATION: (4, "In combinations"),
    PatternClass.TIME: (5, "In time"),
    PatternClass.EXTREMES: (6, "In the extremes"),
    PatternClass.UNMEASURED: (7, "In something unmeasured"),
    PatternClass.GEOMETRY: (8, "In the geometry"),
    PatternClass.RULES_AND_LAWS: (9, "In rules and laws"),
    PatternClass.ERRORS: (10, "In the errors"),
    PatternClass.ACROSS_FILES: (11, "Across files"),
    PatternClass.SPACE_TEXT_NETWORKS: (12, "In space, text and networks"),
}


class FindingKind(StrEnum):
    """Finding types (section 12.1)."""

    ASSOCIATION = "association"
    NONLINEAR_RELATIONSHIP = "nonlinear_relationship"
    EXPLAINED_AWAY = "explained_away"
    CONDITIONAL_DEPENDENCE = "conditional_dependence"
    CAUSAL_EDGE = "causal_edge"
    CAUSAL_EFFECT = "causal_effect"
    MEDIATION = "mediation"
    STORYLINE = "storyline"
    SUBGROUP = "subgroup"
    EXCEPTIONAL_MODEL = "exceptional_model"
    REVERSAL = "reversal"
    SELECTION_BIAS_WARNING = "selection_bias_warning"
    INTERACTION = "interaction"
    SYNERGY = "synergy"
    LATENT_FACTOR = "latent_factor"
    CLUSTER = "cluster"
    TOPOLOGICAL_FEATURE = "topological_feature"
    CHANGE_POINT = "change_point"
    REGIME = "regime"
    LEAD_LAG = "lead_lag"
    MOTIF = "motif"
    DISCORD = "discord"
    PRECURSOR = "precursor"
    PERIODICITY = "periodicity"
    EQUATION = "equation"
    THRESHOLD = "threshold"
    TAIL_DEPENDENCE = "tail_dependence"
    SPATIAL_CLUSTER = "spatial_cluster"
    TOPIC_DRIVER = "topic_driver"
    COMMUNITY = "community"
    ANOMALY = "anomaly"
    ROOT_CAUSE = "root_cause"
    DISTRIBUTION_SHIFT = "distribution_shift"
    MECHANISM_CHANGE = "mechanism_change"
    INVARIANT_PREDICTOR = "invariant_predictor"
    DATA_QUALITY_ISSUE = "data_quality_issue"
    CROSS_FILE_CONTRADICTION = "cross_file_contradiction"
    JOIN_RELATIONSHIP = "join_relationship"
    STRUCTURAL_FACT = "structural_fact"
    NULL_RESULT = "null_result"


class ColumnRef(Contract):
    column: str
    table: str | None = None

    def label(self) -> str:
        return self.column if self.table is None else f"{self.table}.{self.column}"


Scalar = str | int | float | bool | None


class Condition(Contract):
    column: ColumnRef
    op: Literal["==", "!=", "<", "<=", ">", ">=", "in", "not_in", "is_null", "not_null"]
    value: Scalar | list[Scalar] = None


class Predicate(Contract):
    """A conjunction of conditions that defines a subgroup."""

    conditions: list[Condition]
    text: str


class Effect(Contract):
    measure: str  # "risk_diff", "dcor", "ate", "slope_diff", "o_information", "cohen_d", ...
    estimate: float
    ci_low: float | None = None
    ci_high: float | None = None
    ci_level: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.95
    units: str | None = None
    sesoi: Annotated[float, Field(ge=0.0)] | None = None
    ci_method: str | None = None
    split: SplitName | None = None  # which data the estimate was computed on

    @model_validator(mode="after")
    def _interval_is_ordered(self) -> Effect:
        if self.ci_low is not None and self.ci_high is not None and self.ci_low > self.ci_high:
            msg = f"ci_low ({self.ci_low}) exceeds ci_high ({self.ci_high})"
            raise ValueError(msg)
        return self


class AssumptionCheck(Contract):
    """Outcome of one executable assumption check (section 8.6).

    ``untestable`` marks assumptions that no check can settle (for example, no unmeasured
    confounding); they are shown as caveats and addressed by sensitivity analysis.
    ``not_checked`` means a check exists but was skipped (budget, missing data).
    """

    name: str
    description: str
    status: Literal["pass", "warn", "fail", "not_checked", "untestable"]
    severity: Literal["minor", "major", "critical"]
    statistic: float | None = None
    p_value: Probability | None = None
    detail: str = ""
    action: Literal["none", "fallback", "downgrade", "caveat"] = "none"
    fallback_to: str | None = None


class RefutationResult(Contract):
    name: str
    passed: bool
    original_estimate: float | None = None
    refuted_estimate: float | None = None
    p_value: Probability | None = None
    detail: str = ""


class Confirmation(Contract):
    status: Literal["confirmed", "not_confirmed", "pending", "not_applicable"]
    method: Literal["sealed_holdout", "cross_fit", "reusable_holdout", "none"]
    p_value: Probability | None = None
    q_value: Probability | None = None
    hypothesis_ids: list[str] = []
    n: int | None = None
    blind_violation: bool = False
    aggregation: str | None = None  # e.g. "mmb_quantile(gamma=0.5)" for cross-fitting


class EvidenceDraft(Contract):
    """Evidence as produced by an analyzer, before the Rigor Kernel grades it."""

    test: str
    statistic: float | None = None
    p_value: Probability | None = None  # discovery (exploration) test
    e_value: Annotated[float, Field(ge=0.0)] | None = None
    hypothesis_ids: list[str]
    n: int
    confirmation: Confirmation
    effect: Effect | None = None  # estimated on the confirmation data where it exists
    stability: Probability | None = None
    specs_consistent: int | None = None
    specs_total: int | None = None
    sensitivity: dict[str, float] = {}
    assumptions: list[AssumptionCheck] = []
    refutations: list[RefutationResult] = []
    claimed_rung: Rung = "R1"
    rung_support: dict[str, JsonValue] = {}
    facts: dict[str, JsonValue] = {}  # values computed on the confirmation data
    caveats: list[str] = []


class Evidence(Contract):
    test: str
    statistic: float | None = None
    p_value: Probability | None = None  # discovery (exploration) test
    e_value: Annotated[float, Field(ge=0.0)] | None = None
    q_value: Probability | None = None  # FDR-adjusted discovery p-value
    n: int
    confirmation: Confirmation
    stability: Probability | None = None  # 0..1
    specs_consistent: int | None = None  # multiverse
    specs_total: int | None = None
    sensitivity: dict[str, float] = {}  # {"robustness_value": 0.18, "e_value": 2.1}
    assumptions: list[AssumptionCheck] = []
    refutations: list[RefutationResult] = []
    grade: Grade
    rung: Rung
    hypothesis_ids: list[str] = []
    grade_reasons: list[str] = []
    rung_reasons: list[str] = []
    exploratory: bool = False


class LensText(Contract):
    headline: str
    markdown: str


class Lenses(Contract):
    plain: LensText
    analyst: LensText
    scientist: LensText


class Score(Contract):
    value: float
    components: dict[str, float] = {}
    partial: bool = True  # True while some components (surprise, novelty, ...) are not computed


class ChartSpec(Contract):
    kind: Literal["vega-lite", "plotly", "cytoscape"]
    title: str
    alt_text: str
    spec: dict[str, JsonValue]


class Relation(Contract):
    type: Literal["supports", "contradicts", "mediates", "duplicates"]
    target: str


class Provenance(Contract):
    analyzer: str
    analyzer_version: str
    params: dict[str, JsonValue]
    seed: int
    data_hash: str
    run_id: str
    manifest_hash: str
    edaforge_version: str
    hypothesis_ids: list[str]
    code: str  # a command or snippet that reproduces the finding


class Candidate(Contract):
    """A frozen candidate handed from Screen/Refine to Confirm."""

    key: str  # stable identity across splits and folds
    analyzer: str
    kind: FindingKind
    pattern_class: PatternClass
    title: str
    variables: list[ColumnRef]
    subgroup: Predicate | None = None
    hypothesis_id: str
    test: str
    statistic: float | None = None
    p_value: Probability | None = None
    effect: Effect | None = None
    params: dict[str, JsonValue] = {}
    facts: dict[str, JsonValue] = {}
    claimed_rung: Rung = "R1"


class Finding(Contract):
    id: Annotated[str, Field(pattern=r"^F-\d{6}$")]  # "F-000042"
    kind: FindingKind
    pattern_class: PatternClass
    title_plain: str
    lenses: Lenses
    variables: list[ColumnRef]
    subgroup: Predicate | None = None
    effect: Effect | None = None
    secondary_effects: list[Effect] = []
    facts: dict[str, JsonValue] = {}  # engine-computed values that lens text may quote
    evidence: Evidence
    interestingness: Score
    visuals: list[ChartSpec] = []
    caveats: list[str] = []
    actions: list[str] = []
    related: list[Relation] = []
    provenance: Provenance


class LedgerEntry(Contract):
    hypothesis_id: Annotated[str, Field(pattern=r"^H-\d{6}$")]
    hypothesis: str
    family_path: list[str]  # ["L8", "subgroups", "target=churn"]
    analyzer: str
    analyzer_version: str
    test: str
    status: Literal["registered", "tested", "untestable"]
    untestable_reason: str | None = None
    statistic: float | None
    p_value: Probability | None
    e_value: Annotated[float, Field(ge=0.0)] | None
    split: SplitName
    params: dict[str, JsonValue] = {}
    parent_id: str | None = None
    n: int | None = None
    n_resamples: int | None = None
    stopped_early: bool | None = None
    seed: int | None = None
    frozen_at: datetime | None  # candidate-list freeze, for blind analysis
    blind_violation: bool = False
    created_at: datetime
    tested_at: datetime | None = None


class ResamplingRecord(Contract):
    """Audit record for a bootstrap or other resampling obtained through the ledger."""

    purpose: str
    analyzer: str
    method: str
    split: SplitName
    n_resamples: int
    seed: int
    created_at: datetime


class DataInput(Contract):
    name: str
    sha256: str
    n_rows: int
    n_cols: int
    kind: Literal["file", "frame"]
    path: str | None = None


class AnalyzerRef(Contract):
    name: str
    version: str
    distribution: str | None = None


class SplitRecord(Contract):
    mode: Literal["holdout", "cross_fit", "small_sample"]
    n_total: int
    n_exploration: int
    n_confirmation: int
    n_embargo: int = 0
    seal_hash: str | None = None
    n_splits: int | None = None
    strategy: str = ""


class RunManifest(Contract):
    run_id: str
    edaforge_version: str
    python_version: str
    platform: str
    seed: int
    config_hash: str
    inputs: list[DataInput]
    libraries: dict[str, str]
    analyzers: list[AnalyzerRef]
    split: SplitRecord | None = None
    created_at: datetime  # wall clock; never part of run_id or of findings JSON
