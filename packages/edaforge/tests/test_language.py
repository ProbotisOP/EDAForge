"""Calibrated language and lint rules (sections 8.7 and 10.3)."""

from __future__ import annotations

import pytest

from edaforge.explain.language import (
    fmt_num,
    fmt_p,
    lint_text,
    md_code,
    natural_frequency,
    shuffle_phrase,
)


@pytest.mark.parametrize(
    ("p", "expected"),
    [
        (0.312, "about 3 in 10"),  # section 10.2 worked example
        (0.176, "about 1 in 6"),  # section 10.2 worked example
        (0.567, "about 6 in 10"),
        (0.5, "about 5 in 10"),
        (0.05, "about 1 in 20"),
        (0.012, "about 1 in 80"),
        (0.0005, "fewer than 1 in 1,000"),
        (0.97, "about 97 in 100"),
        (0.0, "none"),
        (1.0, "all"),
    ],
)
def test_natural_frequencies(p: float, expected: str) -> None:
    assert natural_frequency(p) == expected


def test_shuffle_phrase_distinguishes_the_floor() -> None:
    assert shuffle_phrase(0.001, 1000) == "never appeared in 999 shuffled tries"
    assert shuffle_phrase(0.02, 1000) == "appeared in about 1 in 50 shuffled tries"


def test_number_formatting() -> None:
    assert fmt_num(0.012345) == "0.0123"
    assert fmt_num(31234.5) == "31,200"
    assert fmt_num(None) == "n/a"
    assert fmt_p(2.1e-6) == "2.1e-06"
    assert fmt_p(0.0234) == "0.023"


def lint(text: str, *, lens: str = "plain", rung: str = "R1", grade: str = "C") -> list[str]:
    return lint_text(text, lens=lens, rung=rung, grade=grade)  # type: ignore[arg-type]


def test_proves_is_never_allowed() -> None:
    assert lint("This proves it.", lens="scientist", rung="R3", grade="A")


def test_significant_is_banned_in_plain_only() -> None:
    assert lint("A significant gap.")
    assert not lint("A significant gap.", lens="scientist")
    assert not lint("Unlikely to be a coincidence.")


def test_causal_verbs_need_r2_and_the_qualifier() -> None:
    assert lint("Discounts drive sales.", rung="R1+")
    assert lint("Discounts increase sales.", rung="R2", grade="B")
    assert not lint("Discounts increase sales under the stated assumptions.", rung="R2", grade="B")
    assert lint("Discounts may influence sales.", rung="R1")
    assert not lint("Discounts may influence sales.", rung="R1+")


def test_grade_wording_and_hedges_must_match_the_grade() -> None:
    assert lint("This is very likely real.", grade="C")
    assert not lint("Moderate evidence: plausible; worth verifying.", grade="C")
    assert lint("This is likely higher.", grade="C")
    assert not lint("This is likely higher.", grade="B")
    assert not lint("Code spans are exempt: `drives_total`.")


def test_md_code_neutralizes_markdown_and_backticks() -> None:
    assert md_code("x") == "`x`"
    assert md_code("a`b") == "``a`b``"
    assert md_code("`edge") == "`` `edge ``"
    assert md_code("**bold**") == "`**bold**`"


@pytest.mark.parametrize(
    "text",
    [
        "Late orders cause churn.",
        "Price changes led to churn.",
        "Ads boost sales.",
        "X results in Y.",
    ],
)
def test_base_forms_of_causal_verbs_are_caught(text: str) -> None:
    assert lint(text, rung="R1")


def test_hedged_noun_phrases_are_allowed_at_the_right_rung() -> None:
    assert not lint("X is a candidate cause of Y.", rung="R1+")
    assert not lint("Lower in B than in A.", rung="R1")


def test_nouns_after_articles_are_not_causal_verbs() -> None:
    assert not lint("There was an increase between the periods.", rung="R1")
    assert lint("Discounts increase sales.", rung="R1")
