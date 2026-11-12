"""Convert the specification's reference list (section 21) into BibTeX entries.

Each entry keeps the specification's exact text in ``edaforge_spec_text``; authoritative metadata
(full author lists, exact titles, DOIs) is filled in only by verification against Crossref or
arXiv, never typed from memory. Entries flagged ``[verify]`` in the specification carry
``edaforge_flag = {verify}``.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from pathlib import Path

from edaforge_devtools.verify_refs.bib import BibEntry

__all__ = ["entries_from_spec", "first_author_surname", "load_supplement", "slug"]

_LINE = re.compile(r"^- (?P<authors>[^()]+?) \((?P<year>\d{4})\)\. (?P<rest>.*)$")
_CONFERENCES = (
    "NeurIPS",
    "ICML",
    "KDD",
    "ICDM",
    "AISTATS",
    "UAI",
    "CHI",
    "ICLR",
    "SIGMOD",
    "WSDM",
    "PAKDD",
    "ECML PKDD",
    "PKDD",
    "WebDB",
    "ICDE",
    "PHM",
    "ICMLA",
    "Eurographics",
    "IEEE DSAA",
)
_PUBLISHERS = ("Press", "Wiley", "Springer", "Chapman & Hall")


def slug(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", folded.lower())


def first_author_surname(authors: str) -> str:
    first = re.split(r",| & | and | et al\.?", authors)[0].strip()
    return first.split()[-1] if first else ""


def _bib_authors(authors: str) -> str:
    text = authors.replace(" et al.", " and others").replace(" et al", " and others")
    parts = re.split(r",\s*|\s+&\s+", text)
    names: list[str] = []
    for part in parts:
        names.extend(p.strip() for p in part.split(" and ") if p.strip())
    return " and ".join(names)


def _split_rest(rest: str) -> tuple[str, str, str]:
    """(title, venue, tail) from 'Title. *Venue* 27(1).'."""
    italic = re.search(r"\*([^*]+)\*", rest)
    if italic is None:
        title = rest.rstrip(". ")
        return title, "", ""
    before = rest[: italic.start()].strip().rstrip(".").strip()
    venue = italic.group(1).strip()
    tail = rest[italic.end() :].strip().rstrip(".").strip()
    return before, venue, tail


def _kind_and_venue_fields(title: str, venue: str, tail: str) -> tuple[str, dict[str, str]]:
    fields: dict[str, str] = {}
    if not title and venue and any(p in tail for p in _PUBLISHERS):
        # A book: the italic text is the title.
        fields["title"] = venue
        fields["publisher"] = tail.rsplit(". ", maxsplit=1)[-1].strip()
        return "book", fields
    fields["title"] = title
    volume = re.match(r"^(\d+)(?:\((\d+)\))?", tail)
    if volume:
        fields["volume"] = volume.group(1)
        if volume.group(2):
            fields["number"] = volume.group(2)
    if venue and any(venue.startswith(c) or c in venue for c in _CONFERENCES):
        fields["booktitle"] = venue
        return "inproceedings", fields
    if venue:
        fields["journal"] = venue
        return "article", fields
    return "misc", fields


def entries_from_spec(spec_text: str) -> list[BibEntry]:
    section = spec_text.split("## 21. References", 1)[1].split("## 22.", 1)[0]
    entries: list[BibEntry] = []
    used: set[str] = set()
    group_flag = False  # a category heading such as "**LLM agents** (all `[verify]`)."
    for raw in section.splitlines():
        if raw.startswith("**"):
            group_flag = "[verify]" in raw
            continue
        if not raw.startswith("- "):
            continue
        line = raw.strip()
        flag = group_flag or "[verify]" in line
        clean = line.replace("`[verify]`", "").replace("[verify]", "").strip()
        clean = re.sub(r"\s+\.", ".", clean)
        fields: dict[str, str] = {
            "edaforge_spec_text": raw[2:].strip(),
            "edaforge_status": "unverified",
        }
        if flag:
            fields["edaforge_flag"] = "verify"
        match = _LINE.match(clean)
        if match:
            authors, year, rest = match["authors"], match["year"], match["rest"]
            arxiv = re.search(r"arXiv:(\d{4}\.\d{4,5})", rest)
            title, venue, tail = _split_rest(re.sub(r"\(ID taken from[^)]*\)", "", rest).strip())
            if arxiv and not venue:
                kind = "misc"
                fields.update(
                    {"title": title.split(". arXiv:")[0].strip(" ."), "eprint": arxiv.group(1)}
                )
                fields["archiveprefix"] = "arXiv"
            else:
                kind, venue_fields = _kind_and_venue_fields(title, venue, tail)
                fields.update(venue_fields)
            fields["author"] = _bib_authors(authors)
            fields["year"] = year
        elif clean.startswith("- ISO/IEC 25012"):
            kind = "misc"
            authors, year = "ISO/IEC", "2008"
            fields.update(
                {
                    "author": "ISO/IEC",
                    "year": year,
                    "title": "ISO/IEC 25012:2008, Data quality model",
                }
            )
        elif clean.startswith("- Neri et al."):
            kind = "article"
            authors, year = "Neri et al.", ""
            doi = re.search(r"doi:(10\.\S+?)(?=[ )])", clean)
            fields.update({"author": "Neri and others", "title": "HOI toolbox", "journal": "JOSS"})
            if doi:
                fields["doi_from_spec"] = doi.group(1)
        else:
            msg = f"unparsed reference line: {raw}"
            raise ValueError(msg)
        doi_in_text = re.search(r"doi:(10\.\S+?)(?=[ )])", clean)
        if doi_in_text and "doi_from_spec" not in fields:
            fields["doi_from_spec"] = doi_in_text.group(1)
        title_word = next(
            (
                w
                for w in re.findall(r"[A-Za-z]{4,}", fields.get("title", ""))
                if w.lower() not in {"with", "from", "using", "towards", "into"}
            ),
            "ref",
        )
        base = f"{slug(first_author_surname(authors))}{year}{slug(title_word)}"
        key = base
        suffix = ord("a")
        while key in used:
            key = f"{base}{chr(suffix)}"
            suffix += 1
        used.add(key)
        entries.append(BibEntry(kind, key, fields))
    return entries


def load_supplement(path: Path) -> list[BibEntry]:
    """Citations used in the specification body or in the code but missing from section 21."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    entries: list[BibEntry] = []
    for item in raw.get("entry", []):
        if not isinstance(item, dict):
            continue
        data: dict[str, str] = {str(k): str(v) for k, v in item.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        kind = data.pop("type", "article")
        key = data.pop("key")
        data.setdefault("edaforge_status", "unverified")
        entries.append(BibEntry(kind, key, data))
    return entries
