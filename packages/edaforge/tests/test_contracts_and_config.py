"""Contracts and configuration (sections 12.1 and 20)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from edaforge.config import EDAForgeConfig, RigorConfig, budget_settings, config_hash, load_config
from edaforge.errors import ConfigError
from edaforge.models import PATTERN_CLASS_INFO, Effect, FindingKind, LedgerEntry, PatternClass

SECTION_20_YAML = """
project: retail-2026
budget: deep                 # quick | deep | exhaustive
mode: auto                   # auto | drivers | change | anomaly | compare | hypothesis | health
targets: [churn]
controllable: [discount_pct, delivery_sla_days, ad_spend]
environments_from: __source__          # file/site/period column, used for invariance and CD-NOD
time_tiers:                  # earlier tiers cannot be caused by later tiers
  - [region, signup_channel]
  - [plan, tenure_months]
  - [discount_pct, delivery_delay_days]
  - [churn]
forbidden_edges: [[churn, signup_channel]]
rigor:
  confirmation_fraction: 0.30
  fdr_q_confirmed: 0.05
  fdr_q_suggestive: 0.10
  online_fdr: saffron        # lord_pp | saffron | addis
  stability_resamples: 100
  nullverse_replicates: 20
  injection_recovery: true
  min_subgroup_support: 30
  min_disclosed_cell: 10
sesoi: {r: 0.10, cohen_d: 0.20, odds_ratio: 1.2, risk_ratio: 1.10, cramers_v: 0.10}
privacy:
  llm: off                   # off | local | remote
  send_raw_rows: false
  pii_detection: true
explain:
  default_lens: plain        # plain | analyst | scientist
  reading_grade_max: 8
  locale: en
compute:
  backend: local             # local | ray
  max_memory_fraction: 0.70
  seed: 20261110
plugins: []                  # e.g. [edaforge-plugin-tigramite] after license review
"""


def test_section_20_reference_config_loads(tmp_path: Path) -> None:
    path = tmp_path / "edaforge.yaml"
    path.write_text(SECTION_20_YAML, encoding="utf-8")
    config = load_config(path)
    assert config.privacy.llm == "off"  # YAML 1.1 reads `off` as False
    assert config.forbidden_edges == [("churn", "signup_channel")]
    assert config.rigor.confirmation_fraction == 0.30
    assert config.compute.seed == 20261110


def test_defaults_match_section_20() -> None:
    config = EDAForgeConfig()
    assert (config.rigor.fdr_q_confirmed, config.rigor.fdr_q_suggestive) == (0.05, 0.10)
    assert config.sesoi == {
        "r": 0.1,
        "cohen_d": 0.2,
        "odds_ratio": 1.2,
        "risk_ratio": 1.1,
        "cramers_v": 0.1,
    }
    assert config.privacy.llm == "off"
    assert not config.privacy.send_raw_rows
    assert config.plugins == []


def test_sesoi_overrides_merge_with_defaults() -> None:
    config = EDAForgeConfig.model_validate({"sesoi": {"cohen_d": 0.3, "my_metric": 2.0}})
    assert config.sesoi["cohen_d"] == 0.3
    assert config.sesoi["r"] == 0.1
    assert config.sesoi["my_metric"] == 2.0


def test_inconsistent_rigor_levels_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RigorConfig(fdr_q_confirmed=0.1, fdr_q_suggestive=0.05)
    with pytest.raises(ValidationError):
        EDAForgeConfig.model_validate({"unknown_key": 1})


def test_bad_yaml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("rigor: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_config_hash_and_budgets() -> None:
    assert config_hash(EDAForgeConfig()) == config_hash(EDAForgeConfig())
    assert config_hash(EDAForgeConfig()) != config_hash(EDAForgeConfig(budget="quick"))
    assert budget_settings("quick").permutation_max < budget_settings("deep").permutation_max


def test_contracts_are_strict() -> None:
    with pytest.raises(ValidationError):
        Effect(measure="d", estimate=float("nan"))
    with pytest.raises(ValidationError):
        Effect(measure="d", estimate=1.0, ci_low=2.0, ci_high=1.0)
    with pytest.raises(ValidationError):
        Effect(measure="d", estimate=1.0, colour="red")  # type: ignore[call-arg]
    effect = Effect(measure="d", estimate=1.0)
    with pytest.raises(ValidationError):
        effect.estimate = 2.0


def test_taxonomy_is_complete() -> None:
    assert len(PatternClass) == 12
    assert sorted(n for n, _ in PATTERN_CLASS_INFO.values()) == list(range(1, 13))
    assert len(FindingKind) == 40  # every kind listed in section 12.1
    assert "hypothesis_id" in LedgerEntry.model_fields
