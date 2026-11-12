"""Check that every in-text citation in the specification has a bibliography entry."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from edaforge_devtools.verify_refs.bib import BibEntry
from edaforge_devtools.verify_refs.spec_to_bib import first_author_surname, slug

__all__ = ["Citation", "find_citations", "missing_citations"]

_YEAR = r"(?:1[89]|20)\d\d"
_PAREN = re.compile(r"\(([^()]*?\b" + _YEAR + r"[a-z]?\b[^()]*)\)")
_CITE = re.compile(
    r"^(?P<auth>[A-Z][^\d;]*?(?:et al\.)?),?\s+(?:\*[^*]+\*\s+)?(?P<year>" + _YEAR + r")[a-z]?$"
)
_NAME = r"[A-Z][\w'’\-]+"
_NARRATIVE = re.compile(
    r"(?P<auth>(?:(?:van den |van |de )?"
    + _NAME
    + r"(?:,\s+|\s+&\s+))*(?:van den |van |de )?"
    + _NAME
    + r"(?: et al\.)?)\s+\((?P<year>"
    + _YEAR
    + r")\)"
)


@dataclass(frozen=True)
class Citation:
    authors: str
    year: str
    context: str

    @property
    def key(self) -> tuple[str, str]:
        return slug(first_author_surname(self.authors)), self.year


def find_citations(body: str) -> list[Citation]:
    """In-text citations: parenthetical "(Name & Name, 2010)" and narrative "Name et al. (2010)"."""
    found: list[Citation] = []
    for match in _PAREN.finditer(body):
        for part in match.group(1).split(";"):
            cite = _CITE.match(part.strip())
            if cite and not cite["auth"].strip().startswith(("Apache", "MIT", "BSD", "GPL")):
                found.append(Citation(cite["auth"].strip(), cite["year"], match.group(0)))
    found.extend(Citation(m["auth"], m["year"], m.group(0)) for m in _NARRATIVE.finditer(body))
    return found


def missing_citations(body: str, entries: Iterable[BibEntry]) -> list[Citation]:
    keys: set[tuple[str, str]] = set()
    for entry in entries:
        keys.add((slug(first_author_surname(entry.cited_authors())), entry.get("year")))
    missing: dict[tuple[str, str], Citation] = {}
    for citation in find_citations(body):
        if citation.key not in keys:
            missing.setdefault(citation.key, citation)
    return sorted(missing.values(), key=lambda c: c.key)
