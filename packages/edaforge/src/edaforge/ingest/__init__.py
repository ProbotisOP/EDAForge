"""Upload ingestion: read a file, type its columns and describe every change made.

:func:`ingest_file` turns one uploaded file into one or more typed tables (an Excel workbook
yields one table per sheet with data). Each table gets a ``__row__`` column with the 1-based row
number in the source, so every result can be traced back to the original records.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from edaforge.ingest.infer import (
    ColumnInfo,
    DType,
    ParseIssue,
    Role,
    detect_pii,
    infer_role,
    type_column,
)
from edaforge.ingest.readers import (
    FORMATS,
    FileFormat,
    IngestError,
    IngestLimits,
    RawTable,
    detect_format,
    read_raw_tables,
)

__all__ = [
    "FORMATS",
    "ROW_COLUMN",
    "ColumnInfo",
    "FileFormat",
    "IngestError",
    "IngestLimits",
    "ParseIssue",
    "ParsedTable",
    "Role",
    "detect_format",
    "ingest_file",
    "is_internal",
]

ROW_COLUMN = "__row__"


def is_internal(name: str) -> bool:
    """Columns EDAForge adds for traceability (``__row__``, ``__source__``, ...)."""
    return name.startswith("__")


@dataclass
class ParsedTable:
    sheet: str
    frame: pl.DataFrame  # typed; ``__row__`` first
    columns: list[ColumnInfo]
    issues: list[ParseIssue]


def _dtype_label(dtype: pl.DataType) -> DType | None:
    if dtype == pl.Boolean:
        return "boolean"
    if dtype.is_integer():
        return "integer"
    if dtype.is_float():
        return "float"
    if dtype == pl.Date:
        return "date"
    if isinstance(dtype, pl.Datetime):
        return "datetime"
    return None


def _type_table(raw: RawTable) -> ParsedTable:
    issues = list(raw.issues)
    n = raw.frame.height
    row_numbers = pl.Series(ROW_COLUMN, range(1, n + 1), dtype=pl.Int64)
    typed: list[pl.Series] = [row_numbers]
    columns: list[ColumnInfo] = []
    for position, name in enumerate(raw.frame.columns):
        series = raw.frame[name]
        label = _dtype_label(series.dtype)
        n_invalid = 0
        note: str | None = None
        if label is None:
            series = series.cast(pl.String)
            series, label, column_issues, n_invalid, note = type_column(name, series, row_numbers)
            issues.extend(column_issues)
        elif label == "float":
            bad = series.is_not_null() & ~series.is_finite()
            n_invalid = int(bad.sum())
            if n_invalid:
                issues.append(
                    ParseIssue(
                        level="warning",
                        code="non_finite",
                        message=(
                            f"{n_invalid} values are NaN or infinite; they are treated as missing."
                        ),
                        column=name,
                        count=n_invalid,
                    )
                )
                series = pl.select(pl.when(bad).then(None).otherwise(series)).to_series()
            series = series.cast(pl.Float64)
        elif label == "integer":
            if series.dtype == pl.UInt64 and int(series.max() or 0) >= 2**63:  # pyright: ignore[reportArgumentType]
                series = series.cast(pl.Float64)
                label = "float"
            else:
                series = series.cast(pl.Int64)
        elif label == "datetime":
            dtype = series.dtype
            if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None:
                series = series.dt.convert_time_zone("UTC").dt.replace_time_zone(None)
                note = "converted to UTC"
            series = series.cast(pl.Datetime("us"))
        series = series.alias(name)
        role, reason = infer_role(name, series, label)
        pii = detect_pii(name, series, label, role)
        original = raw.original_names[position] if position < len(raw.original_names) else name
        columns.append(
            ColumnInfo(
                name=name,
                original_name=original,
                dtype=label,
                role=role,
                role_reason=reason,
                pii=pii,
                n_missing=int(series.null_count()),
                n_invalid=n_invalid,
                parse_note=note,
            )
        )
        typed.append(series)
    frame = pl.DataFrame(typed)
    return ParsedTable(sheet=raw.name, frame=frame, columns=columns, issues=issues)


def ingest_file(
    path: Path, *, filename: str, scratch: Path, limits: IngestLimits | None = None
) -> tuple[FileFormat, list[ParsedTable]]:
    """Read and type ``path``; ``filename`` (untrusted) is used only to pick the format."""
    fmt = detect_format(filename)
    raws = read_raw_tables(path, fmt, scratch, limits or IngestLimits())
    tables = [_type_table(raw) for raw in raws]
    if all(t.frame.height == 0 for t in tables):
        msg = "The file has column names but no data rows."
        raise IngestError(msg)
    return fmt, tables
