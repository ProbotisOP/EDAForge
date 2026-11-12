"""Run configuration (``edaforge.yaml``, section 20).

Defaults follow section 20. Settings that the specification leaves open are marked
"engine default" below and justified in docs/adr/0005-evidence-grading-and-confirmation-tiers.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from edaforge.canonical import content_hash
from edaforge.errors import ConfigError

__all__ = [
    "Budget",
    "ComputeConfig",
    "EDAForgeConfig",
    "ExplainConfig",
    "InterestingnessWeights",
    "PrivacyConfig",
    "RigorConfig",
    "budget_settings",
    "config_hash",
    "load_config",
]

Budget = Literal["quick", "deep", "exhaustive"]
Mode = Literal["auto", "drivers", "change", "anomaly", "compare", "hypothesis", "health", "monitor"]
Fraction = Annotated[float, Field(gt=0.0, lt=1.0)]


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class RigorConfig(_Config):
    confirmation_fraction: Fraction = 0.30
    fdr_q_confirmed: Fraction = 0.05
    fdr_q_suggestive: Fraction = 0.10
    online_fdr: Literal["lord_pp", "saffron", "addis"] = "saffron"
    stability_resamples: Annotated[int, Field(ge=10)] = 100
    nullverse_replicates: Annotated[int, Field(ge=0)] = 20
    injection_recovery: bool = True
    min_subgroup_support: Annotated[int, Field(ge=1)] = 30
    min_disclosed_cell: Annotated[int, Field(ge=1)] = 10
    # Split regimes (section 8.1).
    holdout_min_n: Annotated[int, Field(ge=2)] = 2000
    cross_fit_min_n: Annotated[int, Field(ge=2)] = 300
    # Engine defaults (not fixed by the specification):
    cross_fit_splits: Annotated[int, Field(ge=2)] = 10  # random half-splits for multi-splitting
    cross_fit_gamma: Fraction = 0.5  # Meinshausen-Meier-Buhlmann quantile
    screen_q: Fraction = 0.20  # exploration BH level for promotion to Confirm
    max_confirmations: Annotated[int, Field(ge=1)] = 500
    permutation_h: Annotated[int, Field(ge=1)] = 10  # Besag-Clifford exceedances before stopping
    ci_level: Fraction = 0.95
    robustness_value_min: Fraction = 0.10  # below this, causal claims are capped at grade C
    embargo: Annotated[int, Field(ge=0)] = 0  # rows dropped between time-ordered splits

    @model_validator(mode="after")
    def _levels_are_consistent(self) -> RigorConfig:
        if self.fdr_q_suggestive < self.fdr_q_confirmed:
            msg = "fdr_q_suggestive must be >= fdr_q_confirmed"
            raise ValueError(msg)
        if self.cross_fit_min_n >= self.holdout_min_n:
            msg = "cross_fit_min_n must be smaller than holdout_min_n"
            raise ValueError(msg)
        return self


class InterestingnessWeights(_Config):
    """Weights of the interestingness score (section 9). Never affect the evidence grade."""

    effect: float = 1.0  # w1 * g(effect / SESOI)
    grade: float = 1.0  # w2
    surprise: float = 0.5  # w3
    coverage: float = 0.25  # w4
    actionability: float = 0.5  # w5
    novelty: float = 0.25  # w6
    redundancy: float = 1.0  # w7 (subtracted)


class PrivacyConfig(_Config):
    llm: Literal["off", "local", "remote"] = "off"
    send_raw_rows: bool = False
    pii_detection: bool = True

    @field_validator("llm", mode="before")
    @classmethod
    def _yaml_off_is_false(cls, value: object) -> object:
        # YAML 1.1 parses an unquoted `off` as boolean False.
        if value is False:
            return "off"
        return value


class ExplainConfig(_Config):
    default_lens: Literal["plain", "analyst", "scientist"] = "plain"
    reading_grade_max: Annotated[float, Field(gt=0)] = 8.0
    locale: str = "en"


class ComputeConfig(_Config):
    backend: Literal["local", "ray"] = "local"
    max_memory_fraction: Fraction = 0.70
    seed: Annotated[int, Field(ge=0)] = 20261110
    n_jobs: Annotated[int, Field(ge=1)] = 1


DEFAULT_SESOI: dict[str, float] = {
    "r": 0.10,
    "cohen_d": 0.20,
    "odds_ratio": 1.2,
    "risk_ratio": 1.10,
    "cramers_v": 0.10,
}


class EDAForgeConfig(_Config):
    project: str | None = None
    budget: Budget = "deep"
    mode: Mode = "auto"
    targets: list[str] = []
    controllable: list[str] = []
    environments_from: str | None = "__source__"
    time_tiers: list[list[str]] = []
    forbidden_edges: list[tuple[str, str]] = []
    required_edges: list[tuple[str, str]] = []
    rigor: RigorConfig = RigorConfig()
    sesoi: dict[str, float] = DEFAULT_SESOI
    privacy: PrivacyConfig = PrivacyConfig()
    explain: ExplainConfig = ExplainConfig()
    compute: ComputeConfig = ComputeConfig()
    interestingness: InterestingnessWeights = InterestingnessWeights()
    plugins: list[str] = []  # distribution names, enabled only after license review

    @field_validator("sesoi", mode="before")
    @classmethod
    def _merge_sesoi_defaults(cls, value: object) -> object:
        if isinstance(value, dict):
            merged: dict[str, object] = dict(DEFAULT_SESOI)
            merged.update(value)  # pyright: ignore[reportUnknownArgumentType]
            return merged
        return value


class BudgetSettings(_Config):
    permutation_max: int  # n in Besag-Clifford: at most n - 1 null draws, minimum p = 1/n
    bootstrap_resamples: int


_BUDGETS: dict[Budget, BudgetSettings] = {
    "quick": BudgetSettings(permutation_max=1_000, bootstrap_resamples=1_000),
    "deep": BudgetSettings(permutation_max=10_000, bootstrap_resamples=2_000),
    "exhaustive": BudgetSettings(permutation_max=100_000, bootstrap_resamples=10_000),
}


def budget_settings(budget: Budget) -> BudgetSettings:
    return _BUDGETS[budget]


def load_config(path: Path) -> EDAForgeConfig:
    """Load and validate a ``edaforge.yaml`` file."""
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        msg = f"{path}: invalid YAML: {exc}"
        raise ConfigError(msg) from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        msg = f"{path}: top level must be a mapping"
        raise ConfigError(msg)
    try:
        return EDAForgeConfig.model_validate(raw)
    except ValidationError as exc:
        msg = f"{path}: {exc}"
        raise ConfigError(msg) from exc


def config_hash(config: EDAForgeConfig) -> str:
    return content_hash(config.model_dump(mode="json"))
