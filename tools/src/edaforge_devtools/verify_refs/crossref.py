"""Verify references against Crossref (DOIs) and arXiv.

Statuses:

* ``verified``: a DOI (or arXiv ID) whose registry metadata matches the entry's first author,
  year (+-1 for online-first publication) and title;
* ``candidate``: a plausible registry match that needs a human to confirm it;
* ``mismatch``: the cited DOI exists but its metadata does not match the entry;
* ``not_found``: nothing plausible in the registry;
* ``no_doi``: books, standards and reports that have no DOI; checked by hand;
* ``network_unavailable``: the registry could not be reached; nothing was concluded.

The HTTP layer is injectable so the logic is unit-tested without network access.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass

from edaforge_devtools._json import as_dict, as_list, as_str
from edaforge_devtools.verify_refs.bib import BibEntry
from edaforge_devtools.verify_refs.spec_to_bib import first_author_surname

__all__ = [
    "Fetcher",
    "NetworkUnavailable",
    "Verification",
    "title_similarity",
    "urllib_fetcher",
    "verify_entry",
]

Fetcher = Callable[[str], bytes]
_USER_AGENT = "edaforge-verify-refs/0.1 (EDAForge reference checker)"
_TITLE_VERIFIED = 0.6
_TITLE_CANDIDATE = 0.4
_SELECT = "DOI,title,author,issued,container-title"


class NetworkUnavailable(RuntimeError):
    """The registry could not be reached (offline, blocked by a proxy, or rate-limited)."""


@dataclass(frozen=True)
class Verification:
    key: str
    status: str
    doi: str | None = None
    registry_title: str | None = None
    registry_year: int | None = None
    registry_first_author: str | None = None
    score: float | None = None
    detail: str = ""


def urllib_fetcher(url: str) -> bytes:
    if not url.startswith(("https://api.crossref.org/", "https://export.arxiv.org/")):
        msg = f"refusing to fetch unexpected URL {url}"
        raise ValueError(msg)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return bytes(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return b""
        msg = f"HTTP {exc.code} for {url}"
        raise NetworkUnavailable(msg) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NetworkUnavailable(str(exc)) from exc


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return folded.lower()


_STOP = {"the", "a", "an", "of", "and", "for", "in", "on", "with", "to", "by", "from", "via"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", _fold(text)) if w not in _STOP}


def title_similarity(cited: str, registry: str) -> float:
    """Share of the cited title's words found in the registry title (citations abbreviate)."""
    cited_words = _words(cited)
    if not cited_words:
        return 0.0
    return len(cited_words & _words(registry)) / len(cited_words)


def _first_family(item: dict[str, object]) -> str:
    authors = as_list(item.get("author")) or []
    first = as_dict(authors[0]) if authors else None
    if first is None:
        return ""
    return as_str(first.get("family")) or as_str(first.get("name"))


def _year(item: dict[str, object]) -> int | None:
    for key in ("issued", "published-print", "published-online", "created"):
        stamp = as_dict(item.get(key))
        parts = as_list(stamp.get("date-parts")) if stamp is not None else None
        first = as_list(parts[0]) if parts else None
        if first and isinstance(first[0], int):
            return first[0]
    return None


def _title(item: dict[str, object]) -> str:
    titles = as_list(item.get("title"))
    if titles:
        return as_str(titles[0])
    return as_str(item.get("title"))


def _score(entry: BibEntry, item: dict[str, object]) -> tuple[float, bool, bool]:
    similarity = title_similarity(entry.get("title") or entry.get("journal"), _title(item))
    year = _year(item)
    cited_year = entry.get("year")
    year_ok = bool(cited_year) and year is not None and abs(year - int(cited_year)) <= 1
    surname = _fold(first_author_surname(entry.cited_authors()))
    author_ok = bool(surname) and surname in _fold(_first_family(item))
    return similarity, year_ok, author_ok


def _from_item(
    key: str, status: str, item: dict[str, object], score: float, detail: str
) -> Verification:
    return Verification(
        key=key,
        status=status,
        doi=as_str(item.get("DOI")) or None,
        registry_title=_title(item),
        registry_year=_year(item),
        registry_first_author=_first_family(item),
        score=score,
        detail=detail,
    )


