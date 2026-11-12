"""L9 Synthesis: ranking, deduplication, storylines and the brief (section 9).

Phase 0 provides the interestingness score with the components that can already be computed.
"""

from __future__ import annotations

import math

from edaforge.config import InterestingnessWeights
from edaforge.models import Effect, Grade, Score

__all__ = ["GRADE_SCORE", "interestingness"]

GRADE_SCORE: dict[Grade, float] = {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.3, "E": 0.1}


def _effect_component(effect: Effect | None) -> float | None:
    """``g(effect / SESOI)``: 0 at no effect, 0.5 at the SESOI, saturating towards 1."""
    if effect is None or effect.sesoi is None or effect.sesoi <= 0.0:
        return None
    ratio = abs(effect.estimate) / effect.sesoi
    return 1.0 - math.exp(-math.log(2.0) * ratio)


def interestingness(effect: Effect | None, grade: Grade, weights: InterestingnessWeights) -> Score:
    """``w1 g(effect/SESOI) + w2 grade + ...``; uncomputed components are listed as missing.

    The score ranks findings for display only. It never changes an evidence grade.
    """
    components: dict[str, float] = {"grade": GRADE_SCORE[grade]}
    effect_part = _effect_component(effect)
    if effect_part is not None:
        components["effect"] = effect_part
    value = weights.grade * components["grade"] + weights.effect * components.get("effect", 0.0)
    return Score(value=value, components=components, partial=True)
