"""A minimal BibTeX reader and writer for the project's own, regular ``references.bib``."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

__all__ = ["BibEntry", "parse_bib", "render_bib"]

_FIELD_ORDER = (
    "author",
    "year",
    "title",
    "journal",
    "booktitle",
    "publisher",
    "volume",
    "number",
    "pages",
    "doi",
    "eprint",
    "archiveprefix",
    "url",
    "note",
)


@dataclass
class BibEntry:
    kind: str
    key: str
    fields: dict[str, str] = field(default_factory=dict[str, str])

    def get(self, name: str) -> str:
        return self.fields.get(name, "")

    def cited_authors(self) -> str:
        """Authors as the specification cites them, else the ``author`` field."""
        spec = self.get("edaforge_spec_text")
        return spec.split(" (")[0] if spec else self.get("author").replace(" and ", ", ")

    def citation_text(self) -> str:
        """A one-line citation for registry searches."""
        if self.get("edaforge_spec_text"):
            return self.get("edaforge_spec_text")
        parts = [self.cited_authors(), f"({self.get('year')})", self.get("title")]
        parts.append(self.get("journal") or self.get("booktitle") or self.get("publisher"))
        return " ".join(p for p in parts if p)


def _escape(value: str) -> str:
    return value.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def render_bib(entries: Iterable[BibEntry], header: str = "") -> str:
    out: list[str] = []
    if header:
        out.extend(f"% {line}" if line else "%" for line in header.splitlines())
        out.append("")
    for entry in entries:
        out.append(f"@{entry.kind}{{{entry.key},")
        names = [n for n in _FIELD_ORDER if n in entry.fields]
        names += sorted(n for n in entry.fields if n not in _FIELD_ORDER)
        out.extend(f"  {name} = {{{_escape(entry.fields[name])}}}," for name in names)
        out.append("}")
        out.append("")
    return "\n".join(out)


_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.MULTILINE)


def parse_bib(text: str) -> list[BibEntry]:
    entries: list[BibEntry] = []
    for match in _ENTRY.finditer(text):
        kind, key = match.group(1).lower(), match.group(2)
        pos = match.end()
        depth = 1
        end = pos
        while end < len(text) and depth:
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
            end += 1
        body = text[pos : end - 1]
        fields: dict[str, str] = {}
        for fmatch in re.finditer(r"(\w+)\s*=\s*\{", body):
            start = fmatch.end()
            level = 1
            cursor = start
            while cursor < len(body) and level:
                if body[cursor] == "{":
                    level += 1
                elif body[cursor] == "}":
                    level -= 1
                cursor += 1
            fields[fmatch.group(1).lower()] = body[start : cursor - 1].strip()
        entries.append(BibEntry(kind, key, fields))
    return entries
