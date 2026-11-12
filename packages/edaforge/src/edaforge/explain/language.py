"""Calibrated language (sections 8.7 and 10.3).

* grade wording and hedges come from the evidence grade;
* causal verbs must match the causal rung ("proves" is never allowed);
* the Plain lens never says "significant";
* natural frequencies ("about 3 in 10") replace decimals for proportions (Gigerenzer & Hoffrage,
  1995).

:func:`lint_text` enforces these rules on rendered text. It runs on every template output in the
test suite and, at runtime, on every rendered lens (violations become warnings). The Phase 6
grounding validator applies the same rules to LLM rewrites.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from edaforge.canonical import round_sig
from edaforge.models import RUNG_ORDER, Grade, Rung

__all__ = [
    "GRADE_LABEL",
    "GRADE_WORDING",
    "RUNG_MEANING",
    "Lens",
    "fmt_num",
    "fmt_p",
    "fmt_pct",
    "headline_hedge",
    "lint_text",
    "md_code",
    "natural_frequency",
    "shuffle_phrase",
    "word_count",
]

Lens = Literal["plain", "analyst", "scientist"]

GRADE_WORDING: dict[Grade, str] = {
    "A": "very likely real",
    "B": "likely real",
    "C": "plausible; worth verifying",
    "D": "tentative lead",
    "E": "speculative",
}
GRADE_LABEL: dict[Grade, str] = {
    "A": "very strong",
    "B": "strong",
    "C": "moderate",
    "D": "tentative",
    "E": "hypothesis",
}
RUNG_MEANING: dict[Rung, str] = {
    "R0": "a description of the data",
    "R1": "an association",
    "R1+": "a causal hypothesis that depends on assumptions",
    "R2": "a causal estimate under the stated assumptions",
    "R3": "a model-based counterfactual",
}

_HEDGE: dict[Grade, str] = {
    "A": "very likely",
    "B": "likely",
    "C": "plausibly",
    "D": "possibly",
    "E": "speculatively",
}


def headline_hedge(grade: Grade) -> str:
    return _HEDGE[grade]


# ---------------------------------------------------------------- numbers


def fmt_num(value: float | None, sig: int = 3) -> str:
    """Engine-side rounding for display (``sig`` significant digits, thousands separators)."""
    if value is None:
        return "n/a"
    if not math.isfinite(value):
        msg = "cannot format a non-finite number"
        raise ValueError(msg)
    if value == 0.0:
        return "0"
    rounded = round_sig(value, sig)
    magnitude = math.floor(math.log10(abs(rounded)))
    if magnitude >= 15 or magnitude <= -5:
        return f"{rounded:.{sig - 1}e}"
    decimals = max(0, sig - 1 - magnitude)
    return f"{rounded:,.{decimals}f}"


def fmt_p(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 1e-4:
        return f"{value:.1e}"
    return fmt_num(value, 2)


def fmt_pct(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * value:.{digits}f}%"


def natural_frequency(p: float) -> str:
    """'about k in d' for a proportion (Gigerenzer & Hoffrage, 1995).

    Denominators are limited to 2, 3, 4, 5, 6 and 10. Tens are preferred unless another
    denominator is closer by more than 0.01, so 0.312 reads "about 3 in 10", 0.176 reads
    "about 1 in 6" and 0.567 reads "about 6 in 10". Very small and very large proportions use
    larger denominators ("about 1 in 40", "about 97 in 100").
    """
    if not 0.0 <= p <= 1.0:
        msg = "natural_frequency expects a proportion in [0, 1]"
        raise ValueError(msg)
    if p == 0.0:
        return "none"
    if p == 1.0:
        return "all"
    if p < 0.001:
        return "fewer than 1 in 1,000"
    if p > 0.999:
        return "more than 999 in 1,000"
    if p < 0.1:
        n = 1.0 / p
        digits = 1 if n < 100 else 2
        rounded = int(round_sig(n, digits))
        return f"about 1 in {rounded:,}"
    if p > 0.9:
        return f"about {math.floor(100 * p + 0.5)} in 100"

    def nearest(d: int) -> tuple[float, int, int]:
        k = min(d - 1, max(1, math.floor(p * d + 0.5)))
        return abs(k / d - p), k, d

    tens = nearest(10)
    best = min((nearest(d) for d in (2, 3, 4, 5, 6)), key=lambda t: (t[0], t[2]))
    _, k, d = best if best[0] < tens[0] - 0.01 else tens
    return f"about {k} in {d}"


def shuffle_phrase(p_value: float, n_max: int) -> str:
    """How often a pattern this strong appeared on shuffled data (section 10.3 wording)."""
    if p_value <= 1.0 / n_max + 1e-12:
        return f"never appeared in {n_max - 1:,} shuffled tries"
    return f"appeared in {natural_frequency(p_value)} shuffled tries"


# ---------------------------------------------------------------- markdown safety


def md_code(text: str) -> str:
    """Wrap untrusted text (column names, labels) in a CommonMark code span.

    Inside a code span markdown is not interpreted, so data cannot inject formatting or links.
    The fence is longer than any run of backticks in the text.
    """
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") or not text.strip() else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def word_count(text: str) -> int:
    return len(re.findall(r"[^\s]+", text))


# ---------------------------------------------------------------- lint

_ALWAYS_BANNED = re.compile(r"\b(prove|proves|proved|proven|proof)\b", re.IGNORECASE)
_PLAIN_BANNED = re.compile(r"\b(significant|significance|statistically)\b", re.IGNORECASE)
_CAUSAL_STRONG = re.compile(
    r"(?<!candidate )(?<!root )\b(?:cause|causes|caused)\b"
    r"|\b(?:causing|drive|drives|driven|driving|leads to|lead to|led to|results in|result in|"
    r"increases|decreases|reduce|reduces|raises|lowers|boost|boosts|push|pushes|pushing|"
    r"because of)\b"
    r"|(?<!an )(?<!the )(?<!a )\b(?:increase|decrease)\b",
    re.IGNORECASE,
)
_CAUSAL_HEDGED = re.compile(r"\b(may influence|may affect|candidate cause)\b", re.IGNORECASE)
_R2_QUALIFIER = re.compile(r"under the stated assumptions|according to the model", re.IGNORECASE)
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1", re.DOTALL)
_GRADE_PHRASES = re.compile(
    "|".join(re.escape(w) for w in sorted(GRADE_WORDING.values(), key=len, reverse=True)),
    re.IGNORECASE,
)


def _strip_code(text: str) -> str:
    """Remove code spans: quoted data and formulas are not prose."""
    return _CODE_SPAN.sub(" ", text)


def lint_text(
    text: str,
    *,
    lens: Lens,
    rung: Rung,
    grade: Grade,
    calibrated_probability: float | None = None,
) -> list[str]:
    """Violations of the language rules in ``text`` (empty when clean)."""
    prose = _strip_code(text)
    problems: list[str] = []
    if m := _ALWAYS_BANNED.search(prose):
        problems.append(f"'{m.group(0)}' is never allowed")
    if lens == "plain" and (m := _PLAIN_BANNED.search(prose)):
        problems.append(f"'{m.group(0)}' is not allowed in the Plain lens")
    level = RUNG_ORDER.index(rung)
    strong = _CAUSAL_STRONG.search(prose)
    if strong and level < RUNG_ORDER.index("R2"):
        problems.append(f"causal verb '{strong.group(0)}' needs rung R2 or above (have {rung})")
    if strong and level >= RUNG_ORDER.index("R2") and not _R2_QUALIFIER.search(prose):
        problems.append("causal verbs at R2+ must say 'under the stated assumptions'")
    hedged = _CAUSAL_HEDGED.search(prose)
    if hedged and level < RUNG_ORDER.index("R1+"):
        problems.append(f"'{hedged.group(0)}' needs rung R1+ or above (have {rung})")
    # Grade wording: only the finding's own grade phrase may appear.
    problems.extend(
        f"grade wording '{found}' does not match grade {grade}"
        for found in _GRADE_PHRASES.findall(prose)
        if found.lower() != GRADE_WORDING[grade].lower()
    )
    hedge_prose = _GRADE_PHRASES.sub(" ", prose)
    if re.search(r"\bvirtually certain\b", hedge_prose, re.IGNORECASE) and (
        calibrated_probability is None or calibrated_probability < 0.99
    ):
        problems.append("'virtually certain' needs a calibrated probability >= 0.99")
    if re.search(r"\bvery likely\b", hedge_prose, re.IGNORECASE) and grade != "A":
        problems.append(f"'very likely' is reserved for grade A (have {grade})")
    if re.search(r"(?<!very )(?<!un)\blikely\b", hedge_prose, re.IGNORECASE) and grade not in {
        "A",
        "B",
    }:
        problems.append(f"'likely' needs grade A or B (have {grade})")
    return problems
