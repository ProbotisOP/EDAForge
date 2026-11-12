"""The self-contained HTML report of a discovery run (milestone 6).

Same safety rules as :mod:`edaforge.report.html`: no scripts, a Content-Security-Policy whose only
allowances are the hash of the inline stylesheet and ``data:`` images, every data-derived string
escaped (Jinja2 autoescaping; lens text through the escaping Markdown converter). Charts are SVG
drawings produced by the app from the engine's chart specifications and embedded as ``<img>``
data URIs, which browsers never execute.
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import UTC, datetime
from typing import Any

import jinja2
from markupsafe import Markup

from edaforge.profile import DatasetProfile

__all__ = ["render_run_report"]

_CSS = """
:root { color-scheme: light; --ink: #161b22; --muted: #5f6b7a; --rule: #e2e6ec; --brand: #4338ca; }
* { box-sizing: border-box; }
body { font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--ink);
  max-width: 64rem; margin: 0 auto; padding: 2rem 1.5rem 4rem; background: #fff; }
header { border-bottom: 3px solid var(--brand); padding-bottom: 1rem; margin-bottom: 1.5rem; }
h1 { font-size: 1.7rem; margin: 0 0 .3rem; } h2 { font-size: 1.3rem; margin: 2.2rem 0 .8rem; }
h3 { font-size: 1.08rem; margin: .2rem 0 .4rem; } h4 { font-size: .95rem; margin: 1rem 0 .4rem; }
.meta { color: var(--muted); font-size: .9rem; }
.box { background: #f6f7fb; border: 1px solid var(--rule); border-radius: .5rem; padding: .8rem 1rem; }
.finding { border: 1px solid var(--rule); border-radius: .6rem; padding: 1rem 1.2rem; margin: 1rem 0; break-inside: avoid; }
.badges { display: flex; flex-wrap: wrap; gap: .4rem; margin: .2rem 0 .5rem; }
.badge { font-size: .78rem; font-weight: 650; padding: .05rem .55rem; border-radius: 1rem; border: 1px solid #c7cbe6; background: #eef0ff; color: #312e81; }
.badge.ok { background: #e6f6f4; border-color: #bfe6e1; color: #0f5d56; }
.badge.warn { background: #fff6e5; border-color: #f6dcae; color: #7a4a00; }
.badge.gray { background: #f1f3f6; border-color: #dfe3ea; color: #39414d; }
.badge.bad { background: #fdecec; border-color: #f5c2c2; color: #8f1d1d; }
.chart { margin: .6rem 0; text-align: center; } .chart img { max-width: 100%; height: auto; }
details { margin-top: .6rem; border-top: 1px solid var(--rule); padding-top: .5rem; }
summary { cursor: pointer; font-weight: 650; color: var(--brand); }
table { border-collapse: collapse; margin: .5rem 0; font-size: .88rem; width: 100%; }
th, td { border: 1px solid var(--rule); padding: .3rem .5rem; text-align: left; vertical-align: top; }
th { background: #f6f7fb; }
code { font-family: ui-monospace, Menlo, monospace; font-size: .88em; background: #f2f3f7; padding: 0 .2em; border-radius: .2em; }
.grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: .6rem; }
.stat { border: 1px solid var(--rule); border-radius: .5rem; padding: .6rem .8rem; }
.stat b { display: block; font-size: 1.35rem; }
.lens h3, .lens h4 { margin-top: .6rem; }
footer { margin-top: 3rem; border-top: 1px solid var(--rule); padding-top: .8rem; color: var(--muted); font-size: .85rem; }
@media print { details { display: block; } details > summary { display: none; } }
""".strip()  # noqa: E501 - stylesheet lines; their length is not code style

_TEMPLATE = jinja2.Environment(
    loader=jinja2.DictLoader(
        {
            "report": """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src '{{ style_hash }}'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EDAForge report — {{ project }}</title><style>{{ css }}</style></head>
<body>
<header>
  <div class="meta">EDAForge · discovery report</div>
  <h1>{{ project }}</h1>
  <div class="meta">Table: <b>{{ dataset }}</b> · run {{ run.id }} · {{ created }} · {{ rows }} rows analyzed · {{ mode_text }}</div>
</header>

<div class="box">
  <b>How to read this report.</b> Every number was computed by the analysis engine on your data; nothing was estimated by hand
  or by a language model. Findings come from statistical tests whose false-discovery rate is controlled across everything that was
  tested. Grades summarize the evidence: <b>A</b> very strong, <b>B</b> strong, <b>C</b> moderate (all three held up on data the search
  never saw), <b>D</b> tentative, <b>E</b> did not hold up. Items marked <b>fact</b> are exact data checks, not tests.
  Associations describe the data; they do not show that one thing is the reason for another.
</div>

<h2>Summary</h2>
<div class="grid">
  <div class="stat"><b>{{ summary.n_findings }}</b>findings (grade A–D)</div>
  <div class="stat"><b>{{ summary.n_confirmed }}</b>confirmed on held-out data</div>
  <div class="stat"><b>{{ summary.n_facts }}</b>data facts</div>
  <div class="stat"><b>{{ summary.n_tested }}</b>hypotheses tested</div>
</div>
{% if health %}<p class="meta">Data health score of the table: <b>{{ health.score }}</b> ({{ health.label }}). {{ health.method }}</p>{% endif %}
{% if target %}<p>Outcome studied: <code>{{ target }}</code>.</p>{% endif %}

<h2>Key findings</h2>
{% for f in findings %}
<section class="finding">
  <div class="meta">#{{ f.rank }} · {{ f.id }} · {{ f.family_label }}</div>
  <h3>{{ f.headline }}</h3>
  <div class="badges">
    {% if f.evidence.basis == "descriptive" %}<span class="badge gray">fact · {{ f.severity }}</span>
    {% else %}<span class="badge {{ 'ok' if f.evidence.grade in ['A','B'] else ('warn' if f.evidence.grade == 'C' else 'gray') }}">grade {{ f.evidence.grade }} · {{ f.evidence.label }}</span>
    <span class="badge gray">{{ f.evidence.confirmation }}</span>{% endif %}
    {% if f.effect_text %}<span class="badge gray">{{ f.effect_label }}: {{ f.effect_text }}</span>{% endif %}
    {% if f.records_label %}<span class="badge gray">{{ f.records_label }}</span>{% endif %}
  </div>
  {% if f.chart_uri %}<div class="chart"><img alt="{{ f.chart_alt }}" src="{{ f.chart_uri }}"></div>
  {% elif f.has_chart %}<p class="meta">(The chart is shown in the app; it was not included in this export.)</p>{% endif %}
  <div class="lens">{{ f.plain }}</div>
  <details><summary>Analyst view</summary><div class="lens">{{ f.analyst }}</div></details>
  <details><summary>Scientist view: method, evidence and reproducibility</summary><div class="lens">{{ f.scientist }}</div></details>
  {% if f.caveats %}<h4>Caveats</h4><ul>{% for c in f.caveats %}<li>{{ c }}</li>{% endfor %}</ul>{% endif %}
</section>
{% else %}
<p>No finding reached grade D or better. That does not show that no relationship exists; see "What was checked".</p>
{% endfor %}

{% if issues %}
<h2>Data-quality issues</h2>
<table><tr><th>Severity</th><th>Issue</th><th>Rule</th><th>Records</th></tr>
{% for q in issues %}<tr><td>{{ q.severity }}</td><td><b>{{ q.title }}</b><br>{{ q.detail }}</td><td>{{ q.method }}</td><td>{{ q.count if q.count is not none else "" }}</td></tr>{% endfor %}
</table>
{% endif %}

<h2>What was checked</h2>
<table><tr><th>Analysis</th><th>Status</th><th>Why</th><th>Method</th></tr>
{% for p in plan %}<tr><td>{{ p.label }}</td><td>{{ p.status }}</td><td>{{ p.reason }}</td><td>{{ p.method }}</td></tr>{% endfor %}
</table>
<table><tr><th>Analysis</th><th>Hypotheses tested</th><th>Passed screening</th><th>Confirmed</th></tr>
{% for s in searched %}<tr><td>{{ s.label }}</td><td>{{ s.tested }}</td><td>{{ s.promoted }}</td><td>{{ s.confirmed }}</td></tr>{% endfor %}
</table>
{% if null_results %}<p><b>Searched without a reportable result:</b> {% for n in null_results %}{{ n.label }} ({{ n.message }}){% if not loop.last %}; {% endif %}{% endfor %}
A search that finds nothing does not show that nothing is there.</p>{% endif %}

{% if notes or warnings %}<h2>How the data was handled</h2><ul>
{% for n in notes %}<li>{{ n }}</li>{% endfor %}{% for w in warnings %}<li>{{ w }}</li>{% endfor %}</ul>{% endif %}

<h2>Provenance and reproducibility</h2>
<table>
<tr><th>Run ID</th><td><code>{{ manifest.run_id }}</code></td></tr>
<tr><th>Random seed</th><td>{{ manifest.seed }}</td></tr>
<tr><th>EDAForge version</th><td>{{ manifest.edaforge_version }}</td></tr>
<tr><th>Validation</th><td>{{ split.mode }} — {{ split.strategy }} (search rows: {{ split.n_exploration }}, held-out rows: {{ split.n_confirmation }})</td></tr>
{% for i in manifest.inputs %}<tr><th>Input</th><td>{{ i.name }} — {{ i.n_rows }} rows, fingerprint <code>{{ i.sha256[:16] }}</code></td></tr>{% endfor %}
<tr><th>Libraries</th><td>{% for k, v in manifest.libraries.items() %}{{ k }} {{ v }}{% if not loop.last %}, {% endif %}{% endfor %}</td></tr>
</table>
<footer>Generated {{ generated }} by EDAForge on this computer. Personal-data columns were excluded from the analysis
and are masked in examples.</footer>
</body></html>
"""  # noqa: E501 - HTML template lines; their length is not code style
        }
    ),
    autoescape=True,
    undefined=jinja2.ChainableUndefined,
)

_SVG = re.compile(r"^\s*(<\?xml[^>]*>\s*)?<svg[\s>]", re.IGNORECASE)
_MAX_SVG = 2_000_000


def _svg_uri(svg: str | None) -> str | None:
    if not svg or len(svg) > _MAX_SVG or not _SVG.match(svg):
        return None
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def render_run_report(
    *,
    project_name: str,
    run: dict[str, Any],
    data: dict[str, Any],
    profile: DatasetProfile | None,
    charts: dict[str, str],
) -> str:
    from edaforge.report.markdown import markdown_to_html

    details = data["details"]
    leaders = [
        i
        for i in data["feed"]
        if not i.get("merged_into")
        and (
            i["evidence"]["basis"] == "descriptive"
            or i["evidence"]["grade"] in {"A", "B", "C", "D"}
        )
    ]
    findings: list[dict[str, Any]] = []
    for item in leaders[:30]:
        d = details[item["id"]]
        chart = d["charts"][0] if d.get("charts") else None
        findings.append(
            {
                **item,
                # markdown_to_html escapes every value it is given, so its output is safe markup.
                "plain": Markup(  # noqa: S704
                    markdown_to_html(d["lenses"]["plain"]["markdown"], heading_offset=2)
                ),
                "analyst": Markup(  # noqa: S704
                    markdown_to_html(d["lenses"]["analyst"]["markdown"], heading_offset=2)
                ),
                "scientist": Markup(  # noqa: S704
                    markdown_to_html(d["lenses"]["scientist"]["markdown"], heading_offset=2)
                ),
                "chart_uri": _svg_uri(charts.get(item["id"])),
                "chart_alt": chart["alt_text"] if chart else "",
                "has_chart": chart is not None,
            }
        )
    summary = run.get("summary", {})
    split = data.get("split", {})
    labels = {p["analyzer"]: p["label"] for p in data.get("plan", [])}
    searched = [
        {**s, "label": labels.get(s["analyzer"], s["analyzer"])} for s in data.get("searched", [])
    ]
    mode_text = {
        "holdout": "findings confirmed on a sealed held-out sample",
        "cross_fit": "findings confirmed by repeated cross-fitting",
        "small_sample": "small sample: every finding is exploratory",
    }.get(split.get("mode", ""), split.get("mode", ""))
    created = str(run.get("created_at", ""))[:16].replace("T", " ")
    digest = hashlib.sha256(_CSS.encode("utf-8")).digest()
    return _TEMPLATE.get_template("report").render(
        css=Markup(_CSS),  # noqa: S704 - static stylesheet hashed into the CSP
        style_hash="sha256-" + base64.b64encode(digest).decode("ascii"),
        project=project_name,
        dataset=summary.get("dataset", ""),
        run=run,
        created=created,
        rows=f"{data.get('spec', {}).get('rows', 0):,}",
        mode_text=mode_text,
        summary=summary,
        health=profile.health if profile else None,
        target=data.get("spec", {}).get("target"),
        findings=findings,
        issues=[q for q in (profile.issues if profile else []) if q.severity != "info"],
        plan=data.get("plan", []),
        searched=searched,
        null_results=[
            {**s, "message": f"{s['tested']:,} tested, none confirmed"}
            for s in searched
            if s.get("confirmed", 0) == 0
        ],
        notes=data.get("notes", []),
        warnings=[w for w in data.get("warnings", []) if not w.startswith("template fallback")],
        manifest=data.get("manifest", {}),
        split=split,
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )
