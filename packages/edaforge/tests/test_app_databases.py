"""Database files through the real upload API: SQLite, DuckDB, Access and dBase."""

from __future__ import annotations

import datetime
import os
import sqlite3
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edaforge.server.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(tmp_path / "home", web_dist=tmp_path / "none"),
        headers={"x-edaforge-client": "1"},
    )


def _upload(c: TestClient, path: Path, name: str | None = None) -> tuple[str, dict, list[dict]]:
    pid = c.post("/api/projects", json={"name": "t"}).json()["id"]
    out = c.post(
        f"/api/projects/{pid}/uploads", files=[("files", (name or path.name, path.read_bytes()))]
    ).json()
    up = out["uploads"][0]
    return pid, up, [d for d in out["project"]["datasets"] if d["upload_id"] == up["id"]]


def _rows(c: TestClient, pid: str, did: str) -> list[dict]:
    page = c.get(f"/api/projects/{pid}/datasets/{did}/rows?limit=500").json()
    names = [x["name"] for x in page["columns"]]
    return [dict(zip(names, r, strict=True)) for r in page["rows"]]


def _sqlite(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE customers (id TEXT PRIMARY KEY, region TEXT, age REAL, photo BLOB)")
    con.execute(
        "CREATE TABLE orders (order_id INTEGER, customer_id TEXT, amount REAL, ordered TEXT)"
    )
    con.executemany(
        "INSERT INTO customers VALUES (?,?,?,?)",
        [(f"c{i}", "NS"[i % 2], 20.0 + i, b"\x00\x01") for i in range(50)],
    )
    con.executemany(
        "INSERT INTO orders VALUES (?,?,?,?)",
        [(i, f"c{i % 50}", float(i), f"2024-01-{1 + i % 28:02d}") for i in range(200)],
    )
    con.execute("CREATE VIEW big AS SELECT * FROM orders WHERE amount > 100")
    con.commit()
    con.close()
    return path


def test_sqlite_tables_become_datasets_and_blobs_are_reported(
    client: TestClient, tmp_path: Path
) -> None:
    pid, up, ds = _upload(client, _sqlite(tmp_path / "shop.sqlite"))
    assert up["status"] == "parsed"
    by = {d["name"].split(" › ")[-1]: d for d in ds}
    assert set(by) == {"customers", "orders"}  # the view is listed, not run
    assert (by["orders"]["n_rows"], by["customers"]["n_rows"]) == (200, 50)
    issues = [i["message"] for i in by["customers"]["issues"]]
    assert any("photo was not read" in m for m in issues)
    assert any("view" in m for m in issues)
    assert {c["name"]: c["role"] for c in by["orders"]["columns"]}["ordered"] == "datetime"
    rows = _rows(client, pid, by["orders"]["id"])
    assert sum(r["amount"] for r in rows if r["amount"] is not None) == sum(
        float(i) for i in range(200)
    )


def test_sqlite_upload_cannot_be_modified_or_used_to_reach_files(
    client: TestClient, tmp_path: Path
) -> None:
    db = _sqlite(tmp_path / "shop.db")  # .db is detected by its signature
    before = db.read_bytes()
    _, up, ds = _upload(client, db)
    assert up["status"] == "parsed"
    assert len(ds) == 2
    assert db.read_bytes() == before


def test_duckdb_tables_and_schemas(client: TestClient, tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    for name in ("shop.duckdb", "shop_duck.db"):
        path = tmp_path / name
        con = duckdb.connect(str(path))
        con.execute(
            "CREATE TABLE sales AS SELECT range AS id, range * 1.5 AS amount, DATE "
            "'2024-01-01' + range::INT AS day FROM range(120)"
        )
        con.execute("CREATE SCHEMA hr")
        con.execute("CREATE TABLE hr.staff AS SELECT 'a' AS name, 10.0 AS salary")
        con.close()
        pid, up, ds = _upload(client, path)
        assert up["status"] == "parsed", up["error"]
        by = {d["name"].split(" › ")[-1]: d for d in ds}
        assert set(by) == {"sales", "hr.staff"}
        assert by["sales"]["n_rows"] == 120
        assert {c["name"]: c["dtype"] for c in by["sales"]["columns"]}["day"] == "date"
        assert sum(r["amount"] for r in _rows(client, pid, by["sales"]["id"])) == pytest.approx(
            1.5 * sum(range(120))
        )


def _dbf(path: Path) -> Path:
    fields = [("NAME", "C", 10, 0), ("QTY", "N", 5, 0), ("PRICE", "N", 8, 2), ("DAY", "D", 8, 0)]
    recs = [(f"item{i}", i, i * 1.25, datetime.date(2024, 1, 1 + i % 28), False) for i in range(30)]
    recs.append(("gone", 1, 1.0, datetime.date(2024, 1, 1), True))
    rec_len = 1 + sum(f[2] for f in fields)
    out = bytearray(
        struct.pack("<BBBBIHH20x", 0x03, 124, 1, 1, len(recs), 32 + 32 * len(fields) + 1, rec_len)
    )
    for f in fields:
        out += struct.pack("<11sc4xBB14x", f[0].encode(), f[1].encode(), f[2], f[3])
    out += b"\r"
    for n, q, p, d, deleted in recs:
        out += (
            (b"*" if deleted else b" ")
            + n.encode().ljust(10)
            + str(q).rjust(5).encode()
            + f"{p:8.2f}".encode()
            + d.strftime("%Y%m%d").encode()
        )
    path.write_bytes(bytes(out) + b"\x1a")
    return path


def test_dbase_file_skips_deleted_rows_and_says_so(client: TestClient, tmp_path: Path) -> None:
    pid, up, ds = _upload(client, _dbf(tmp_path / "items.dbf"))
    assert up["status"] == "parsed", up["error"]
    d = ds[0]
    assert d["n_rows"] == 30
    assert any("deleted" in i["message"] for i in d["issues"])
    rows = _rows(client, pid, d["id"])
    assert rows[3]["PRICE"] == pytest.approx(3.75)
    assert {c["name"]: c["dtype"] for c in d["columns"]}["DAY"] == "date"


def test_access_file_reads(client: TestClient) -> None:
    pid, up, ds = _upload(client, FIXTURES / "access_parser_test.mdb", "test.mdb")
    assert up["status"] == "parsed", up["error"]
    table = next(
        d for d in ds if d["name"].endswith("ClarotyTable")
    )  # attachment storage tables are hidden
    assert len(ds) == 1
    assert table["n_rows"] == 2
    rows = _rows(client, pid, table["id"])
    assert [r["Field1"] for r in rows] == ["test", "test2"]
    assert rows[1]["Field3"] is None


@pytest.mark.skipif(
    not os.environ.get("EDAFORGE_ACCESS_SAMPLES"),
    reason="set EDAFORGE_ACCESS_SAMPLES to a folder with nwind.mdb",
)
def test_access_currency_is_exact_on_northwind(client: TestClient) -> None:
    pid, _up, ds = _upload(client, Path(os.environ["EDAFORGE_ACCESS_SAMPLES"]) / "nwind.mdb")
    by = {d["name"].split(" › ")[-1]: d for d in ds}
    assert (by["Orders"]["n_rows"], by["Order Details"]["n_rows"], by["Products"]["n_rows"]) == (
        830,
        2155,
        77,
    )
    prices = {r["ProductName"]: r["UnitPrice"] for r in _rows(client, pid, by["Products"]["id"])}
    assert (prices["Chai"], prices["Chang"], prices["Aniseed Syrup"]) == (18.0, 19.0, 10.0)


@pytest.mark.parametrize(
    "name", ["fake.mdb", "fake.accdb", "fake.sqlite", "fake.duckdb", "fake.dbf"]
)
def test_renamed_files_are_refused(client: TestClient, tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"\x01this is not a database at all, just text" * 10)
    _, up, ds = _upload(client, path)
    assert up["status"] == "failed"
    assert "does not look like" in up["error"]
    assert not ds
