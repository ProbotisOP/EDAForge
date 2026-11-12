"""Evidence grades, causal rungs and their downgrades (section 8.7).

Only this module turns an :class:`~edaforge.models.EvidenceDraft` into graded
:class:`~edaforge.models.Evidence`. The interpretation of the grade table is recorded in
docs/adr/0005-evidence-grading-and-confirmation-tiers.md; in short:

* "Confirmed at q < x" means the confirmation test (sealed holdout, cross-fit or reusable
  holdout, without a blind-analysis violation) has a BH-adjusted q-value <= x.
* Criteria that were not measured (stability, specification curve, SESOI) do not hold. Grades A
  and B therefore require measured stability and multiverse agreement; grade C does not, which
  is how the table's "or" clauses read: a confirmed finding that misses B's measurements is C.
* A measured stability below 0.60, or agreement below 60%, rules out the confirmed grades.
* D: significant after FDR on exploration data only (q <= the suggestive level). E: the rest.

Downgrades and caps, applied in this order:

1. a failed refutation caps the grade at C;
2. a causal claim (rung R1+ or above) with a robustness value below the configured threshold is
   capped at C;
3. a failed critical assumption check without a fallback caps the grade at D; a failed major
   check caps it at C;
4. exploratory findings (small-sample mode without pre-registration) are capped at D;
5. health issues on any involved column lower the grade by one step.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from edaforge.config import RigorConfig
from edaforge.models import (
    GRADE_ORDER,
    RUNG_ORDER,
    AssumptionCheck,
    Confirmation,
    Effect,
    Evidence,
    EvidenceDraft,
    Grade,
    Rung,
)

__all__ = [
    "assumption_level",
    "cap_grade",
    "confirmation_status",
    "grade_evidence",
    "lower_grade",
    "validate_rung",
]

_CONFIRMING_METHODS = frozenset({"sealed_holdout", "cross_fit", "reusable_holdout"})
AssumptionLevel = Literal["clean", "minor", "major", "critical"]
_LEVELS: tuple[AssumptionLevel, ...] = ("clean", "minor", "major", "critical")


def _worse(a: AssumptionLevel, b: AssumptionLevel) -> AssumptionLevel:
    return _LEVELS[max(_LEVELS.index(a), _LEVELS.index(b))]


def cap_grade(grade: Grade, cap: Grade) -> Grade:
    """The weaker of ``grade`` and ``cap``."""
    return GRADE_ORDER[max(GRADE_ORDER.index(grade), GRADE_ORDER.index(cap))]


def lower_grade(grade: Grade, steps: int = 1) -> Grade:
    return GRADE_ORDER[min(len(GRADE_ORDER) - 1, GRADE_ORDER.index(grade) + steps)]


def assumption_level(checks: Sequence[AssumptionCheck]) -> AssumptionLevel:
    """Summarize assumption checks.

    * clean: at least one executed check, and every check passed (untestable ones aside);
    * minor: warnings, minor failures, failures handled by a fallback, skipped minor checks,
      or no executed checks at all;
    * major: a failed or skipped major (or a skipped critical) check;
    * critical: a failed critical check without a fallback.
    """
    executed = [c for c in checks if c.status != "untestable"]
    level: AssumptionLevel = "clean" if executed else "minor"
    for check in executed:
        if check.status == "pass":
            continue
        if check.status == "fail" and check.action != "fallback":
            if check.severity == "critical":
                return "critical"
            level = _worse(level, "major" if check.severity == "major" else "minor")
        elif check.status == "not_checked" and check.severity != "minor":
            level = _worse(level, "major")
        else:
            level = _worse(level, "minor")
    return level


def confirmation_status(
    confirmation: Confirmation, rigor: RigorConfig
) -> Literal["confirmed", "not_confirmed", "pending", "not_applicable"]:
    if confirmation.method == "none":
        return "not_applicable"
    if confirmation.q_value is None:
        return "pending"
    if (
        confirmation.method in _CONFIRMING_METHODS
        and not confirmation.blind_violation
        and confirmation.q_value <= rigor.fdr_q_confirmed
    ):
        return "confirmed"
    return "not_confirmed"


def validate_rung(draft: EvidenceDraft) -> tuple[Rung, list[str]]:
    """Lower the analyzer's claimed rung until its requirements are met."""
    reasons: list[str] = []
    support = draft.rung_support
    rung: Rung = draft.claimed_rung

    def has_association() -> bool:
        return draft.p_value is not None or draft.e_value is not None

    def has_graph_support() -> bool:
        value = support.get("graph_edge_frequency")
        return isinstance(value, int | float)

    def has_r2() -> bool:
        identified = isinstance(support.get("identification"), str)
        refuted = bool(draft.refutations)
        sensitive = "robustness_value" in draft.sensitivity or "e_value" in draft.sensitivity
        return identified and refuted and sensitive

    if rung == "R3" and not (has_r2() and isinstance(support.get("counterfactual_model"), str)):
        reasons.append("R3 needs an R2 estimate plus a fitted counterfactual model")
        rung = "R2"
    if rung == "R2" and not has_r2():
        reasons.append("R2 needs identification, refutation and a sensitivity analysis")
        rung = "R1+"
    if rung == "R1+" and not has_graph_support():
        reasons.append("R1+ needs support from the consensus causal graph")
        rung = "R1"
    if rung == "R1" and not has_association():
        reasons.append("R1 needs a ledgered test of association")
        rung = "R0"
    return rung, reasons


