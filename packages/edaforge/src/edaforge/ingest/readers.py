"""Readers for the supported upload formats (PROJECT_PROMPT.md sections 3 and 9).

CSV, TSV, XLSX, Parquet, JSON and JSONL. Every reader returns raw tables plus the issues found
while reading; :func:`edaforge.ingest.ingest_file` then types the columns.

Safety (section 9): file sizes, row, column and cell counts are limited; XLSX archives are
checked for decompression bombs before they are opened; spreadsheet macros and external links
are never executed or followed (openpyxl reads cached cell values only); the file content is
checked against the claimed format. File names are never used to build paths.
"""

from __future__ import annotations

import codecs
import csv
import json
import os
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Literal

import polars as pl

from edaforge.ingest.infer import ParseIssue

__all__ = [
    "FORMATS",
    "IngestError",
    "IngestLimits",
    "RawTable",
    "detect_format",
    "read_raw_tables",
]

FileFormat = Literal[
    "csv", "tsv", "xlsx", "parquet", "json", "jsonl", "sqlite", "duckdb", "access", "dbf"
]
FORMATS: dict[str, FileFormat] = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".tab": "tsv",
    ".xlsx": "xlsx",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
    ".db": "sqlite",  # SQLite or DuckDB, told apart by the file's signature
    ".duckdb": "duckdb",
    ".mdb": "access",
    ".accdb": "access",
    ".dbf": "dbf",
}


class IngestError(Exception):
    """A file that cannot be read; the message is shown to the user as is."""


@dataclass(frozen=True)
class IngestLimits:
    max_bytes: int = int(os.environ.get("EDAFORGE_MAX_UPLOAD_MB", "256")) * 1024 * 1024
    max_rows: int = 5_000_000
    max_columns: int = 2_000
    max_cells: int = 100_000_000
    max_xlsx_uncompressed: int = 1024 * 1024 * 1024
    max_xlsx_ratio: float = 200.0
    max_xlsx_members: int = 10_000


@dataclass
class RawTable:
    name: str  # sheet name for workbooks; "" for single-table files
    frame: pl.DataFrame  # original column order; text or typed columns
    original_names: list[str]
    issues: list[ParseIssue]


def detect_format(filename: str) -> FileFormat:
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsm" or suffix == ".xls":
        msg = (
            f"{suffix} files are not supported. Save the workbook as .xlsx (macros are never run) "
            "or export the sheet as CSV."
        )
        raise IngestError(msg)
    fmt = FORMATS.get(suffix)
    if fmt is None:
        supported = ", ".join(sorted({s for s in FORMATS if len(s) <= 8}))
        msg = f"Unsupported file type {suffix or '(none)'}. Supported: {supported}."
        raise IngestError(msg)
    return fmt


def _check_magic(path: Path, fmt: FileFormat) -> None:
    with path.open("rb") as handle:
        head = handle.read(8)
    if fmt == "xlsx" and not head.startswith(b"PK\x03\x04"):
        msg = "The file is named .xlsx but is not an Excel workbook (it is not a ZIP archive)."
        raise IngestError(msg)
    if fmt == "parquet" and not head.startswith(b"PAR1"):
        msg = "The file is named .parquet but does not start with the Parquet signature."
        raise IngestError(msg)
    if fmt in {"csv", "tsv", "json", "jsonl"} and (
        head.startswith((b"PK\x03\x04", b"PAR1")) or b"\x00" in head
    ):
        msg = f"The file is named .{fmt} but contains binary data."
        raise IngestError(msg)


# ---------------------------------------------------------------- header names


def sanitize_names(names: list[str], issues: list[ParseIssue]) -> list[str]:
    """Unique, non-empty column names; every rename is reported."""
    out: list[str] = []
    seen: set[str] = set()
    for i, original in enumerate(names):
        name = original.strip()
        reason = ""
        if not name:
            name, reason = f"column_{i + 1}", "the header was empty"
        elif name != original:
            reason = "leading or trailing spaces were removed"
        if name.startswith("__"):
            name, reason = "col" + name, "names starting with '__' are reserved for EDAForge"
        base, k = name, 2
        while name in seen:
            name = f"{base}_{k}"
            k += 1
            reason = "another column has the same name"
        seen.add(name)
        out.append(name)
        if reason:
            issues.append(
                ParseIssue(
                    level="info",
                    code="column_renamed",
                    message=f"Column {i + 1} {original!r} was renamed to {name!r}: {reason}.",
                    column=name,
                )
            )
    return out


