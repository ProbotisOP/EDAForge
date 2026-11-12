"""Evidence grades, causal rungs and downgrades (section 8.7, ADR 0005)."""

from __future__ import annotations

from typing import Any

import pytest

from edaforge.config import RigorConfig
from edaforge.models import AssumptionCheck, Confirmation, Effect, EvidenceDraft, RefutationResult
from edaforge.rigor.grading import (
    assumption_level,
    cap_grade,
    confirmation_status,
    grade_evidence,
    lower_grade,
    validate_rung,
)

RIGOR = RigorConfig()
PASS = AssumptionCheck(name="a", description="d", status="pass", severity="major")


def conf(q: float | None, method: str = "sealed_holdout", **kw: Any) -> Confirmation:
    return Confirmation(status="pending", method=method, p_value=q, q_value=q, **kw)  # type: ignore[arg-type]


def draft(**kw: Any) -> EvidenceDraft:
    base: dict[str, Any] = {
        "test": "t",
        "p_value": 0.001,
        "hypothesis_ids": ["H-000001"],
        "n": 5000,
        "confirmation": conf(0.001),
        "effect": Effect(measure="cohen_d", estimate=0.5, sesoi=0.2),
        "stability": 0.95,
        "specs_consistent": 19,
        "specs_total": 20,
        "assumptions": [PASS],
    }
    base.update(kw)
    return EvidenceDraft(**base)


def grade(d: EvidenceDraft, confirmation: Confirmation | None = None, **kw: Any) -> Any:
    return grade_evidence(
        d,
        confirmation=confirmation or d.confirmation,
        exploration_q=kw.pop("exploration_q", 0.001),
        rigor=RIGOR,
        small_sample=kw.pop("small_sample", False),
        sesoi=kw.pop("sesoi", 0.2),
        **kw,
    )


def test_grade_a_needs_every_criterion() -> None:
    assert grade(draft()).grade == "A"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"stability": 0.85}, "B"),
        ({"specs_consistent": 16}, "B"),  # 80% agree
        ({"stability": 0.7}, "C"),
        ({"specs_consistent": 13}, "C"),  # 65% agree
        ({"stability": None}, "C"),  # not measured: A and B impossible
        ({"specs_total": None, "specs_consistent": None}, "C"),
        ({"stability": 0.5}, "D"),  # measured but too unstable for a confirmed grade
        ({"effect": Effect(measure="cohen_d", estimate=0.1, sesoi=0.2)}, "B"),  # below SESOI
        (
            {
                "assumptions": [
                    AssumptionCheck(name="a", description="d", status="warn", severity="minor")
                ]
            },
            "B",
        ),
    ],
)
def test_grade_table(change: dict[str, Any], expected: str) -> None:
    assert grade(draft(**change)).grade == expected


@pytest.mark.parametrize(("q", "expected"), [(0.03, "B"), (0.08, "C"), (0.2, "D")])
def test_confirmation_q_thresholds(q: float, expected: str) -> None:
    assert grade(draft(confirmation=conf(q))).grade == expected


def test_unconfirmed_findings_fall_back_to_exploration_evidence() -> None:
    unconfirmed = Confirmation(status="not_applicable", method="none")
    assert grade(draft(confirmation=unconfirmed), exploration_q=0.05).grade == "D"
    assert grade(draft(confirmation=unconfirmed), exploration_q=0.5).grade == "E"


def test_blind_violation_voids_the_confirmation() -> None:
    evidence = grade(draft(confirmation=conf(0.001, blind_violation=True)))
    assert evidence.grade == "D"
    assert evidence.confirmation.status == "not_confirmed"
    assert any("frozen" in r for r in evidence.grade_reasons)


def test_failed_refutation_caps_at_c() -> None:
    refuted = RefutationResult(name="placebo", passed=False)
    assert grade(draft(refutations=[refuted])).grade == "C"


def test_low_robustness_value_caps_causal_claims_only() -> None:
    support = {"identification": "backdoor", "graph_edge_frequency": 0.9}
    passed = RefutationResult(name="placebo", passed=True)
    causal = draft(
        claimed_rung="R2",
        rung_support=support,
        refutations=[passed],
        sensitivity={"robustness_value": 0.05},
    )
    evidence = grade(causal)
    assert evidence.rung == "R2"
    assert evidence.grade == "C"
    associational = draft(sensitivity={"robustness_value": 0.05})
    assert grade(associational).grade == "A"


def test_assumption_failures() -> None:
    critical = AssumptionCheck(name="c", description="d", status="fail", severity="critical")
    major = AssumptionCheck(name="m", description="d", status="fail", severity="major")
    handled = critical.model_copy(update={"action": "fallback"})
    assert grade(draft(assumptions=[critical])).grade == "D"
    assert grade(draft(assumptions=[major])).grade == "C"
    assert grade(draft(assumptions=[handled])).grade == "B"


def test_small_sample_mode_is_exploratory_and_capped_at_d() -> None:
    evidence = grade(draft(), small_sample=True)
    assert evidence.grade == "D"
    assert evidence.exploratory


def test_health_flags_lower_one_step() -> None:
    evidence = grade(draft(), health_flags=["x"])
    assert evidence.grade == "B"
    assert any("data-health" in r for r in evidence.grade_reasons)


def test_rung_validation_steps_down_until_requirements_hold() -> None:
    assert validate_rung(draft(claimed_rung="R3"))[0] == "R1"
    assert validate_rung(draft(claimed_rung="R1+"))[0] == "R1"
    supported = draft(claimed_rung="R1+", rung_support={"graph_edge_frequency": 0.8})
    assert validate_rung(supported)[0] == "R1+"
    assert validate_rung(draft(p_value=None, claimed_rung="R1"))[0] == "R0"


def test_status_uses_the_confirmed_level() -> None:
    assert confirmation_status(conf(0.05), RIGOR) == "confirmed"
    assert confirmation_status(conf(0.06), RIGOR) == "not_confirmed"
    assert confirmation_status(conf(None), RIGOR) == "pending"
    assert confirmation_status(Confirmation(status="pending", method="none"), RIGOR) == (
        "not_applicable"
    )


def test_helpers() -> None:
    assert cap_grade("A", "C") == "C"
    assert cap_grade("D", "C") == "D"
    assert lower_grade("E") == "E"
    assert assumption_level([]) == "minor"
    untestable = AssumptionCheck(name="u", description="d", status="untestable", severity="major")
    assert assumption_level([PASS, untestable]) == "clean"
    skipped = AssumptionCheck(name="s", description="d", status="not_checked", severity="major")
    assert assumption_level([PASS, skipped]) == "major"
