"""Report safety: escaping, CSP and no scripts (section 15)."""

from __future__ import annotations

import base64
import hashlib
import re

from edaforge.report.html import REPORT_CSS, render_html_report
from edaforge.report.markdown import markdown_to_html
from edaforge.runtime.manifest import build_manifest, manifest_hash


def test_markdown_escapes_html_before_formatting() -> None:
    html = markdown_to_html("# Title <script>alert(1)</script>\n\n**bold** and `<b>code</b>`")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<strong>bold</strong>" in html
    assert "<code>&lt;b&gt;code&lt;/b&gt;</code>" in html


def test_markdown_tables_and_nested_lists() -> None:
    md = "| A | B |\n| --- | --- |\n| 1 | <i>2</i> |\n\n- one\n\n  - child\n- two"
    html = markdown_to_html(md)
    assert '<th scope="col">A</th>' in html
    assert "<td>&lt;i&gt;2&lt;/i&gt;</td>" in html
    assert "<ul><li>one<ul><li>child</li></ul></li><li>two</li></ul>" in html


def test_report_has_hash_csp_and_no_script() -> None:
    manifest = build_manifest(seed=1, config_hash="c" * 64, inputs=[], analyzers=[])
    html = render_html_report(
        manifest=manifest,
        manifest_hash=manifest_hash(manifest),
        findings=[],
        searched=[
            {
                "analyzer": "x.<img src=x onerror=alert(1)>",
                "tested": 3,
                "promoted": 0,
                "confirmed": 0,
            }
        ],
    )
    assert "<script" not in html.lower()
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    style = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert style is not None
    assert style.group(1) == REPORT_CSS
    digest = base64.b64encode(hashlib.sha256(style.group(1).encode()).digest()).decode()
    assert f"style-src 'sha256-{digest}'" in html
    assert "default-src 'none'" in html
    assert "No findings met the bar" in html
    assert 'href="https://github.com/ProbotisOP/EDAForge"' in html
    assert "img-src https://raw.githubusercontent.com" in html
    assert (
        'src="https://raw.githubusercontent.com/ProbotisOP/EDAForge/main/apps/web/public/appicon.png"'
        in html
    )
    assert 'alt="EDAForge logo"' in html