def _check_shape(n_rows: int, n_cols: int, limits: IngestLimits) -> None:
    if n_cols > limits.max_columns:
        msg = f"The table has {n_cols:,} columns; the maximum is {limits.max_columns:,}."
        raise IngestError(msg)
    if n_rows > limits.max_rows:
        msg = f"The table has {n_rows:,} rows; the maximum is {limits.max_rows:,}."
        raise IngestError(msg)
    if n_rows * max(n_cols, 1) > limits.max_cells:
        msg = f"The table has {n_rows * n_cols:,} cells; the maximum is {limits.max_cells:,}."
        raise IngestError(msg)


# ---------------------------------------------------------------- delimited text


def _decode_to_utf8(path: Path, scratch: Path, issues: list[ParseIssue]) -> Path:
    """Return a UTF-8 version of ``path`` (the file itself when it already is UTF-8)."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
        return path
    except UnicodeDecodeError:
        pass
    data = path.read_bytes()
    for encoding, label in (("cp1252", "Windows-1252"), ("latin-1", "Latin-1 (ISO-8859-1)")):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        target = scratch / "decoded.txt"
        target.write_text(text, encoding="utf-8")
        issues.append(
            ParseIssue(
                level="warning",
                code="encoding",
                message=(
                    f"The file is not UTF-8; it was decoded as {label}. Check accented characters "
                    "in the preview."
                ),
            )
        )
        return target
    # Unreachable in practice: latin-1 decodes every byte sequence.
    msg = "The file's text encoding could not be determined."  # pragma: no cover
    raise IngestError(msg)


def _sniff_delimiter(path: Path, default: str, issues: list[ParseIssue]) -> str:
    if default == "\t":
        return default
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(64 * 1024)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        return default
    if delimiter != default:
        label = {"\t": "tab", ";": "semicolon", "|": "pipe"}.get(delimiter, repr(delimiter))
        issues.append(
            ParseIssue(
                level="info", code="delimiter", message=f"Columns are separated by a {label}."
            )
        )
    return delimiter


def _scan_rows(path: Path, delimiter: str) -> tuple[list[str], int, list[int], list[int]]:
    """Header, data-row count, and data rows with too few / too many fields (1-based)."""
    short: list[int] = []
    long: list[int] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            return [], 0, [], []
        width = len(header)
        n = 0
        for row in reader:
            if not row:
                continue
            n += 1
            if len(row) < width:
                short.append(n)
            elif len(row) > width:
                long.append(n)
    return header, n, short, long


def _read_delimited(
    path: Path, fmt: FileFormat, scratch: Path, limits: IngestLimits
) -> list[RawTable]:
    issues: list[ParseIssue] = []
    source = _decode_to_utf8(path, scratch, issues)
    delimiter = _sniff_delimiter(source, "\t" if fmt == "tsv" else ",", issues)
    header, n_rows, short, long = _scan_rows(source, delimiter)
    if not header:
        msg = "The file is empty."
        raise IngestError(msg)
    _check_shape(n_rows, len(header), limits)
    if long:
        sample = ", ".join(str(r) for r in long[:10])
        msg = (
            f"{len(long):,} data rows have more fields than the header ({len(header)} columns), "
            f"for example rows {sample}. This usually means an unquoted delimiter inside a value. "
            "Fix those rows or quote the values, then upload again."
        )
        raise IngestError(msg)
    try:
        frame = pl.read_csv(
            source,
            separator=delimiter,
            has_header=True,
            infer_schema=False,
            quote_char='"',
            empty_string_is_null=False,
            raise_if_empty=False,
            encoding="utf8",
        )
    except pl.exceptions.PolarsError as exc:
        msg = f"The file could not be parsed as {fmt.upper()}: {str(exc).splitlines()[0]}"
        raise IngestError(msg) from exc
    if short:
        issues.append(
            ParseIssue(
                level="warning",
                code="short_rows",
                message=(
                    f"{len(short):,} rows have fewer fields than the header; their missing fields "
                    "are treated as missing values."
                ),
                count=len(short),
                rows=short[:20],
            )
        )
    if frame.height != n_rows:
        issues.append(
            ParseIssue(
                level="warning",
                code="row_count_check",
                message=(
                    f"The row scan counted {n_rows:,} data rows but the parser read "
                    f"{frame.height:,}. Blank lines or quoted line breaks can cause this; check "
                    "the preview."
                ),
            )
        )
    names = sanitize_names(header[: frame.width], issues)
    frame.columns = names
    return [RawTable(name="", frame=frame, original_names=header[: frame.width], issues=issues)]


# ---------------------------------------------------------------- Excel


def _check_zip(path: Path, limits: IngestLimits, issues: list[ParseIssue]) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
    except zipfile.BadZipFile as exc:
        msg = "The workbook is damaged or not a valid .xlsx file."
        raise IngestError(msg) from exc
    if len(members) > limits.max_xlsx_members:
        msg = f"The workbook contains {len(members):,} parts; this looks unsafe and was not opened."
        raise IngestError(msg)
    total = 0
    for info in members:
        total += info.file_size
        if (
            info.compress_size
            and info.file_size / info.compress_size > limits.max_xlsx_ratio
            and info.file_size > 10 * 1024 * 1024
        ):
            msg = (
                "The workbook expands to an unusually large size when unpacked "
                "(possible decompression bomb) and was not opened."
            )
            raise IngestError(msg)
        if ".." in info.filename or info.filename.startswith("/"):
            msg = "The workbook contains an unsafe internal path and was not opened."
            raise IngestError(msg)
    if total > limits.max_xlsx_uncompressed:
        msg = (
            f"The workbook unpacks to {total / 1e9:.1f} GB, above the "
            f"{limits.max_xlsx_uncompressed / 1e9:.1f} GB limit."
        )
        raise IngestError(msg)
    names = {m.filename.lower() for m in members}
    if any(n.endswith("vbaproject.bin") for n in names):
        issues.append(
            ParseIssue(
                level="warning",
                code="macros_ignored",
                message="The workbook contains macros. They were not run.",
            )
        )
    if any(n.startswith("xl/externallinks/") for n in names):
        issues.append(
            ParseIssue(
                level="info",
                code="external_links_ignored",
                message="The workbook links to other files. The links were not followed.",
            )
        )


def _cell_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return str(int(value))
    return str(value)


def _read_xlsx(path: Path, limits: IngestLimits) -> list[RawTable]:
    import openpyxl

    file_issues: list[ParseIssue] = []
    _check_zip(path, limits, file_issues)
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except Exception as exc:  # any parser failure becomes a readable error
        msg = f"The workbook could not be opened: {exc}"
        raise IngestError(msg) from exc
    tables: list[RawTable] = []
    skipped: list[str] = []
    try:
        for sheet in workbook.worksheets:
            issues = list(file_issues)
            rows: Iterator[tuple[Any, ...]] = sheet.iter_rows(values_only=True)
            header: list[Any] | None = None
            header_row = 0
            body: list[list[str | None]] = []
            for index, row in enumerate(rows, start=1):
                if header is None:
                    if any(v is not None and str(v).strip() for v in row):
                        header = list(row)
                        header_row = index
                    continue
                body.append([_cell_text(v) for v in row])
                if len(body) > limits.max_rows:
                    _check_shape(len(body), len(header), limits)
            if header is None:
                skipped.append(sheet.title)
                continue
            width = max(
                [i + 1 for i, v in enumerate(header) if v is not None and str(v).strip()]
                + [max((i + 1 for i, v in enumerate(r) if v is not None), default=0) for r in body]
            )
            while body and all(v is None or not v.strip() for v in body[-1][:width]):
                body.pop()
            _check_shape(len(body), width, limits)
            if header_row > 1:
                issues.append(
                    ParseIssue(
                        level="info",
                        code="header_row",
                        message=f"Column names were read from row {header_row} of the sheet.",
                    )
                )
            original = [_cell_text(v) or "" for v in header[:width]] + [""] * max(
                0, width - len(header)
            )
            names = sanitize_names(original, issues)
            columns = {
                name: [r[i] if i < len(r) else None for r in body] for i, name in enumerate(names)
            }
            frame = pl.DataFrame(columns, schema=dict.fromkeys(names, pl.String))
            if sheet.sheet_state != "visible":
                issues.append(
                    ParseIssue(level="info", code="hidden_sheet", message="This sheet is hidden.")
                )
            tables.append(
                RawTable(name=sheet.title, frame=frame, original_names=original, issues=issues)
            )
    finally:
        workbook.close()
    if not tables:
        msg = "The workbook has no sheets with data."
        raise IngestError(msg)
    if skipped:
        names = ", ".join(repr(n) for n in skipped)
        tables[0].issues.append(
            ParseIssue(
                level="info",
                code="empty_sheets",
                message=f"Sheets without data were not imported: {names}.",
            )
        )
    return tables


# ---------------------------------------------------------------- Parquet


def _read_parquet(path: Path, limits: IngestLimits) -> list[RawTable]:
    issues: list[ParseIssue] = []
    try:
        schema = pl.read_parquet_schema(path)
        n_rows = int(pl.scan_parquet(path).select(pl.len()).collect().item())
    except pl.exceptions.PolarsError as exc:
        msg = f"The Parquet file could not be read: {str(exc).splitlines()[0]}"
        raise IngestError(msg) from exc
    _check_shape(n_rows, len(schema), limits)
    try:
        frame = pl.read_parquet(path)
    except pl.exceptions.PolarsError as exc:
        msg = f"The Parquet file could not be read: {str(exc).splitlines()[0]}"
        raise IngestError(msg) from exc
    original = list(frame.columns)
    frame.columns = sanitize_names(original, issues)
    frame = _flatten(frame, issues)
    return [RawTable(name="", frame=frame, original_names=list(frame.columns), issues=issues)]


# ---------------------------------------------------------------- JSON


def _scalar_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _flatten_record(record: dict[str, Any], prefix: str, out: dict[str, Any]) -> None:
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            _flatten_record(value, f"{name}.", out)  # pyright: ignore[reportUnknownArgumentType]
        else:
            out[name] = value


def _records_to_frame(records: list[Any], issues: list[ParseIssue]) -> pl.DataFrame:
    flat: list[dict[str, Any]] = []
    nested = False
    lists = 0
    non_objects = 0
    for record in records:
        if not isinstance(record, dict):
            non_objects += 1
            flat.append({"value": record})
            continue
        row: dict[str, Any] = {}
        _flatten_record(record, "", row)  # pyright: ignore[reportUnknownArgumentType]
        nested = nested or any("." in k for k in row)
        lists += sum(1 for v in row.values() if isinstance(v, list))
        flat.append(row)
    names: dict[str, None] = {}
    for row in flat:
        for key in row:
            names.setdefault(key, None)
    columns = {name: [_scalar_text(row.get(name)) for row in flat] for name in names}
    if nested:
        issues.append(
            ParseIssue(
                level="info",
                code="flattened",
                message="Nested objects were flattened into columns named parent.child.",
            )
        )
    if lists:
        issues.append(
            ParseIssue(
                level="info",
                code="lists_as_text",
                message=f"{lists:,} list values were kept as JSON text.",
                count=lists,
            )
        )
    if non_objects:
        issues.append(
            ParseIssue(
                level="warning",
                code="non_object_records",
                message=f"{non_objects:,} records were not objects; they are in a column 'value'.",
                count=non_objects,
            )
        )
    return pl.DataFrame(columns, schema=dict.fromkeys(names, pl.String))


def _read_json(path: Path, limits: IngestLimits) -> list[RawTable]:
    issues: list[ParseIssue] = []
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except UnicodeDecodeError as exc:
        msg = "The JSON file is not UTF-8 text."
        raise IngestError(msg) from exc
    except json.JSONDecodeError as exc:
        msg = f"The file is not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}."
        raise IngestError(msg) from exc
    records: list[Any]
    if isinstance(data, list):
        records = data  # pyright: ignore[reportUnknownVariableType]
    elif isinstance(data, dict):
        lists: dict[str, list[Any]] = {
            k: v
            for k, v in data.items()  # pyright: ignore[reportUnknownVariableType]
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)  # pyright: ignore[reportUnknownVariableType]
        }
        if lists:
            key: str = max(lists, key=lambda k: len(lists[k]))
            records = lists[key]
            issues.append(
                ParseIssue(
                    level="info",
                    code="records_key",
                    message=f"Rows were read from the list under the key {key!r}.",
                )
            )
        elif data and all(isinstance(v, list) for v in data.values()):  # pyright: ignore[reportUnknownVariableType]
            lengths = {len(v) for v in data.values()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            if len(lengths) != 1:
                msg = "The JSON object holds columns of different lengths."
                raise IngestError(msg)
            n = lengths.pop()
            records = [{k: data[k][i] for k in data} for i in range(n)]  # pyright: ignore[reportUnknownVariableType]
            issues.append(
                ParseIssue(level="info", code="columnar_json", message="Read as column arrays.")
            )
        else:
            records = [data]
    else:
        msg = "The JSON file holds a single value, not a table."
        raise IngestError(msg)
    if not records:
        msg = "The JSON file contains no records."
        raise IngestError(msg)
    frame = _records_to_frame(records, issues)
    _check_shape(frame.height, frame.width, limits)
    original = list(frame.columns)
    frame.columns = sanitize_names(original, issues)
    return [RawTable(name="", frame=frame, original_names=original, issues=issues)]


def _read_jsonl(path: Path, limits: IngestLimits) -> list[RawTable]:
    issues: list[ParseIssue] = []
    records: list[Any] = []
    blank = 0
    with path.open("r", encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                blank += 1
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                msg = f"Line {number} is not valid JSON: {exc.msg} (column {exc.colno})."
                raise IngestError(msg) from exc
            if len(records) > limits.max_rows:
                _check_shape(len(records), 1, limits)
    if not records:
        msg = "The JSONL file contains no records."
        raise IngestError(msg)
    if blank:
        issues.append(
            ParseIssue(
                level="info", code="blank_lines", message=f"{blank:,} blank lines were skipped."
            )
        )
    frame = _records_to_frame(records, issues)
    _check_shape(frame.height, frame.width, limits)
    original = list(frame.columns)
    frame.columns = sanitize_names(original, issues)
    return [RawTable(name="", frame=frame, original_names=original, issues=issues)]


# ---------------------------------------------------------------- nested Parquet columns


def _flatten(frame: pl.DataFrame, issues: list[ParseIssue]) -> pl.DataFrame:
    changed = True
    while changed:
        changed = False
        for name, dtype in frame.schema.items():
            if isinstance(dtype, pl.Struct):
                fields = frame[name].struct.unnest()
                fields.columns = [f"{name}.{c}" for c in fields.columns]
                position = frame.columns.index(name)
                frame = pl.concat(
                    [frame[:, :position], fields, frame[:, position + 1 :]], how="horizontal"
                )
                issues.append(
                    ParseIssue(
                        level="info",
                        code="flattened",
                        message=f"Nested column {name!r} was split into columns {name}.*.",
                        column=name,
                    )
                )
                changed = True
                break
    for name, dtype in frame.schema.items():
        if isinstance(dtype, pl.List | pl.Array):
            frame = frame.with_columns(
                pl.col(name).map_elements(
                    lambda v: json.dumps(list(v), default=str), return_dtype=pl.String
                )
            )
            issues.append(
                ParseIssue(
                    level="info",
                    code="lists_as_text",
                    message="List values were kept as JSON text.",
                    column=name,
                )
            )
        elif isinstance(dtype, pl.Binary):
            frame = frame.with_columns(pl.col(name).bin.encode("hex"))
            issues.append(
                ParseIssue(
                    level="info",
                    code="binary_as_hex",
                    message="Binary values are shown as hexadecimal text.",
                    column=name,
                )
            )
        elif isinstance(dtype, pl.Categorical | pl.Enum):
            frame = frame.with_columns(pl.col(name).cast(pl.String))
        elif isinstance(dtype, pl.Decimal):
            frame = frame.with_columns(pl.col(name).cast(pl.Float64))
            issues.append(
                ParseIssue(
                    level="info",
                    code="decimal_as_float",
                    message="Decimal values were converted to floating-point numbers.",
                    column=name,
                )
            )
        elif isinstance(dtype, pl.Time | pl.Duration | pl.Object | pl.Null):
            frame = frame.with_columns(pl.col(name).cast(pl.String))
    return frame


def read_raw_tables(
    path: Path, fmt: FileFormat, scratch: Path, limits: IngestLimits
) -> list[RawTable]:
    size = path.stat().st_size
    if size > limits.max_bytes:
        msg = f"The file is {size / 1e6:.0f} MB; the maximum is {limits.max_bytes / 1e6:.0f} MB."
        raise IngestError(msg)
    if size == 0:
        msg = "The file is empty."
        raise IngestError(msg)
    from edaforge.ingest.databases import is_database, read_database

    if is_database(fmt):
        try:
            found = read_database(path, fmt, lambda n, c: _check_shape(n, c, limits))
        except ValueError as exc:
            raise IngestError(str(exc)) from exc
        out: list[RawTable] = []
        for name, frame, issues in found:
            original = list(frame.columns)
            frame.columns = sanitize_names(original, issues)
            out.append(RawTable(name=name, frame=frame, original_names=original, issues=issues))
        return out
    _check_magic(path, fmt)
    if fmt in {"csv", "tsv"}:
        return _read_delimited(path, fmt, scratch, limits)
    if fmt == "xlsx":
        return _read_xlsx(path, limits)
    if fmt == "parquet":
        return _read_parquet(path, limits)
    if fmt == "json":
        return _read_json(path, limits)
    return _read_jsonl(path, limits)
