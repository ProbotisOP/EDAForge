"""A minimal, safe Markdown-to-HTML converter for lens text.

Everything is HTML-escaped first; only a small Markdown subset is then turned into tags:
headings, bullet lists (one nesting level), pipe tables, paragraphs, code spans, bold and
``$...$`` math (shown as code until the web app renders KaTeX). Because escaping happens before
any tag is produced, text that comes from data cannot inject markup or scripts.
"""

from __future__ import annotations

import html
import re

__all__ = ["markdown_to_html"]

_CODE = re.compile(r"(`+)(.+?)\1", re.DOTALL)
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MATH = re.compile(r"\$(.+?)\$")


def _inline(text: str) -> str:
    out: list[str] = []
    pos = 0
    for match in _CODE.finditer(text):
        out.append(_styled(text[pos : match.start()]))
        content = match.group(2)
        if content.startswith(" ") and content.endswith(" ") and content.strip():
            content = content[1:-1]
        out.append(f"<code>{html.escape(content)}</code>")
        pos = match.end()
    out.append(_styled(text[pos:]))
    return "".join(out)


def _styled(text: str) -> str:
    escaped = html.escape(text)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    return _MATH.sub(r'<code class="math">\1</code>', escaped)


def _cells(line: str) -> list[str]:
    core = line.strip()
    core = core.removeprefix("|").removesuffix("|")
    return [c.strip() for c in core.split("|")]


def markdown_to_html(markdown: str, *, heading_offset: int = 2) -> str:
    """Convert lens Markdown to HTML; ``#`` maps to ``<h{1 + heading_offset}>``."""
    out: list[str] = []
    paragraph: list[str] = []
    items: list[tuple[int, str]] = []
    rows: list[list[str]] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append("<p>" + " ".join(_inline(p) for p in paragraph) + "</p>")
            paragraph.clear()

    def flush_list() -> None:
        if not items:
            return
        parts = ["<ul>"]
        i = 0
        while i < len(items):
            parts.append(f"<li>{_inline(items[i][1])}")
            j = i + 1
            children: list[str] = []
            while j < len(items) and items[j][0] == 1:
                children.append(items[j][1])
                j += 1
            if children:
                parts.append("<ul>" + "".join(f"<li>{_inline(c)}</li>" for c in children) + "</ul>")
            parts.append("</li>")
            i = j
        parts.append("</ul>")
        out.append("".join(parts))
        items.clear()

    def flush_table() -> None:
        if not rows:
            return
        header, *body = rows
        if body and all(re.fullmatch(r":?-{3,}:?", c) for c in body[0]):
            body = body[1:]
        out.append("<table><thead><tr>")
        out.extend(f'<th scope="col">{_inline(c)}</th>' for c in header)
        out.append("</tr></thead><tbody>")
        out.extend(
            "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in body
        )
        out.append("</tbody></table>")
        rows.clear()

    def flush_all() -> None:
        flush_paragraph()
        flush_list()
        flush_table()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped:
            flush_paragraph()
            flush_table()
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading and not line.startswith(" "):
            flush_all()
            level = min(6, len(heading.group(1)) + heading_offset)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif stripped.startswith("- "):
            flush_paragraph()
            flush_table()
            depth = 0 if len(line) - len(stripped) < 2 else 1
            if depth == 1 and not items:
                depth = 0
            items.append((depth, stripped[2:]))
        elif stripped.startswith("|"):
            flush_paragraph()
            flush_list()
            rows.append(_cells(stripped))
        else:
            flush_list()
            flush_table()
            paragraph.append(stripped)
    flush_all()
    return "\n".join(out)
