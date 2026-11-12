"""The Hypothesis Ledger: the only source of p-values (Law 2, section 8.2)."""

from __future__ import annotations

import numpy as np
import pytest

from edaforge.errors import BlindAnalysisError, ContractViolation, LedgerError
from edaforge.rigor.ledger import HypothesisLedger
from edaforge.runtime.clock import FixedClock


def ledger() -> HypothesisLedger:
    return HypothesisLedger("R-test", 7, clock=FixedClock(), permutation_max=200)


def draw(rng: np.random.Generator, size: int) -> np.ndarray:
    return rng.random(size)


def register(led: HypothesisLedger, split: str = "exploration", analyzer: str = "a.x") -> str:
    return led.register(
        hypothesis="h",
        family_path=["a", analyzer, "fam"],
        analyzer=analyzer,
        analyzer_version="1",
        test="t",
        split=split,  # type: ignore[arg-type]
    )


def test_ids_are_sequential_and_entries_complete() -> None:
    led = ledger()
    first, second = register(led), register(led)
    assert (first, second) == ("H-000001", "H-000002")
    result = led.permutation_test(first, observed=0.99, draw=draw, n_obs=10)
    entry = led.entry(first)
    assert entry.status == "tested"
    assert entry.p_value == result.p_value
    assert entry.n_resamples == result.n_draws
    assert entry.seed is not None
    assert entry.created_at.tzinfo is not None
    assert led.entry(second).status == "registered"


def test_a_hypothesis_is_tested_exactly_once() -> None:
    led = ledger()
    hid = register(led)
    led.analytic_test(hid, statistic=1.0, p_value=0.2, n_obs=5)
    with pytest.raises(LedgerError, match="already tested"):
        led.analytic_test(hid, statistic=1.0, p_value=0.01, n_obs=5)


def test_seeds_depend_only_on_the_run_seed_and_hypothesis() -> None:
    a, b = ledger(), ledger()
    pa = a.permutation_test(register(a), observed=0.97, draw=draw, n_obs=10).p_value
    pb = b.permutation_test(register(b), observed=0.97, draw=draw, n_obs=10).p_value
    assert pa == pb


def test_confirmation_requires_a_frozen_candidate_list() -> None:
    led = ledger()
    with pytest.raises(BlindAnalysisError):
        register(led, split="confirmation")
    led.freeze(["k"])
    assert register(led, split="confirmation") == "H-000001"
    with pytest.raises(BlindAnalysisError):
        led.freeze(["k"])


def test_pre_freeze_sealed_access_marks_confirmation_entries() -> None:
    led = ledger()
    assert led.note_sealed_access("peek") is True
    led.freeze(["k"])
    hid = register(led, split="confirmation")
    assert led.entry(hid).blind_violation
    assert led.sealed_accesses[0].before_freeze


def test_p_values_must_match_the_ledger() -> None:
    led = ledger()
    hid = register(led)
    with pytest.raises(ContractViolation, match="no recorded test"):
        led.verify_p_value(hid, 0.5)
    led.analytic_test(hid, statistic=2.0, p_value=0.03, n_obs=9)
    led.verify_p_value(hid, 0.03)
    with pytest.raises(ContractViolation, match="Law 2"):
        led.verify_p_value(hid, 0.01)


def test_views_bind_analyzer_and_split() -> None:
    led = ledger()
    view = led.view(analyzer="a.x", analyzer_version="1", split="exploration")
    hid = view.register(hypothesis="h", family=["fam"], test="t")
    assert led.entry(hid).family_path == ["a", "a.x", "fam"]
    intruder = led.view(analyzer="b.y", analyzer_version="1", split="exploration")
    with pytest.raises(ContractViolation, match="cannot test"):
        intruder.analytic_test(hid, statistic=1.0, p_value=0.5, n_obs=3)


def test_adjust_counts_untested_hypotheses_as_p_one() -> None:
    led = ledger()
    tested = register(led)
    untested = [register(led) for _ in range(3)]
    led.analytic_test(tested, statistic=3.0, p_value=0.01, n_obs=50)
    q = led.adjust([tested, *untested])
    assert q[tested] == pytest.approx(0.04)
    assert all(q[h] == 1.0 for h in untested)


def test_resampling_is_audited_and_purposes_are_unique() -> None:
    led = ledger()
    view = led.view(analyzer="a.x", analyzer_version="1", split="exploration")
    x = np.random.default_rng(0).normal(size=50)
    view.bootstrap(
        purpose="ci", samples=[x], statistic=lambda a: float(a.mean()), n_resamples=200, level=0.9
    )
    with pytest.raises(LedgerError, match="reused"):
        view.bootstrap(
            purpose="ci",
            samples=[x],
            statistic=lambda a: float(a.mean()),
            n_resamples=200,
            level=0.9,
        )
    scoped = led.view(analyzer="a.x", analyzer_version="1", split="exploration", scope="split1")
    scoped.bootstrap(
        purpose="ci", samples=[x], statistic=lambda a: float(a.mean()), n_resamples=200, level=0.9
    )
    records = led.to_dict()["resampling"]
    assert isinstance(records, list)
    assert len(records) == 2


def test_jsonl_round_trip() -> None:
    led = ledger()
    hid = register(led)
    led.analytic_test(hid, statistic=1.5, p_value=0.2, n_obs=10)
    entries = HypothesisLedger.entries_from_jsonl(led.to_jsonl())
    assert entries == list(led.entries())


def test_invalid_inputs() -> None:
    led = ledger()
    with pytest.raises(LedgerError, match="unknown"):
        led.entry("H-999999")
    with pytest.raises(LedgerError, match="family_path"):
        led.register(
            hypothesis="h",
            family_path=[],
            analyzer="a.x",
            analyzer_version="1",
            test="t",
            split="exploration",
        )
    hid = register(led)
    with pytest.raises(LedgerError, match="finite"):
        led.analytic_test(hid, statistic=float("nan"), p_value=0.5, n_obs=1)


def test_untestable_hypothesis_is_closed_without_a_p_value() -> None:
    led = ledger()
    hid = register(led)
    led.mark_untestable(hid, reason="too few rows set aside", n_obs=4)
    entry = led.entry(hid)
    assert entry.status == "untestable"
    assert entry.p_value is None
    assert entry.statistic is None
    assert entry.untestable_reason == "too few rows set aside"
    led.verify_p_value(hid, None)  # no number claimed: allowed
    with pytest.raises(ContractViolation, match="no p-value to cite"):
        led.verify_p_value(hid, 0.01)  # citing a p-value for an untested hypothesis is not
    with pytest.raises(LedgerError, match="closed exactly once"):
        led.analytic_test(hid, statistic=1.0, p_value=0.5, n_obs=4)


def test_registered_but_unclosed_hypothesis_still_fails_verification() -> None:
    led = ledger()
    hid = register(led)
    with pytest.raises(ContractViolation, match="no recorded test"):
        led.verify_p_value(hid, None)
