"""Clean-up recipes: what each step changes.

Also that exported Python and SQL reproduce the table.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from edaforge.clean import CleanError, Step, apply_recipe, recipe_python, recipe_sql, suggest_steps
from edaforge.server.app import create_app

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    sys.path.insert(0, str(ROOT / "examples" / "demo"))
    from make_demo import make_demo  # type: ignore[import-not-found]

    out = tmp_path_factory.mktemp("demo")
    make_demo(out, n_customers=400, n_orders=1200)
    return out


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "__row__": [1, 2, 3, 4, 5, 6],
            "region": ["East", "east ", "West", "East", None, "East"],
            "age": [30.0, None, 50.0, 30.0, 40.0, 30.0],
            "amount": [100.0, 200.0, 300.0, 100.0, 5.0, 100.0],
            "src": ["a", "b", "b", "a", "a", "a"],
        }
    )


def test_steps_report_exact_effects() -> None:
    steps = [
        Step(kind="drop_duplicates"),
        Step(kind="unify_labels", column="region", mapping={"east ": "East"}),
        Step(kind="fill_missing", column="age", value=40.0, value_source="median", flag=True),
        Step(kind="scale", column="amount", factor=0.01, where_column="src", where_value="b"),
        Step(kind="drop_missing", column="region"),
    ]
    out, effects = apply_recipe(_frame(), steps)
    assert [e.rows_after for e in effects] == [4, 4, 4, 4, 3]
    assert effects[0].rows_removed == [4, 6]  # original row numbers kept
    assert effects[1].cells_changed == 1
    assert effects[2].cells_changed == 1
    assert effects[3].cells_changed == 2
    assert out["__row__"].to_list() == [1, 2, 3]
    assert out["region"].to_list() == ["East", "East", "West"]
    assert out["age"].to_list() == [30.0, 40.0, 50.0]
    assert out["age_was_missing"].to_list() == [False, True, False]
    assert out["amount"].to_list() == [100.0, 2.0, 3.0]


def test_invalid_steps_are_refused() -> None:
    with pytest.raises(ValueError, match="power of ten"):
        Step(kind="scale", column="amount", factor=3)
    with pytest.raises(CleanError, match="Unknown column"):
        apply_recipe(_frame(), [Step(kind="drop_column", column="nope")])
    with pytest.raises(CleanError, match="does not fit"):
        apply_recipe(_frame(), [Step(kind="fill_missing", column="age", value="abc")])


def test_suggestions_find_planted_problems(demo: Path) -> None:
    from edaforge.ingest import ingest_file

    _, tables = ingest_file(demo / "customers_eu.csv", filename="customers_eu.csv", scratch=demo)
    t = tables[0]
    kinds = {(s.kind, s.column) for s in suggest_steps(t.frame, t.columns)}
    assert ("unify_labels", "region") in kinds  # 'east' vs 'East'
    assert ("fill_missing", "age") in kinds  # 10% of ages missing


def _recipe() -> list[Step]:
    return [
        Step(kind="drop_duplicates"),
        Step(
            kind="unify_labels",
            column="region",
            mapping={"east": "East", "west": "West", "north": "North", "south": "South"},
        ),
        Step(kind="fill_missing", column="age", value=42.0, value_source="median", flag=True),
        Step(kind="scale", column="lifetime_value", factor=0.01),
        Step(kind="drop_column", column="email"),
    ]


def _user(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.select([c for c in frame.columns if not c.startswith("__")])


def test_exported_python_reproduces_the_table(demo: Path, tmp_path: Path) -> None:
    source = pl.read_csv(demo / "customers_eu.csv", try_parse_dates=True)
    expected, _ = apply_recipe(source, _recipe())
    script = tmp_path / "recipe.py"
    script.write_text(recipe_python(_recipe(), source="customers_eu.csv"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("recipe", script)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    got = module.clean(source)
    assert got.equals(expected)


def test_exported_sql_reproduces_the_table(demo: Path, tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    source = (
        pl.read_csv(demo / "customers_eu.csv", try_parse_dates=True)
        .with_row_index("__row__", offset=1)
        .with_columns(pl.col("__row__").cast(pl.Int64))
    )
    expected, _ = apply_recipe(source, _recipe())
    sql = recipe_sql(_recipe(), source.columns)
    source.write_parquet(tmp_path / "src.parquet")
    con = duckdb.connect()
    src = tmp_path / "src.parquet"  # views take no parameters; this is a temporary test path
    con.execute(f"CREATE VIEW source_table AS SELECT * FROM read_parquet('{src}')")  # noqa: S608
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    got = pl.DataFrame(
        [dict(zip(names, r, strict=True)) for r in cur.fetchall()], infer_schema_length=None
    ).sort("__row__")
    exp = expected.sort("__row__")
    assert got.columns == exp.columns
    for c in exp.columns:
        a, b = got[c].to_list(), exp[c].to_list()
        if exp[c].dtype.is_float():
            assert all(
                (x is None and y is None) or abs(x - y) < 1e-9 for x, y in zip(a, b, strict=True)
            ), c
        else:
            assert [str(x) for x in a] == [str(x) for x in b], c


def test_api_clean_flow(demo: Path, tmp_path: Path) -> None:
    c = TestClient(
        create_app(tmp_path / "home", web_dist=tmp_path / "none"),
        headers={"x-edaforge-client": "1"},
    )
    pid = c.post("/api/projects", json={"name": "t"}).json()["id"]
    proj = c.post(
        f"/api/projects/{pid}/uploads",
        files=[("files", ("orders.xlsx", (demo / "orders.xlsx").read_bytes()))],
    ).json()["project"]
    did = proj["datasets"][0]["id"]
    assert proj["datasets"][0]["health"]["status"] == "yellow"  # planted duplicates
    sug = c.get(f"/api/projects/{pid}/datasets/{did}/clean/suggestions").json()
    dup = [s for s in sug if s["kind"] == "drop_duplicates"]
    assert dup
    pv = c.post(f"/api/projects/{pid}/datasets/{did}/clean/preview", json={"steps": dup}).json()
    assert pv["n_before"] - pv["n_after"] == 6
    made = c.post(f"/api/projects/{pid}/datasets/{did}/clean", json={"steps": dup}).json()[
        "dataset"
    ]
    assert made["kind"] == "cleaned"
    assert made["n_rows"] == pv["n_after"]
    assert made["health"]["status"] == "green"
    # Cleaning the cleaned table extends the recipe from the original source.
    more = c.post(
        f"/api/projects/{pid}/datasets/{made['id']}/clean",
        json={"steps": [{"kind": "drop_column", "column": "channel"}]},
    ).json()["dataset"]
    assert more["sources"] == [did]
    assert [s["kind"] for s in more["recipe"]] == [
        "drop_duplicates",
        "drop_column",
    ]
    py = c.get(f"/api/projects/{pid}/datasets/{more['id']}/export/recipe.py")
    assert py.status_code == 200
    assert "def clean" in py.text
    assert (
        c.get(f"/api/projects/{pid}/datasets/{more['id']}/export/recipe.sql")
        .text.strip()
        .endswith(";")
    )
    csv = c.get(f"/api/projects/{pid}/datasets/{more['id']}/export/csv")
    assert csv.status_code == 200
    assert "channel" not in csv.text.splitlines()[0]
    assert (
        c.get(f"/api/projects/{pid}/datasets/{did}/export/recipe.py").status_code == 404
    )  # files have no recipe
    assert (
        c.delete(f"/api/projects/{pid}/datasets/{did}").status_code == 409
    )  # uploads are removed elsewhere
    # The extended recipe was rebuilt from the original file, so it does not depend on `made`.
    left = c.delete(f"/api/projects/{pid}/datasets/{made['id']}").json()
    assert {d["id"] for d in left["datasets"]} == {did, more["id"]}


def test_csv_export_neutralizes_formulas(tmp_path: Path) -> None:
    c = TestClient(
        create_app(tmp_path / "home", web_dist=tmp_path / "none"),
        headers={"x-edaforge-client": "1"},
    )
    pid = c.post("/api/projects", json={"name": "t"}).json()["id"]
    body = b'name,v\n=HYPERLINK("x"),1\nok,2\n'
    did = c.post(f"/api/projects/{pid}/uploads", files=[("files", ("f.csv", body))]).json()[
        "project"
    ]["datasets"][0]["id"]
    text = c.get(f"/api/projects/{pid}/datasets/{did}/export/csv").text
    assert "'=HYPERLINK" in text


def test_downloaded_script_reproduces_the_app_export_end_to_end(demo: Path, tmp_path: Path) -> None:
    """Upload -> clean in the app -> download recipe.py -> run it on the original file.

    The result must be the same CSV.
    """
    import subprocess

    c = TestClient(
        create_app(tmp_path / "home", web_dist=tmp_path / "none"),
        headers={"x-edaforge-client": "1"},
    )
    pid = c.post("/api/projects", json={"name": "t"}).json()["id"]
    raw = demo / "customers_eu.csv"
    did = c.post(
        f"/api/projects/{pid}/uploads", files=[("files", ("customers_eu.csv", raw.read_bytes()))]
    ).json()["project"]["datasets"][0]["id"]
    steps = [
        s
        for s in c.get(f"/api/projects/{pid}/datasets/{did}/clean/suggestions").json()
        if s["kind"] in {"unify_labels", "fill_missing"}
    ]
    assert len(steps) >= 2
    made = c.post(f"/api/projects/{pid}/datasets/{did}/clean", json={"steps": steps}).json()[
        "dataset"
    ]
    (tmp_path / "recipe.py").write_text(
        c.get(f"/api/projects/{pid}/datasets/{made['id']}/export/recipe.py").text, encoding="utf-8"
    )
    (tmp_path / "app.csv").write_text(
        c.get(f"/api/projects/{pid}/datasets/{made['id']}/export/csv").text, encoding="utf-8"
    )
    subprocess.run(  # noqa: S603
        [sys.executable, str(tmp_path / "recipe.py"), str(raw), str(tmp_path / "replayed.csv")],
        check=True,
    )
    app = pl.read_csv(tmp_path / "app.csv", try_parse_dates=True)
    replayed = pl.read_csv(tmp_path / "replayed.csv", try_parse_dates=True)
    assert app.equals(replayed)