def _sesoi_met(effect: Effect | None, sesoi: float | None) -> bool | None:
    if effect is None or sesoi is None:
        return None
    return abs(effect.estimate) >= sesoi


def grade_evidence(
    draft: EvidenceDraft,
    *,
    confirmation: Confirmation,
    exploration_q: float | None,
    rigor: RigorConfig,
    small_sample: bool,
    preregistered: bool = False,
    health_flags: Sequence[str] = (),
    sesoi: float | None = None,
) -> Evidence:
    """Grade a draft (section 8.7); every grade comes with the reasons it is not higher."""
    reasons: list[str] = []
    rung, rung_reasons = validate_rung(draft)

    usable = (
        confirmation.method in _CONFIRMING_METHODS
        and confirmation.q_value is not None
        and not confirmation.blind_violation
    )
    if confirmation.blind_violation:
        reasons.append(
            "sealed data were accessed before the candidate list was frozen; "
            "the confirmation does not count"
        )
    q = confirmation.q_value if usable else None
    stability = draft.stability
    share: float | None = None
    if draft.specs_total and draft.specs_consistent is not None:
        share = draft.specs_consistent / draft.specs_total
    level = assumption_level(draft.assumptions)
    sesoi_met = _sesoi_met(draft.effect, sesoi)

    def unmet_a() -> list[str]:
        out: list[str] = []
        if q is None or q > 0.01:
            out.append("not confirmed at q <= 0.01")
        if stability is None:
            out.append("stability not measured")
        elif stability < 0.90:
            out.append(f"stability {stability:.2f} < 0.90")
        if share is None:
            out.append("specification curve not run")
        elif share < 0.90:
            out.append(f"{share:.0%} of specifications agree (< 90%)")
        if level != "clean":
            out.append("not every assumption check passed")
        if sesoi_met is None:
            out.append("no smallest effect size of interest to compare with")
        elif not sesoi_met:
            out.append("effect is smaller than the smallest effect size of interest")
        return out

    def unmet_b() -> list[str]:
        out: list[str] = []
        if q is None or q > rigor.fdr_q_confirmed:
            out.append(f"not confirmed at q <= {rigor.fdr_q_confirmed}")
        if stability is None:
            out.append("stability not measured")
        elif stability < 0.75:
            out.append(f"stability {stability:.2f} < 0.75")
        if share is None:
            out.append("specification curve not run")
        elif share < 0.75:
            out.append(f"{share:.0%} of specifications agree (< 75%)")
        if level not in {"clean", "minor"}:
            out.append("assumption checks raised more than minor warnings")
        return out

    def unmet_c() -> list[str]:
        out: list[str] = []
        if q is None or q > rigor.fdr_q_suggestive:
            out.append(f"not confirmed at q <= {rigor.fdr_q_suggestive}")
        if stability is not None and stability < 0.60:
            out.append(f"stability {stability:.2f} < 0.60")
        if share is not None and share < 0.60:
            out.append(f"{share:.0%} of specifications agree (< 60%)")
        return out

    grade: Grade
    if not (missing := unmet_a()):
        grade = "A"
    else:
        reasons.extend(f"not A: {m}" for m in missing)
        if not (missing := unmet_b()):
            grade = "B"
        else:
            reasons.extend(f"not B: {m}" for m in missing)
            if not (missing := unmet_c()):
                grade = "C"
            else:
                reasons.extend(f"not C: {m}" for m in missing)
                if exploration_q is not None and exploration_q <= rigor.fdr_q_suggestive:
                    grade = "D"
                else:
                    grade = "E"
                    reasons.append(
                        "not D: not significant after FDR on the exploration data"
                        if exploration_q is not None
                        else "not D: no FDR-controlled exploration test"
                    )

    eff = draft.effect
    if (
        eff is not None
        and eff.ci_low is not None
        and eff.ci_high is not None
        and eff.ci_low <= 0 <= eff.ci_high
        and grade in {"A", "B"}
    ):
        # A test can reject "no difference at all" while the size of the effect stays uncertain
        # enough that zero is plausible; then the finding is not strong evidence of an effect.
        reasons.append(
            f"the {eff.measure} interval [{eff.ci_low:.3g}, {eff.ci_high:.3g}] includes "
            f"no effect: capped at C"
        )
        grade = cap_grade(grade, "C")
    if any(not r.passed for r in draft.refutations) and grade in {"A", "B"}:
        reasons.append("a refutation failed: capped at C")
        grade = cap_grade(grade, "C")
    is_causal = RUNG_ORDER.index(rung) >= RUNG_ORDER.index("R1+")
    rv = draft.sensitivity.get("robustness_value")
    if is_causal and rv is not None and rv < rigor.robustness_value_min and grade in {"A", "B"}:
        reasons.append(
            f"robustness value {rv:.2f} < {rigor.robustness_value_min}: causal claim capped at C"
        )
        grade = cap_grade(grade, "C")
    if level == "critical":
        reasons.append("a critical assumption check failed without a fallback: capped at D")
        grade = cap_grade(grade, "D")
    elif level == "major" and grade in {"A", "B"}:
        reasons.append("a major assumption check failed: capped at C")
        grade = cap_grade(grade, "C")
    exploratory = small_sample and not preregistered
    if exploratory:
        reasons.append("small-sample mode without pre-registration: exploratory, capped at D")
        grade = cap_grade(grade, "D")
        if (
            eff is not None
            and eff.ci_low is not None
            and eff.ci_high is not None
            and eff.ci_low <= 0 <= eff.ci_high
        ):
            # Nothing is checked on held-out data, so an interval that includes no effect is
            # the only safeguard left: such a pattern is not reported as evidence.
            reasons.append(
                f"exploratory and the {eff.measure} interval [{eff.ci_low:.3g}, "
                f"{eff.ci_high:.3g}] includes no effect: E"
            )
            grade = cap_grade(grade, "E")
    if health_flags:
        lowered = lower_grade(grade)
        if lowered != grade:
            reasons.append(
                "data-health issues on involved columns ("
                + ", ".join(sorted(health_flags))
                + f"): lowered from {grade} to {lowered}"
            )
        grade = lowered

    status = confirmation_status(confirmation, rigor)
    return Evidence(
        test=draft.test,
        statistic=draft.statistic,
        p_value=draft.p_value,
        e_value=draft.e_value,
        q_value=exploration_q,
        n=draft.n,
        confirmation=confirmation.model_copy(update={"status": status}),
        stability=draft.stability,
        specs_consistent=draft.specs_consistent,
        specs_total=draft.specs_total,
        sensitivity=draft.sensitivity,
        assumptions=draft.assumptions,
        refutations=draft.refutations,
        grade=grade,
        rung=rung,
        hypothesis_ids=draft.hypothesis_ids,
        grade_reasons=reasons,
        rung_reasons=rung_reasons,
        exploratory=exploratory or grade in {"D", "E"},
    )
