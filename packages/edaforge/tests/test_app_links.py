"""Connecting files: join safety (duplicate keys, many-to-many, row inflation) and traceability."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from edaforge.server.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(tmp_path / "home", web_dist=tmp_path / "none"),
        headers={"x-edaforge-client": "1"},
    )


def _csv(frame: pl.DataFrame) -> bytes:
    return frame.write_csv().encode()


def _setup(c: TestClient, files: dict[str, pl.DataFrame]) -> tuple[str, dict[str, str]]:
    pid = c.post("/api/projects", json={"name": "t"}).json()["id"]
    proj = c.post(
        f"/api/projects/{pid}/uploads", files=[("files", (n, _csv(f))) for n, f in files.items()]
    ).json()["project"]
    return pid, {d["name"]: d["id"] for d in proj["datasets"]}


ORDERS = pl.DataFrame(
    {
        "order_id": [f"o{i}" for i in range(60)],
        "cust": [f"c{i % 20}" for i in range(60)],
        "amount": [float(i) for i in range(60)],
    }
)
CUSTOMERS = pl.DataFrame({"cust": [f"c{i}" for i in range(20)], "region": ["N", "S"] * 10})


def test_many_to_one_lookup_keeps_row_count_and_origin(client: TestClient) -> None:
    pid, ids = _setup(client, {"orders.csv": ORDERS, "customers.csv": CUSTOMERS})
    spec = {
        "kind": "join",
        "left": ids["orders.csv"],
        "right": ids["customers.csv"],
        "keys": [{"left": "cust", "right": "cust"}],
    }
    pv = client.post(f"/api/projects/{pid}/links/preview", json=spec).json()
    assert (pv["n_result"], pv["row_multiplication"], pv["cardinality"], pv["requires_ack"]) == (
        60,
        1.0,
        "m:1",
        False,
    )
    made = client.post(f"/api/projects/{pid}/links", json={"spec": spec}).json()["dataset"]
    assert made["n_rows"] == 60
    assert set(made["sources"]) == set(ids.values())
    rows = client.get(f"/api/projects/{pid}/datasets/{made['id']}/rows?limit=5").json()
    internal = [c["name"] for c in rows["columns"] if c["internal"]]
    assert any(n.startswith("__row__") for n in internal)  # each row points at its original rows


def test_duplicate_keys_in_lookup_table_are_flagged_and_inflation_needs_ack(
    client: TestClient,
) -> None:
    dup = pl.concat([CUSTOMERS, CUSTOMERS.head(5)])  # 5 customers appear twice
    pid, ids = _setup(client, {"orders.csv": ORDERS, "customers.csv": dup})
    spec = {
        "kind": "join",
        "left": ids["orders.csv"],
        "right": ids["customers.csv"],
        "keys": [{"left": "cust", "right": "cust"}],
    }
    pv = client.post(f"/api/projects/{pid}/links/preview", json=spec).json()
    assert pv["duplicate_keys_right"] == 5
    assert pv["n_result"] == 60 + 5 * 3  # each of 5 customers has 3 orders, now doubled
    assert pv["row_multiplication"] > 1
    assert pv["requires_ack"]
    assert any(w["severity"] == "critical" for w in pv["warnings"])
    refused = client.post(f"/api/projects/{pid}/links", json={"spec": spec, "acknowledged": False})
    assert refused.status_code == 409
    assert "inflated" in refused.json()["detail"]
    agg = {**spec, "right_mode": "aggregate"}  # the safe alternative: one summary row per key
    assert client.post(f"/api/projects/{pid}/links/preview", json=agg).json()["n_result"] == 60


def test_many_to_many_requires_ack(client: TestClient) -> None:
    a = pl.DataFrame({"k": ["x", "x", "y", "y"] * 10, "v": list(range(40))})
    b = pl.DataFrame({"k": ["x", "x", "y"] * 10, "w": list(range(30))})
    pid, ids = _setup(client, {"a.csv": a, "b.csv": b})
    spec = {
        "kind": "join",
        "left": ids["a.csv"],
        "right": ids["b.csv"],
        "keys": [{"left": "k", "right": "k"}],
        "right_mode": "expand",
    }
    pv = client.post(f"/api/projects/{pid}/links/preview", json=spec).json()
    assert pv["cardinality"] == "m:m"
    assert pv["requires_ack"]
    assert any("many-to-many" in r for r in pv["ack_reasons"])


def test_unmatched_records_are_counted_not_hidden(client: TestClient) -> None:
    extra = pl.concat(
        [ORDERS, pl.DataFrame({"order_id": ["o99"], "cust": ["ghost"], "amount": [1.0]})]
    )
    pid, ids = _setup(client, {"orders.csv": extra, "customers.csv": CUSTOMERS})
    spec = {
        "kind": "join",
        "left": ids["orders.csv"],
        "right": ids["customers.csv"],
        "keys": [{"left": "cust", "right": "cust"}],
    }
    pv = client.post(f"/api/projects/{pid}/links/preview", json=spec).json()
    assert pv["unmatched_left"] == 1
    assert pv["n_result"] == 61
    inner = client.post(f"/api/projects/{pid}/links/preview", json={**spec, "how": "inner"}).json()
    assert inner["n_result"] == 60
    assert any("dropped" in w["message"] for w in inner["warnings"])


def test_suggestions_find_the_key_and_reject_is_remembered(client: TestClient) -> None:
    pid, _ids = _setup(client, {"orders.csv": ORDERS, "customers.csv": CUSTOMERS})
    sug = [
        s
        for s in client.get(f"/api/projects/{pid}/links/suggestions").json()
        if s["kind"] == "join"
    ]
    assert sug
    assert sug[0]["keys"][0] == {"left": "cust", "right": "cust"}
    assert sug[0]["cardinality"] in {"m:1", "1:m"}
    client.post(f"/api/projects/{pid}/links/reject", json=sug[0]["spec"])
    again = [
        s
        for s in client.get(f"/api/projects/{pid}/links/suggestions").json()
        if s["kind"] == "join"
    ]
    assert again[0]["status"] == "rejected"


def test_append_keeps_source_and_flags_unit_mismatch(client: TestClient) -> None:
    us = pl.DataFrame(
        {"id": [f"u{i}" for i in range(40)], "ltv": [float(500 + i) for i in range(40)]}
    )
    eu = pl.DataFrame(
        {"id": [f"e{i}" for i in range(40)], "ltv": [float((500 + i) * 100) for i in range(40)]}
    )
    pid, ids = _setup(client, {"us.csv": us, "eu.csv": eu})
    spec = {"kind": "append", "left": ids["us.csv"], "right": ids["eu.csv"]}
    pv = client.post(f"/api/projects/{pid}/links/preview", json=spec).json()
    assert pv["n_result"] == 80
    assert pv["requires_ack"]
    assert pv["unit_mismatches"][0]["hint"] == "×100"
    fixed = {**spec, "rescale": [pv["unit_mismatches"][0]["options"][0]]}
    assert not client.post(f"/api/projects/{pid}/links/preview", json=fixed).json()["requires_ack"]
    made = client.post(f"/api/projects/{pid}/links", json={"spec": fixed}).json()["dataset"]
    rows = client.get(f"/api/projects/{pid}/datasets/{made['id']}/rows?limit=100").json()
    names = [c["name"] for c in rows["columns"]]
    src, ltv = names.index("__source__"), names.index("ltv")
    assert {r[src] for r in rows["rows"]} == {"us.csv", "eu.csv"}
    assert max(r[ltv] for r in rows["rows"]) < 1000  # EU values were brought to the US scale


def test_scope_connects_three_files_and_reuses_tables(client: TestClient) -> None:
    half = CUSTOMERS.with_columns(pl.col("cust"))
    pid, ids = _setup(
        client, {"orders.csv": ORDERS, "cust_a.csv": half.head(10), "cust_b.csv": half.tail(10)}
    )
    scope = list(ids.values())
    plan = client.post(f"/api/projects/{pid}/scope/plan", json={"dataset_ids": scope}).json()
    assert [s["kind"] for s in plan["steps"]] == ["append", "join"]
    assert plan["result_rows"] == 60
    assert not plan["unconnected"]
    assert client.post(f"/api/projects/{pid}/runs/plan", json={"scope": scope}).status_code == 200
    n1 = len(client.get(f"/api/projects/{pid}").json()["datasets"])
    assert client.post(f"/api/projects/{pid}/runs", json={"scope": scope}).status_code == 201
    n2 = len(client.get(f"/api/projects/{pid}").json()["datasets"])
    assert client.post(f"/api/projects/{pid}/runs", json={"scope": scope}).status_code == 201
    assert (
        len(client.get(f"/api/projects/{pid}").json()["datasets"]) == n2 == n1 + 2
    )  # built once, reused


def test_scope_reports_files_that_do_not_connect(client: TestClient) -> None:
    other = pl.DataFrame({"zz": [f"q{i}" for i in range(30)], "t": list(range(30))})
    pid, ids = _setup(
        client, {"orders.csv": ORDERS, "customers.csv": CUSTOMERS, "other.csv": other}
    )
    plan = client.post(
        f"/api/projects/{pid}/scope/plan", json={"dataset_ids": list(ids.values())}
    ).json()
    assert [u["table"] for u in plan["unconnected"]] == ["other.csv"]
