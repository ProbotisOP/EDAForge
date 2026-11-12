"""Reference tooling: building the bibliography, coverage and DOI verification logic."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from edaforge_devtools.verify_refs.bib import BibEntry, parse_bib, render_bib
from edaforge_devtools.verify_refs.coverage import find_citations, missing_citations
from edaforge_devtools.verify_refs.crossref import (
    NetworkUnavailable,
    title_similarity,
    verify_entry,
)
from edaforge_devtools.verify_refs.spec_to_bib import entries_from_spec, load_supplement

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "docs" / "archive" / "PROJECT_PROMPT.v1.md"
# The specification is not part of every checkout; only the tests that read it need it.
needs_spec = pytest.mark.skipif(
    not SPEC_PATH.is_file(), reason=f"{SPEC_PATH.relative_to(ROOT)} is not in this checkout"
)


@pytest.fixture
def spec() -> str:
    return SPEC_PATH.read_text("utf-8")


@needs_spec
def test_every_section_21_reference_becomes_an_entry(spec: str) -> None:
    entries = entries_from_spec(spec)
    assert len(entries) == 219
    assert len({e.key for e in entries}) == 219
    flagged = [e for e in entries if e.get("edaforge_flag") == "verify"]
    # 8 entries flagged on their own line, plus the 4 under "LLM agents ... (all [verify])".
    assert len(flagged) == 12
    assert all(e.get("edaforge_status") == "unverified" for e in entries)
    assert not any(e.get("doi") for e in entries), "no DOI may come from memory"
    neri = next(e for e in entries if e.key.startswith("neri"))
    assert neri.get("doi_from_spec") == "10.21105/joss.07360"


@needs_spec
def test_the_committed_bibliography_is_up_to_date_and_complete(spec: str) -> None:
    committed = parse_bib((ROOT / "docs" / "references.bib").read_text("utf-8"))
    rebuilt = entries_from_spec(spec) + load_supplement(
        ROOT / "docs" / "references-supplement.toml"
    )
    assert [e.key for e in committed] == [e.key for e in rebuilt]
    body = spec.split("## 21. References", 1)[0]
    assert missing_citations(body, committed) == []


def test_bib_round_trip() -> None:
    entries = [
        BibEntry("article", "x2020y", {"author": "X and Y", "year": "2020", "title": "T {braces}"})
    ]
    parsed = parse_bib(render_bib(entries))
    assert parsed[0].key == "x2020y"
    assert parsed[0].get("title") == "T (braces)"


def test_citation_finder_handles_both_styles() -> None:
    text = (
        "as shown (Klein & Roodman, 2005; Gross & Vitells, 2010) and by Meinshausen, Meier & "
        "Bühlmann (2009), but not in (MIT; last release January 2025)."
    )
    found = {(c.key, c.year) for c in find_citations(text)}
    assert (("klein", "2005"), "2005") in found
    assert (("gross", "2010"), "2010") in found
    assert (("meinshausen", "2009"), "2009") in found
    assert len(found) == 3


ENTRY = BibEntry(
    "article",
    "anscombe1973graphs",
    {
        "author": "Anscombe",
        "year": "1973",
        "title": "Graphs in statistical analysis",
        "journal": "The American Statistician",
        "edaforge_spec_text": (
            "Anscombe (1973). Graphs in statistical analysis. *The American Statistician* 27(1)."
        ),
    },
)


def crossref_item(title: str, year: int, family: str, doi: str = "10.1/x") -> dict[str, object]:
    return {
        "DOI": doi,
        "title": [title],
        "issued": {"date-parts": [[year]]},
        "author": [{"family": family}],
    }


def fetcher(payload: object) -> Callable[[str], bytes]:
    def fetch(url: str) -> bytes:
        return json.dumps(payload).encode()

    return fetch


def test_search_verifies_a_strong_unique_match() -> None:
    payload = {
        "message": {"items": [crossref_item("Graphs in Statistical Analysis", 1973, "Anscombe")]}
    }
    result = verify_entry(ENTRY, fetcher(payload))
    assert (result.status, result.doi) == ("verified", "10.1/x")


def test_weak_matches_need_review_or_fail() -> None:
    candidate = {"message": {"items": [crossref_item("Graphs in data analysis", 1980, "Anscombe")]}}
    assert verify_entry(ENTRY, fetcher(candidate)).status == "candidate"
    nothing = {"message": {"items": [crossref_item("Protein folding", 2001, "Smith")]}}
    assert verify_entry(ENTRY, fetcher(nothing)).status == "not_found"


def test_cited_doi_with_wrong_metadata_is_a_mismatch() -> None:
    entry = BibEntry(ENTRY.kind, ENTRY.key, {**ENTRY.fields, "doi": "10.1/wrong"})
    payload = {"message": crossref_item("Something else entirely", 1999, "Other")}
    assert verify_entry(entry, fetcher(payload)).status == "mismatch"


def test_network_failures_are_inconclusive_not_failures() -> None:
    def offline(url: str) -> bytes:
        raise NetworkUnavailable("HTTP 403 (proxy)")

    result = verify_entry(ENTRY, offline)
    assert result.status == "network_unavailable"
    assert "403" in result.detail


def test_books_have_no_doi() -> None:
    book = BibEntry(
        "book", "pearl2009causality", {"author": "Pearl", "year": "2009", "title": "Causality"}
    )
    assert verify_entry(book, fetcher({})).status == "no_doi"


@pytest.mark.parametrize(
    ("cited", "registry", "minimum"),
    [
        ("PELT", "Optimal detection of changepoints with a linear computational cost", 0.0),
        ("Same stats, different graphs", "Same Stats, Different Graphs: Generating Datasets", 1.0),
    ],
)
def test_title_similarity(cited: str, registry: str, minimum: float) -> None:
    assert title_similarity(cited, registry) >= minimum
