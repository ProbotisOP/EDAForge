"""Small tables (8 to 29 rows): exact permutation tests, exploratory grades, exact formulas."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from fastapi.testclient import TestClient

from edaforge.discovery.formulas import formulas
from edaforge.server.app import create_app

SHOPS = """\
Shop_Name,Location_Type,Floor_Size_sqft,Num_Staff,Daily_Customers,Avg_Spend_per_Customer,Monthly_Revenue_000,Customer_Satisfaction_Score
Downtown Core,Urban,820,6,312,8.4,78.9,4.1
Westside Plaza,Urban,1100,8,278,9.2,77.0,4.3
University Ave,Suburban,950,7,195,7.8,45.6,3.9
Airport Terminal,Urban,680,5,441,6.9,91.4,3.5
Midtown Mall,Urban,1250,9,302,10.5,95.5,4.4
Riverside Park,Suburban,880,6,168,8.7,44.0,4.2
Eastgate Centre,Suburban,760,5,149,7.2,32.3,3.7
North Hills,Suburban,1050,8,221,9.8,65.1,4.0
Harbour View,Urban,1400,10,388,11.2,131.0,4.6
College Street,Urban,720,5,267,7.6,61.0,3.8
Tech Campus,Suburban,1180,8,310,9.4,87.7,4.3
Old Town Square,Urban,640,5,198,8.1,48.3,3.6
"""


def _feed(tmp_path: Path, csv: str) -> dict:
    c = TestClient(
        create_app(tmp_path / "home", web_dist=tmp_path / "none"),
        headers={"x-edaforge-client": "1"},
    )
    pid = c.post("/api/projects", json={"name": "t"}).json()["id"]
    up = c.post(f"/api/projects/{pid}/uploads", files=[("files", ("t.csv", csv.encode()))]).json()
    did = up["project"]["datasets"][0]["id"]
    rid = c.post(f"/api/projects/{pid}/runs", json={"dataset_id": did}).json()["run_id"]
    for _ in range(600):
        s = c.get(f"/api/projects/{pid}/runs/{rid}").json()
        if s["run"]["status"] in {"completed", "failed"}:
            return s
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_twelve_shops_strong_patterns_and_the_revenue_formula(tmp_path: Path) -> None:
    s = _feed(tmp_path, SHOPS)
    assert s["run"]["status"] == "completed"
    feed = [i for i in s["feed"] if not i.get("merged_into")]
    formula = [i for i in feed if i["kind"] == "formula"]
    assert [i["headline"] for i in formula] == [
        "Monthly_Revenue_000 is computed from Avg_Spend_per_Customer and Daily_Customers"
    ]
    found = {frozenset(i["variables"]) for i in feed if i["evidence"]["grade"] == "D"}
    assert frozenset({"Floor_Size_sqft", "Num_Staff"}) in found
    assert frozenset({"Num_Staff", "Avg_Spend_per_Customer"}) in found
    graded = [i for i in feed if i["evidence"]["grade"]]
    assert graded
    assert all(i["evidence"]["grade"] in {"D", "E"} for i in graded)  # exploratory: never A to C
    assert any("Small table" in n for n in s["notes"])
    assert any("Shop_Name" in n for n in s["notes"])


@pytest.mark.parametrize("seed", range(8))
def test_small_noise_tables_produce_no_evidence(tmp_path: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    n = 14
    frame = pl.DataFrame(
        {f"x{k}": rng.normal(size=n).round(3) for k in range(5)} | {"g": rng.choice(["a", "b"], n)}
    )
    s = _feed(tmp_path, frame.write_csv())
    assert s["run"]["status"] == "completed"
    graded = [i for i in s["feed"] if i["evidence"]["grade"] in {"A", "B", "C", "D"}]
    assert len(graded) <= 1, [
        i["headline"] for i in graded
    ]  # FDR at 0.1 over 15 pairs + 5 group tests
    assert not [i for i in s["feed"] if i["kind"] == "formula"]


def test_formula_kinds_and_tolerance() -> None:
    rng = np.random.default_rng(1)
    a, b = rng.uniform(1, 9, 20), rng.uniform(1, 9, 20)
    frame = pl.DataFrame(
        {
            "a": a,
            "b": b,
            "total": (a + b).round(2),
            "eur": (a * 0.92).round(3),
            "noisy": a * b * rng.uniform(0.9, 1.1, 20),
        }
    )
    found = {
        o.facts["target"]: o.facts for o in formulas(frame, ["a", "b", "total", "eur", "noisy"])
    }
    assert set(found["total"]["inputs"]) == {"a", "b"}
    assert found["eur"]["inputs"] == ["a"]
    assert "noisy" not in found  # 10% noise is a relationship, not a formula


def test_universe_carries_signs_stats_stories_and_the_formula(tmp_path: Path) -> None:
    c = TestClient(
        create_app(tmp_path / "home", web_dist=tmp_path / "none"),
        headers={"x-edaforge-client": "1"},
    )
    pid = c.post("/api/projects", json={"name": "t"}).json()["id"]
    did = c.post(
        f"/api/projects/{pid}/uploads", files=[("files", ("shops.csv", SHOPS.encode()))]
    ).json()["project"]["datasets"][0]["id"]
    rid = c.post(f"/api/projects/{pid}/runs", json={"dataset_id": did}).json()["run_id"]
    for _ in range(600):
        if c.get(f"/api/projects/{pid}/runs/{rid}").json()["run"]["status"] == "completed":
            break
        time.sleep(0.2)
    u = c.get(f"/api/projects/{pid}/runs/{rid}/universe").json()
    nodes = {n["id"]: n for n in u["nodes"]}
    floor = nodes["Floor_Size_sqft"]
    assert floor["stats"]["median"] == 915.0
    assert sum(floor["stats"]["hist"]) == 12
    assert "Num_Staff" in floor["story"]
    assert "+0.97" in floor["story"]
    assert (
        nodes["Monthly_Revenue_000"]["derived"]["formula_text"]
        == "Avg_Spend_per_Customer × Daily_Customers × 0.03"
    )
    pair = next(
        e for e in u["edges"] if {e["source"], e["target"]} == {"Floor_Size_sqft", "Num_Staff"}
    )
    assert pair["sign"] == 1
    assert abs(pair["estimate"] - 0.973) < 0.01
    assert sum(e["kind"] == "formula" for e in u["edges"]) == 2
    assert nodes["Location_Type"]["stats"]["top"][0] == {"label": "Urban", "count": 7}
