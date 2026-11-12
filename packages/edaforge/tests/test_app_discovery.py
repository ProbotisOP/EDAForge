"""Discovery through the real API on data with known answers.

* the demo files have planted patterns (see examples/demo/make_demo.py); the engine must find them;
* a table of independent noise must produce no strong finding (a false-alarm control);
* every p- and q-value shown with a finding must be the ledger's value for the same hypothesis;
* explanations must not use causal language for associations;
* with an outcome chosen, findings about the outcome lead the feed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from fastapi.testclient import TestClient

from edaforge.explain.language import lint_text
from edaforge.server.app import create_app

ROOT = Path(__file__).resolve().parents[3]


def _client(home: Path) -> TestClient:
    return TestClient(create_app(home, web_dist=home / "none"), headers={"x-edaforge-client": "1"})


def _wait(c: TestClient, pid: str, rid: str) -> dict[str, Any]:
    for _ in range(600):
        view = c.get(f"/api/projects/{pid}/runs/{rid}").json()
        if view["run"]["status"] not in {"queued", "running"}:
            assert view["run"]["status"] == "completed", view["run"].get("error")
            return view
        time.sleep(0.5)
    raise AssertionError("run did not finish")


@pytest.fixture(scope="module")
def demo_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[TestClient, str, str, dict[str, Any], Path]:
    sys.path.insert(0, str(ROOT / "examples" / "demo"))
    from make_demo import make_demo  # type: ignore[import-not-found]

    home = tmp_path_factory.mktemp("home")
    files = make_demo(tmp_path_factory.mktemp("demo"))
    c = _client(home)
    pid = c.post("/api/projects", json={"name": "demo"}).json()["id"]
    proj = c.post(
        f"/api/projects/{pid}/uploads", files=[("files", (p.name, p.read_bytes())) for p in files]
    ).json()["project"]
    scope = [d["id"] for d in proj["datasets"]]
    rid = c.post(
        f"/api/projects/{pid}/runs",
        json={"scope": scope, "acknowledged": True, "target": "returned"},
    ).json()["run_id"]
    return c, pid, rid, _wait(c, pid, rid), home


def _leaders(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in view["feed"] if not i.get("merged_into")]


def _find(
    view: dict[str, Any], family: str, *variables: str, grades: str = "ABC"
) -> dict[str, Any] | None:
    for i in view["feed"]:
        if (
            i["family"] == family
            and set(variables) <= set(i["variables"])
            and (i["evidence"].get("grade") or "") in grades
        ):
            return i
    return None


def test_planted_patterns_are_found(
    demo_run: tuple[TestClient, str, str, dict[str, Any], Path],
) -> None:
    _, _, _, view, _ = demo_run
    assert _find(view, "reversal", "sessions_per_month", "satisfaction", "region"), (
        "Simpson's reversal"
    )
    assert _find(view, "conditional", "promo", "amount", "loyalty_years"), (
        "promo explained away by loyalty"
    )
    change = _find(view, "time", "amount")
    assert change, "change point at 2024-07-01"
    assert "2024-07-01" in (change["effect_text"] or ""), "change point at 2024-07-01"
    # The planted curve saturates early and is noisy, so the engine may report it as a monotonic
    # association rather than prove the curvature; either way the relationship must be found.
    assert _find(view, "nonlinear", "amount", "discount_pct") or _find(
        view, "association", "amount", "discount_pct"
    ), "discount and amount"
    assert _find(view, "cross_file", "lifetime_value"), "cents vs dollars between the files"
    assert _find(view, "subgroup", "returned", "delivery_days", grades="ABCD"), (
        "late deliveries and returns"
    )


def test_mixed_units_are_kept_out_of_within_table_analyses(
    demo_run: tuple[TestClient, str, str, dict[str, Any], Path],
) -> None:
    _, _, _, view, _ = demo_run
    assert any(
        "lifetime_value is only compared between the source files" in n for n in view["notes"]
    )
    for i in _leaders(view):
        if "lifetime_value" in i["variables"] and i["evidence"]["basis"] == "inferential":
            assert i["family"] == "cross_file", i["headline"]


def test_outcome_findings_lead_the_feed(
    demo_run: tuple[TestClient, str, str, dict[str, Any], Path],
) -> None:
    _, _, _, view, _ = demo_run
    top = [i for i in _leaders(view) if i["evidence"]["basis"] == "inferential"][:5]
    assert sum("returned" in i["variables"] for i in top) >= 4, [i["headline"] for i in top]


def test_displayed_p_and_q_values_come_from_the_ledger(
    demo_run: tuple[TestClient, str, str, dict[str, Any], Path],
) -> None:
    c, pid, rid, view, home = demo_run
    result = json.loads(
        next(home.glob(f"projects/{pid}/runs/{rid}/result.json")).read_text("utf-8")
    )
    ledger = {e["hypothesis_id"]: e for e in result["ledger"]["entries"]}
    checked = 0
    for item in _leaders(view):
        if item["evidence"]["basis"] != "inferential":
            continue
        detail = c.get(f"/api/projects/{pid}/runs/{rid}/findings/{item['id']}").json()
        ids = detail["provenance"]["hypothesis_ids"]
        assert ids
        assert all(h in ledger for h in ids)
        for row in detail.get("ledger", []):
            entry = ledger[row["hypothesis_id"]]
            assert row.get("p_value") == entry.get("p_value"), row["hypothesis_id"]
            assert row.get("statistic") == entry.get("statistic")
        checked += 1
    assert checked >= 10


def test_explanations_avoid_causal_language(
    demo_run: tuple[TestClient, str, str, dict[str, Any], Path],
) -> None:
    c, pid, rid, view, _ = demo_run
    for item in _leaders(view)[:40]:
        if item["evidence"]["basis"] != "inferential":
            continue
        d = c.get(f"/api/projects/{pid}/runs/{rid}/findings/{item['id']}").json()
        rung = d["evidence"].get("rung", "R1")
        for lens in ("plain", "analyst", "scientist"):
            problems = lint_text(
                d["lenses"][lens]["markdown"],
                lens=lens,
                rung=rung,
                grade=d["evidence"].get("grade"),
            )
            assert not problems, (item["id"], lens, problems)
        text = d["lenses"]["plain"]["markdown"].lower()
        assert "proves" not in text
        assert " causes " not in text


def test_skipped_analyses_say_why_and_universe_uses_stored_findings(
    demo_run: tuple[TestClient, str, str, dict[str, Any], Path],
) -> None:
    c, pid, rid, view, _ = demo_run
    assert all(p["reason"] for p in view["plan"])
    uni = c.get(f"/api/projects/{pid}/runs/{rid}/universe").json()
    ids = {i["id"] for i in view["feed"]}
    assert uni["edges"]
    assert all(e["finding"] in ids for e in uni["edges"])
    by_id = {i["id"]: i for i in view["feed"]}
    for e in uni["edges"]:
        assert e["grade"] == by_id[e["finding"]]["evidence"]["grade"]


def test_group_effect_matches_the_rank_test(
    demo_run: tuple[TestClient, str, str, dict[str, Any], Path],
) -> None:
    c, pid, rid, view, _ = demo_run
    two = [
        i
        for i in view["feed"]
        if i["family"] == "group_difference" and i["effect_label"] == "Cliff's delta"
    ]
    assert two
    for i in two:
        d = c.get(f"/api/projects/{pid}/runs/{rid}/findings/{i['id']}").json()
        f = d["method"]["effect"]
        assert f["measure"] == "cliffs_delta"
        assert f["estimate"] >= 0  # "higher" follows the rank comparison
        if f["ci_low"] is not None and f["ci_low"] <= 0 <= f["ci_high"]:
            assert d["evidence"]["grade"] not in {"A", "B"}


def test_independent_noise_produces_no_strong_findings(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    n = 800
    noise = pl.DataFrame(
        {
            **{f"x{i}": rng.normal(size=n) for i in range(6)},
            "group": rng.choice(["a", "b", "c"], n),
            "flag": rng.choice(["yes", "no"], n),
        }
    )
    c = _client(tmp_path / "home")
    pid = c.post("/api/projects", json={"name": "noise"}).json()["id"]
    did = c.post(
        f"/api/projects/{pid}/uploads", files=[("files", ("noise.csv", noise.write_csv().encode()))]
    ).json()["project"]["datasets"][0]["id"]
    rid = c.post(f"/api/projects/{pid}/runs", json={"dataset_id": did, "target": "x0"}).json()[
        "run_id"
    ]
    view = _wait(c, pid, rid)
    strong = [
        i["headline"]
        for i in _leaders(view)
        if i["evidence"]["basis"] == "inferential" and i["evidence"].get("grade") in {"A", "B", "C"}
    ]
    assert not strong, strong
    assert view["searched"]
    assert sum(s["tested"] for s in view["searched"]) > 10  # it did search
