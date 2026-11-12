"""Database files: SQLite, DuckDB, Microsoft Access and dBase, read one table per database table.

Every reader opens the file read-only and never runs code the file contains:

* SQLite: ``mode=ro&immutable=1`` with ``trusted_schema=OFF``; only base tables are read (views
  are listed in the log, not evaluated);
* DuckDB: ``read_only`` with external access disabled, so a crafted file cannot make a query
  reach other files or the network;
* Access (.mdb Jet 3/4, .accdb ACE): parsed byte-by-byte by ``access-parser`` (no database engine,
  no macros, no VBA). Currency is stored as an integer scaled by 10,000 and is converted exactly;
  system tables (``MSys*``) and attachment storage tables are hidden;
* dBase / FoxPro (.dbf): ``dbfread``; a separate memo file (.dbt/.fpt) cannot come with a single
  upload, so memo fields are reported as unavailable.

Columns whose values cannot be shown faithfully (pictures, OLE objects, raw binary, Access
decimals) are left out and named in the table's log. Nothing is dropped silently.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from edaforge.ingest.infer import ParseIssue

__all__ = ["DB_FORMATS", "is_database", "read_database"]

DB_FORMATS = {"sqlite", "duckdb", "access", "dbf"}
_MAX_TABLES = 200
SQLITE_MAGIC = b"SQLite format 3\x00"
DUCKDB_MAGIC = b"DUCK"  # at byte offset 8
ACCESS_MAGICS = (b"Standard Jet DB", b"Standard ACE DB")  # at byte offset 4
DBF_VERSIONS = {
    0x02,
    0x03,
    0x04,
    0x05,
    0x30,
    0x31,
    0x32,
    0x43,
    0x63,
    0x7B,
    0x83,
    0x87,
    0x8B,
    0x8E,
    0xCB,
    0xE5,
    0xF5,
    0xFB,
}


def is_database(fmt: str) -> bool:
    return fmt in DB_FORMATS


def sniff(path: Path) -> str | None:
    """The database format by signature, or None."""
    with path.open("rb") as handle:
        head = handle.read(32)
    if head.startswith(SQLITE_MAGIC):
        return "sqlite"
    if head[8:12] == DUCKDB_MAGIC:
        return "duckdb"
    if any(head[4 : 4 + len(m)] == m for m in ACCESS_MAGICS):
        return "access"
    if head and head[0] in DBF_VERSIONS and len(head) >= 32:
        return "dbf"
    return None


def _frame(columns: list[str], rows: list[tuple[Any, ...]]) -> pl.DataFrame:
    data = {c: [r[i] for r in rows] for i, c in enumerate(columns)}
    out: dict[str, pl.Series] = {}
    for c, values in data.items():
        try:
            out[c] = pl.Series(c, values, strict=False)
        except (TypeError, ValueError, pl.exceptions.PolarsError):
            out[c] = pl.Series(c, [None if v is None else str(v) for v in values], dtype=pl.String)
    return pl.DataFrame(out) if out else pl.DataFrame()


def _drop_binary(
    frame: pl.DataFrame, issues: list[ParseIssue], extra: dict[str, str] | None = None
) -> pl.DataFrame:
    """Leave out columns holding bytes (pictures, files) and say so."""
    gone: dict[str, str] = dict(extra or {})
    for c, t in frame.schema.items():
        if t == pl.Binary or (t == pl.Object):
            gone.setdefault(c, "binary data (for example a picture or an attached file)")
    for c, why in gone.items():
        issues.append(
            ParseIssue(
                level="warning",
                code="column_not_read",
                column=c,
                message=f"{c} was not read: it holds {why}.",
            )
        )
    return frame.drop([c for c in gone if c in frame.columns])


# ---------------------------------------------------------------- SQLite


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _read_sqlite(
    path: Path, check: Callable[[int, int], None]
) -> list[tuple[str, pl.DataFrame, list[ParseIssue]]]:
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    except sqlite3.Error as exc:
        msg = f"The SQLite database could not be opened: {exc}"
        raise ValueError(msg) from exc
    try:
        con.execute("PRAGMA trusted_schema=OFF")
        objects = con.execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
        ).fetchall()
        tables = [n for t, n in objects if t == "table" and not n.startswith("sqlite_")]
        views = [n for t, n in objects if t == "view"]
        out: list[tuple[str, pl.DataFrame, list[ParseIssue]]] = []
        for name in tables[:_MAX_TABLES]:
            n = int(con.execute(f"SELECT COUNT(*) FROM {_quote(name)}").fetchone()[0])  # noqa: S608 - quoted identifier from the file's own catalog
            cur = con.execute(f"SELECT * FROM {_quote(name)}")  # noqa: S608
            cols = [d[0] for d in cur.description]
            check(n, len(cols))
            issues: list[ParseIssue] = []
            if views and name == tables[0]:
                issues.append(
                    ParseIssue(
                        level="info",
                        code="views_not_read",
                        message=(
                            f"The database also has {len(views)} view(s), which were not "
                            f"run: {', '.join(views[:8])}."
                        ),
                    )
                )
            out.append((name, _drop_binary(_frame(cols, cur.fetchall()), issues), issues))
        return out
    finally:
        con.close()


# ---------------------------------------------------------------- DuckDB


def _read_duckdb(
    path: Path, check: Callable[[int, int], None]
) -> list[tuple[str, pl.DataFrame, list[ParseIssue]]]:
    import duckdb

    try:
        con = duckdb.connect(str(path), read_only=True, config={"enable_external_access": False})
    except duckdb.Error as exc:
        msg = f"The DuckDB database could not be opened: {str(exc).splitlines()[0]}"
        raise ValueError(msg) from exc
    try:
        rows = con.execute(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') ORDER BY 1, 2"
        ).fetchall()
        tables = [(s, t) for s, t, k in rows if k == "BASE TABLE"]
        views = [t for _, t, k in rows if k != "BASE TABLE"]
        out: list[tuple[str, pl.DataFrame, list[ParseIssue]]] = []
        for schema, name in tables[:_MAX_TABLES]:
            ref = f"{_quote(schema)}.{_quote(name)}"  # identifiers quoted; read-only connection
            count = con.execute(f"SELECT COUNT(*) FROM {ref}").fetchone()  # noqa: S608
            n = int(count[0]) if count else 0
            cur = con.execute(f"SELECT * FROM {ref}")  # noqa: S608
            cols = [d[0] for d in cur.description]
            check(n, len(cols))
            issues: list[ParseIssue] = []
            if views and (schema, name) == tables[0]:
                issues.append(
                    ParseIssue(
                        level="info",
                        code="views_not_read",
                        message=(
                            f"The database also has {len(views)} view(s), which were not "
                            f"run: {', '.join(views[:8])}."
                        ),
                    )
                )
            label = name if schema == "main" else f"{schema}.{name}"
            out.append((label, _drop_binary(_frame(cols, cur.fetchall()), issues), issues))
        return out
    finally:
        con.close()


# ---------------------------------------------------------------- Access


def _read_access(
    path: Path, check: Callable[[int, int], None]
) -> list[tuple[str, pl.DataFrame, list[ParseIssue]]]:
    from access_parser import AccessParser, utils  # pyright: ignore[reportMissingTypeStubs]

    au: Any = utils  # access-parser ships no type information

    logging.getLogger("access_parser").setLevel(logging.CRITICAL)
    try:
        db: Any = AccessParser(str(path))
    except Exception as exc:  # the parser raises many types on damaged or protected files
        msg = (
            f"The Access database could not be read (it may be damaged, encrypted or "
            f"password-protected): {type(exc).__name__}"
        )
        raise ValueError(msg) from exc
    names = [
        n
        for n in db.catalog
        if not n.startswith(("MSys", "~")) and not (n.startswith("f_") and n.endswith("_Data"))
    ]
    unreadable = {
        au.TYPE_OLE: "an OLE object (for example a picture)",
        au.TYPE_BINARY: "raw binary data",
        au.TYPE_96_bit_17_BYTES: "Access Decimal values, which cannot be decoded reliably",
        au.TYPE_COMPLEX: "an attachment or multi-value field",
    }
    out: list[tuple[str, pl.DataFrame, list[ParseIssue]]] = []
    failed: list[str] = []
    for name in names[:_MAX_TABLES]:
        try:
            table = db.get_table(name)
            columns = list(table.columns.values())
            money: list[str] = []
            for col in columns:
                if col.type == au.TYPE_MONEY:
                    col.extra_props = None  # raw scaled integer instead of a formatted string
                    money.append(col.col_name_str)
            parsed = table.parse()
        except Exception:  # noqa: BLE001 - one unreadable table must not hide the others
            failed.append(name)
            continue
        issues: list[ParseIssue] = []
        skip = {c.col_name_str: unreadable[c.type] for c in columns if c.type in unreadable}
        cols = [c.col_name_str for c in columns if c.col_name_str in parsed]
        n = max((len(parsed[c]) for c in cols), default=0)
        check(n, len(cols))
        data: dict[str, list[Any]] = {}
        for c in cols:
            if c in skip:
                continue
            values = list(parsed[c]) + [None] * (n - len(parsed[c]))
            if c in money:
                values = [None if v in (None, "") else int(v) / 10_000 for v in values]
            data[c] = values
        frame = (
            _frame(list(data), list(zip(*data.values(), strict=True))) if data else pl.DataFrame()
        )
        if money:
            issues.append(
                ParseIssue(
                    level="info",
                    code="access_currency",
                    message=(
                        f"Currency columns read exactly (stored as 1/10,000 units): "
                        f"{', '.join(money)}."
                    ),
                )
            )
        out.append((name, _drop_binary(frame, issues, skip), issues))
    if failed and out:
        out[0][2].insert(
            0,
            ParseIssue(
                level="warning",
                code="tables_not_read",
                message=(
                    f"{len(failed)} table(s) in this database could not be read and were "
                    f"left out: {', '.join(failed[:8])}. "
                    "They may be linked tables, saved queries or use a feature the reader "
                    "does not support."
                ),
            ),
        )
    if failed and not out:
        msg = (
            f"None of the Access tables could be read ({', '.join(failed[:5])}). The file "
            f"may be damaged, encrypted or use an unsupported feature."
        )
        raise ValueError(msg)
    return out


# ---------------------------------------------------------------- dBase


def _read_dbf(
    path: Path, check: Callable[[int, int], None]
) -> list[tuple[str, pl.DataFrame, list[ParseIssue]]]:
    from dbfread import DBF  # pyright: ignore[reportMissingTypeStubs]
    from dbfread.exceptions import (  # pyright: ignore[reportMissingTypeStubs]
        DBFNotFound,
        MissingMemoFile,
    )

    issues: list[ParseIssue] = []
    try:
        table: Any = DBF(  # dbfread ships no type information
            str(path), load=False, ignore_missing_memofile=True, char_decode_errors="replace"
        )
        cols: list[str] = list(table.field_names)
        memo = [f.name for f in table.fields if f.type in {"M", "G", "B", "P"}]
        check(len(table), len(cols))
        rows = [tuple(r.get(c) for c in cols) for r in table]
    except (DBFNotFound, MissingMemoFile, ValueError, OSError, UnicodeError) as exc:
        msg = f"The dBase file could not be read: {exc}"
        raise ValueError(msg) from exc
    if memo:
        issues.append(
            ParseIssue(
                level="warning",
                code="dbf_memo",
                message=(
                    f"Memo fields need their separate .dbt/.fpt file and were left empty: "
                    f"{', '.join(memo)}."
                ),
            )
        )
    frame = _frame(cols, rows).drop([c for c in memo if c in cols])
    n_deleted = sum(1 for _ in table.deleted)
    if n_deleted:
        issues.append(
            ParseIssue(
                level="info",
                code="dbf_deleted",
                count=n_deleted,
                message=f"{n_deleted:,} rows marked as deleted in the file were not read.",
            )
        )
    return [("", _drop_binary(frame, issues), issues)]


_READERS = {
    "sqlite": _read_sqlite,
    "duckdb": _read_duckdb,
    "access": _read_access,
    "dbf": _read_dbf,
}


def read_database(
    path: Path, fmt: str, check: Callable[[int, int], None]
) -> list[tuple[str, pl.DataFrame, list[ParseIssue]]]:
    """Every table of the database as (name, frame, issues).

    ``check(rows, cols)`` enforces limits.
    """
    actual = sniff(path)
    if fmt in {"sqlite", "duckdb"} and actual in {"sqlite", "duckdb"}:
        fmt = actual  # a .db file can be either
    elif actual != fmt:
        label = {
            "sqlite": "a SQLite",
            "duckdb": "a DuckDB",
            "access": "an Access",
            "dbf": "a dBase",
        }[fmt]
        msg = f"The file does not look like {label} database (its first bytes do not match)."
        raise ValueError(msg)
    tables = _READERS[fmt](path, check)
    if not tables:
        msg = "The database has no tables."
        raise ValueError(msg)
    return tables
