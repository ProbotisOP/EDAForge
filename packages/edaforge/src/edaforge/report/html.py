"""Self-contained HTML report (section 11.1, view 10; section 15 exports).

* no scripts at all, and a strict Content-Security-Policy (``default-src 'none'``) whose only
  allowances are the hash of the inline stylesheet and the fixed GitHub logo origin;
* every data-derived string is HTML-escaped (Jinja2 autoescaping plus the safe Markdown
  converter for lens text);
* lens toggles use ``<details>`` so the report needs no JavaScript and works with keyboards and
  screen readers.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence

import jinja2
from markupsafe import Markup

from edaforge.explain.language import GRADE_LABEL, GRADE_WORDING
from edaforge.models import PATTERN_CLASS_INFO, Finding, RunManifest
from edaforge.report.markdown import markdown_to_html

__all__ = ["REPORT_CSS", "render_html_report"]

# Okabe-Ito colours for grade badges; text colours chosen for >= 4.5:1 contrast.
REPORT_CSS = """
:root { color-scheme: light; --ink: #1a1a1a; --muted: #555; --rule: #d0d0d0; }
* { box-sizing: border-box; }
body { font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: var(--ink); max-width: 60rem; margin: 0 auto; padding: 1.5rem; background: #fff; }
header { border-bottom: 2px solid var(--ink); margin-bottom: 1.5rem; }
.brand { display: flex; align-items: center; gap: .75rem; margin-bottom: .75rem;
  color: inherit; text-decoration: none; }
.brand img { width: 4rem; height: 4rem; border-radius: .75rem; object-fit: cover; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
h2 { font-size: 1.3rem; margin-top: 2rem; }
.meta { color: var(--muted); font-size: .9rem; }
.finding { border: 1px solid var(--rule); border-radius: .5rem; padding: 1rem 1.25rem;
  margin: 1rem 0; }
.badges { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .5rem; }
.badge { font-size: .8rem; font-weight: 600; padding: .1rem .5rem; border-radius: 1rem;
  border: 1px solid; }
.grade-A, .grade-B { background: #e6f2fa; border-color: #0072B2; color: #003c5e; }
.grade-C { background: #fdf3e1; border-color: #E69F00; color: #6b4a00; }
.grade-D, .grade-E { background: #f2f2f2; border-color: #777; color: #333; }
.rung, .pclass, .fid { background: #fff; border-color: #999; color: #333; }
details { margin-top: .75rem; border-top: 1px solid var(--rule); padding-top: .5rem; }
summary { cursor: pointer; font-weight: 600; }
summary:focus-visible { outline: 3px solid #0072B2; outline-offset: 2px; }
table { border-collapse: collapse; margin: .5rem 0; font-size: .9rem; }
th, td { border: 1px solid var(--rule); padding: .25rem .5rem; text-align: left;
  vertical-align: top; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em;
  background: #f4f4f4; padding: 0 .2em; border-radius: .2em; }
.notice { background: #fdf3e1; border-left: 4px solid #E69F00; padding: .5rem 1rem; }
footer { margin-top: 2rem; border-top: 1px solid var(--rule); color: var(--muted);
  font-size: .85rem; }
""".strip()

_TEMPLATE = jinja2.Environment(
    loader=jinja2.PackageLoader("edaforge.report", "templates"),
    autoescape=jinja2.select_autoescape(["html", "j2"], default=True),
    undefined=jinja2.StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _style_hash(css: str) -> str:
    digest = hashlib.sha256(css.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def render_html_report(
    *,
    manifest: RunManifest,
    manifest_hash: str,
    findings: Sequence[Finding],
    searched: Sequence[Mapping[str, object]],
    warnings: Sequence[str] = (),
    locale: str = "en",
) -> str:
    cards: list[dict[str, object]] = []
    for finding in findings:
        number, class_title = PATTERN_CLASS_INFO[finding.pattern_class]
        cards.append(
            {
                "id": finding.id,
                "grade": finding.evidence.grade,
                "grade_label": GRADE_LABEL[finding.evidence.grade],
                "grade_wording": GRADE_WORDING[finding.evidence.grade],
                "rung": finding.evidence.rung,
                "pattern": f"{number}. {class_title}",
                "plain": Markup(markdown_to_html(finding.lenses.plain.markdown)),  # noqa: S704 - escaped by the converter
                "analyst": Markup(markdown_to_html(finding.lenses.analyst.markdown)),  # noqa: S704
                "scientist": Markup(markdown_to_html(finding.lenses.scientist.markdown)),  # noqa: S704
            }
        )
    template = _TEMPLATE.get_template("report.html.j2")
    return template.render(
        css=Markup(REPORT_CSS),  # noqa: S704 - static stylesheet, hashed into the CSP
        style_hash=_style_hash(REPORT_CSS),
        manifest=manifest.model_dump(mode="json"),
        manifest_hash=manifest_hash,
        cards=cards,
        searched=list(searched),
        warnings=list(warnings),
        locale=locale,
    )
