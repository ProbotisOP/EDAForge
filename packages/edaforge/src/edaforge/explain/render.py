"""Deterministic three-lens rendering (section 10.4, step 1).

Templates live in ``edaforge/explain/templates/<finding_kind>/<lens>.md.j2`` with a generic
fallback in ``_generic/``. They are Jinja2 with ``StrictUndefined``: a template that needs a fact
the finding does not carry fails loudly and the generic template is used instead, so a lens never
shows a guessed number.

Every number in a lens comes from a field of the finding through the formatting filters below
(Law 1). Untrusted strings (column names, category labels) are wrapped in code spans with
:func:`~edaforge.explain.language.md_code`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import jinja2

from edaforge.explain.language import (
    GRADE_LABEL,
    GRADE_WORDING,
    RUNG_MEANING,
    Lens,
    fmt_num,
    fmt_p,
    fmt_pct,
    headline_hedge,
    lint_text,
    md_code,
    natural_frequency,
    shuffle_phrase,
)
from edaforge.models import PATTERN_CLASS_INFO, Finding, Lenses, LensText

__all__ = ["LENSES", "lint_lenses", "render_lenses"]

LENSES: tuple[Lens, ...] = ("plain", "analyst", "scientist")

_TAG = re.compile(r"\{%.*?%\}|\{#.*?#\}")
_LAST_BLOCK_TAG = re.compile(r"(?<![-+])%\}\s*$")


def _keep_line_breaks(source: str) -> str:
    """Keep the newline after a block tag that ends a line of text.

    ``trim_blocks`` removes the newline after *every* block tag. That is right for a line that
    holds only a tag (``{% endif %}``), but on a line such as ``- **Why:** ...{% endif %}`` it
    glues the next Markdown bullet onto this one. The closing ``%}`` of such a tag becomes
    ``+%}``, Jinja's per-tag opt-out, so line structure in the template is line structure in
    the output.
    """
    lines = source.split("\n")
    for i, line in enumerate(lines):
        if _TAG.sub("", line).strip() and _LAST_BLOCK_TAG.search(line):
            lines[i] = _LAST_BLOCK_TAG.sub("+%}", line)
    return "\n".join(lines)


class _MarkdownLoader(jinja2.PackageLoader):
    def get_source(
        self, environment: jinja2.Environment, template: str
    ) -> tuple[str, str, Callable[[], bool] | None]:
        source, filename, uptodate = super().get_source(environment, template)
        return _keep_line_breaks(source), filename, uptodate


_env = jinja2.Environment(
    loader=_MarkdownLoader("edaforge.explain", "templates"),
    undefined=jinja2.StrictUndefined,
    autoescape=False,  # noqa: S701 - output is Markdown; untrusted strings go through md_code
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)


def _signed(value: float | None, sig: int = 3) -> str:
    if value is None:
        return "n/a"
    text = fmt_num(value, sig)
    return text if value < 0 or text == "0" else "+" + text


_FILTERS: dict[str, Callable[..., str]] = {
    "signed": _signed,
    "num": fmt_num,
    "p": fmt_p,
    "pct": fmt_pct,
    "natfreq": natural_frequency,
    "code": md_code,
    "shuffles": shuffle_phrase,
}
_env.filters.update(_FILTERS)  # pyright: ignore[reportUnknownMemberType] - Jinja2 typing gap


def _context(finding: Finding) -> dict[str, Any]:
    data = finding.model_dump(mode="json")
    grade = finding.evidence.grade
    number, class_title = PATTERN_CLASS_INFO[finding.pattern_class]
    return {
        "f": data,
        "facts": data["facts"],
        "ev": data["evidence"],
        "conf": data["evidence"]["confirmation"],
        "effect": data["effect"],
        "prov": data["provenance"],
        "grade": grade,
        "grade_label": GRADE_LABEL[grade],
        "grade_wording": GRADE_WORDING[grade],
        "hedge": headline_hedge(grade),
        "rung": finding.evidence.rung,
        "rung_meaning": RUNG_MEANING[finding.evidence.rung],
        "pattern_number": number,
        "pattern_title": class_title,
    }


def _render(kind: str, lens: Lens, context: dict[str, Any]) -> str:
    try:
        template = _env.get_template(f"{kind}/{lens}.md.j2")
        return template.render(**context).strip() + "\n"
    except jinja2.TemplateNotFound:
        return _env.get_template(f"_generic/{lens}.md.j2").render(**context).strip() + "\n"
    except jinja2.UndefinedError as exc:
        # A template that needs a missing fact falls back to the generic text, never a guess.
        RENDER_ERRORS.append(f"{kind}/{lens}: {exc}")
        return _env.get_template(f"_generic/{lens}.md.j2").render(**context).strip() + "\n"


RENDER_ERRORS: list[str] = []


def _headline(markdown: str) -> str:
    first = markdown.strip().splitlines()[0]
    return first.lstrip("#").strip()


def render_lenses(finding: Finding, template: str | None = None) -> Lenses:
    """Render the Plain, Analyst and Scientist lenses of ``finding`` from templates.

    ``template`` selects a template directory other than the finding kind (analyzers that
    share a kind, such as the relationship screens, have their own wording).
    """
    context = _context(finding)
    texts = {lens: _render(template or finding.kind.value, lens, context) for lens in LENSES}
    return Lenses(
        plain=LensText(headline=_headline(texts["plain"]), markdown=texts["plain"]),
        analyst=LensText(headline=_headline(texts["analyst"]), markdown=texts["analyst"]),
        scientist=LensText(headline=_headline(texts["scientist"]), markdown=texts["scientist"]),
    )


def lint_lenses(finding: Finding) -> list[str]:
    """Language-rule violations in all three lenses, prefixed by the lens name."""
    problems: list[str] = []
    for lens in LENSES:
        text = getattr(finding.lenses, lens).markdown
        problems.extend(
            f"{lens}: {p}"
            for p in lint_text(
                text, lens=lens, rung=finding.evidence.rung, grade=finding.evidence.grade
            )
        )
    headline = finding.lenses.plain.headline
    if len(headline.split()) > 20:
        problems.append(f"plain: headline has {len(headline.split())} words (max 20)")
    return problems
