"""The data path through the real API: every supported format, malformed files, profiles, health."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import openpyxl
import polars as pl
import pytest
from fastapi.testclient import TestClient

from edaforge.server.app import create_app

ROWS = [
    ("a1", 3, 1.5, "yes", "2024-01-02"),
    ("a2", 5, 2.5, "no", "2024-01-03"),
    ("a3", None, 3.5, "yes", "2024-01-04"),
]
HEAD = ["id", "count", "value", "flag", "day"]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(tmp_path / "home", web_dist=tmp_path / "none"),
        headers={"x-edaforge-client": "1"},
    )


def _project(c: TestClient) -> str:
    return c.post("/api/projects", json={"name": "t"}).json()["id"]


def _upload(c: TestClient, pid: str, name: str, body: bytes) -> dict:
    return c.post(f"/api/projects/{pid}/uploads", files=[("files", (name, body))]).json()


def _delimited(sep: str) -> bytes:
    lines = [sep.join(HEAD)] + [sep.join("" if v is None else str(v) for v in r) for r in ROWS]
    return ("\n".join(lines) + "\n").encode()


def _xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(HEAD)
    for r in ROWS:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _parquet() -> bytes:
    buf = io.BytesIO()
    pl.DataFrame([dict(zip(HEAD, r, strict=True)) for r in ROWS]).write_parquet(buf)
    return buf.getvalue()


def _records() -> list[dict]:
    return [dict(zip(HEAD, r, strict=True)) for r in ROWS]


FORMATS = {
    "t.csv": _delimited(","),
    "t.tsv": _delimited("\t"),
    "t.xlsx": _xlsx(),
    "t.parquet": _parquet(),
    "t.json": json.dumps(_records()).encode(),
    "t.jsonl": "\n".join(json.dumps(r) for r in _records()).encode(),
}


@pytest.mark.parametrize("name", list(FORMATS))
def test_every_supported_format_reads_the_same_table(client: TestClient, name: str) -> None:
    pid = _project(client)
    out = _upload(client, pid, name, FORMATS[name])
    up = out["uploads"][0]
    assert up["status"] == "parsed", up.get("error")
    ds = out["project"]["datasets"][0]
    assert (ds["n_rows"], ds["n_cols"]) == (3, 5)
    roles = {c["name"]: c["role"] for c in ds["columns"]}
    assert roles["id"] == "identifier"  # IDs are never treated as measurements
    assert roles["value"] == "numeric"
    assert ds["health"]["status"] in {"green", "yellow"}
    rows = client.get(f"/api/projects/{pid}/datasets/{ds['id']}/rows").json()
    assert rows["total"] == 3
    prof = client.get(f"/api/projects/{pid}/datasets/{ds['id']}/profile").json()
    assert prof["health"]["score"] is not None


@pytest.mark.parametrize(
    ("name", "body", "message"),
    [
        ("empty.csv", b"", "empty"),
        ("fake.xlsx", b"not a zip at all", "not an Excel workbook"),
        ("fake.parquet", b"hello", "Parquet"),
        ("bin.csv", b"\x00\x01\x02\x03" * 50, "binary"),
        ("bad.json", b"{not json", "JSON"),
        ("notes.docx", b"PK", "Unsupported file type"),
    ],
)
def test_malformed_files_fail_with_a_readable_error_and_nothing_else_breaks(
    client: TestClient, name: str, body: bytes, message: str
) -> None:
    pid = _project(client)
    up = _upload(client, pid, name, body)["uploads"][0]
    assert up["status"] == "failed"
    assert message.lower() in (up["error"] or "").lower()
    ok = _upload(client, pid, "t.csv", FORMATS["t.csv"])
    assert ok["uploads"][0]["status"] == "parsed"
    assert len(ok["project"]["datasets"]) == 1  # the failed file left no table behind


def test_zip_bomb_workbook_is_refused(client: TestClient) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("xl/worksheets/sheet1.xml", "0" * (60 * 1024 * 1024))  # compresses ~1000x
    up = _upload(client, _project(client), "bomb.xlsx", buf.getvalue())["uploads"][0]
    assert up["status"] == "failed"


def test_file_names_cannot_escape_the_workspace(client: TestClient, tmp_path: Path) -> None:
    pid = _project(client)
    up = _upload(client, pid, "../../evil.csv", FORMATS["t.csv"])["uploads"][0]
    assert up["filename"] == "evil.csv"
    assert not (tmp_path / "evil.csv").exists()
    assert client.get("/api/projects/../../etc/passwd").status_code == 404


def test_state_changes_require_the_client_header(tmp_path: Path) -> None:
    c = TestClient(create_app(tmp_path / "home", web_dist=tmp_path / "none"))
    assert c.post("/api/projects", json={"name": "x"}).status_code == 403


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (b"a,b\n1,x\n2,y\n3,z\n", "green"),
        (
            b"a,b\n1,x\n1,x\n2,y\n3,z\n4,w\n5,v\n6,u\n7,t\n8,s\n9,r\n10,q\n",
            "yellow",
        ),  # 1 duplicate in 12 rows
        (b"a,b\n1,\n2,\n3,\n4,x\n", "red"),  # 37.5% of cells empty
        (b"a,b\n1,x\n1,x\n1,x\n2,y\n", "red"),  # half the rows are duplicates
    ],
)
def test_health_traffic_light(client: TestClient, body: bytes, status: str) -> None:
    ds = _upload(client, _project(client), "h.csv", body)["project"]["datasets"][0]
    assert ds["health"]["status"] == status, ds["health"]