def _crossref_doi(entry: BibEntry, doi: str, fetch: Fetcher) -> Verification:
    raw = fetch("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"))
    if not raw:
        return Verification(entry.key, "not_found", doi=doi, detail="DOI not registered")
    body = as_dict(json.loads(raw))
    item = as_dict(body.get("message")) if body is not None else None
    if item is None:
        return Verification(entry.key, "not_found", doi=doi, detail="unexpected response")
    similarity, year_ok, author_ok = _score(entry, item)
    if similarity >= _TITLE_VERIFIED and year_ok and author_ok:
        return _from_item(entry.key, "verified", item, similarity, "DOI metadata matches")
    detail = (
        f"title {similarity:.2f}, year {'ok' if year_ok else 'differs'}, "
        f"author {'ok' if author_ok else 'differs'}"
    )
    return _from_item(entry.key, "mismatch", item, similarity, detail)


def _crossref_search(entry: BibEntry, fetch: Fetcher) -> Verification:
    query = re.sub(r"[*`\[\]]", " ", entry.citation_text())
    params = {"query.bibliographic": query, "rows": "5", "select": _SELECT}
    raw = fetch("https://api.crossref.org/works?" + urllib.parse.urlencode(params))
    body = as_dict(json.loads(raw)) if raw else None
    message = as_dict(body.get("message")) if body is not None else None
    items = as_list(message.get("items")) if message is not None else None
    best: tuple[float, dict[str, object]] | None = None
    for raw_item in items or []:
        item = as_dict(raw_item)
        if item is None:
            continue
        similarity, year_ok, author_ok = _score(entry, item)
        value = similarity + (0.5 if year_ok else 0.0) + (0.5 if author_ok else 0.0)
        if best is None or value > best[0]:
            best = (value, item)
    if best is None:
        return Verification(entry.key, "not_found", detail="no Crossref candidates")
    similarity, year_ok, author_ok = _score(entry, best[1])
    if similarity >= _TITLE_VERIFIED and year_ok and author_ok:
        return _from_item(entry.key, "verified", best[1], similarity, "unique strong match")
    if similarity >= _TITLE_CANDIDATE and (year_ok or author_ok):
        return _from_item(entry.key, "candidate", best[1], similarity, "needs human review")
    return _from_item(entry.key, "not_found", best[1], similarity, "best match too weak")


def _arxiv(entry: BibEntry, arxiv_id: str, fetch: Fetcher) -> Verification:
    raw = fetch("https://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv_id))
    if not raw:
        return Verification(entry.key, "not_found", detail=f"arXiv:{arxiv_id} not found")
    root = ET.fromstring(raw)  # noqa: S314 - trusted registry response, no DTDs
    ns = {"a": "http://www.w3.org/2005/Atom"}
    title_node = root.find("a:entry/a:title", ns)
    title = " ".join((title_node.text or "").split()) if title_node is not None else ""
    similarity = title_similarity(entry.get("title"), title)
    status = "verified" if similarity >= _TITLE_VERIFIED else "mismatch"
    return Verification(
        entry.key, status, registry_title=title, score=similarity, detail=f"arXiv:{arxiv_id}"
    )


def verify_entry(entry: BibEntry, fetch: Fetcher) -> Verification:
    """Verify one entry; a network failure yields ``network_unavailable``, never an exception."""
    try:
        doi = entry.get("doi") or entry.get("doi_from_spec")
        if doi:
            return _crossref_doi(entry, doi, fetch)
        if entry.get("eprint"):
            return _arxiv(entry, entry.get("eprint"), fetch)
        if entry.kind in {"book", "misc", "techreport"} and not entry.get("journal"):
            return Verification(entry.key, "no_doi", detail="book, standard or report: by hand")
        return _crossref_search(entry, fetch)
    except NetworkUnavailable as exc:
        return Verification(entry.key, "network_unavailable", detail=str(exc))
