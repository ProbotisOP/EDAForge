"""Clean-up recipes: explicit, recorded fixes that produce a new table, plus code that replays them.

A recipe is an ordered list of steps applied to one source table. Each step is chosen by the user
(the app only *suggests* steps for issues the profile found), reports exactly what it changed, and
keeps ``__row__`` so every cleaned row still points at its original row. Any value a step needs
(a median used to fill gaps, the mapping between spellings of a label) is computed once, when the
step is created, and stored in the step. Applying the recipe, here or in the exported Python or
SQL, therefore gives the same table every time.

Steps:

* ``drop_duplicates``: remove exact duplicate rows (all user columns equal), keeping the first;
* ``unify_labels``: replace spelling variants of a category (case, surrounding spaces) with one
  spelling, given as an explicit mapping;
* ``fill_missing``: fill empty cells of a column with a stored constant (the median or most common
  value at the time the step was made, or a value the user typed), optionally adding a
  ``<column>_was_missing`` flag so the filling stays visible to later analyses;
* ``drop_missing``: remove rows where a column is empty;
* ``scale``: multiply a numeric column by a power of ten (unit alignment), optionally only for
  rows where another column has a given value (for example one source file);
* ``drop_column``: remove a column.
"""

from __future__ import annotations

import json
import math
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, Field, field_validator

from edaforge.ingest import ROW_COLUMN, ColumnInfo

__all__ = ["CleanError", "Step", "apply_recipe", "recipe_python", "recipe_sql", "suggest_steps"]

StepKind = Literal[
    "drop_duplicates", "unify_labels", "fill_missing", "drop_missing", "scale", "drop_column"
]


class CleanError(ValueError):
    """A step that cannot be applied as given; the message is shown to the user."""


class Step(BaseModel):
    kind: StepKind
    column: str | None = None
    mapping: dict[str, str] = Field(default_factory=dict)  # unify_labels: variant -> spelling kept
    value: float | str | bool | None = None  # fill_missing constant
    value_source: str | None = (
        None  # how the constant was chosen ("median", "most common", "typed")
    )
    flag: bool = False  # fill_missing: add <column>_was_missing
    factor: float | None = None  # scale
    where_column: str | None = None  # scale: only where where_column == where_value
    where_value: str | None = None
    note: str = ""  # why the step was suggested

    @field_validator("factor")
    @classmethod
    def _power_of_ten(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v <= 0 or not math.isfinite(v) or abs(math.log10(v) - round(math.log10(v))) > 1e-9:
            msg = (
                "Scaling multiplies by a power of ten (for example 0.01, 100 or 1,000), "
                "which is a unit change."
            )
            raise ValueError(msg)
        return v


class StepEffect(BaseModel):
    step: Step
    summary: str
    rows_before: int
    rows_after: int
    cells_changed: int = 0
    rows_removed: list[int] = []  # original row numbers (first 20)


def _user(frame: pl.DataFrame) -> list[str]:
    return [c for c in frame.columns if not c.startswith("__")]


def _need(frame: pl.DataFrame, column: str | None) -> str:
    if not column or column not in frame.columns:
        msg = f"Unknown column {column!r}."
        raise CleanError(msg)
    return column


def _removed(before: pl.DataFrame, after: pl.DataFrame) -> list[int]:
    if ROW_COLUMN not in before.columns:
        return []
    gone = before.filter(~pl.col(ROW_COLUMN).is_in(after[ROW_COLUMN].implode()))
    return [int(v) for v in gone[ROW_COLUMN].head(20).to_list()]


def _apply(frame: pl.DataFrame, step: Step) -> tuple[pl.DataFrame, str, int]:
    """(new frame, plain summary, cells changed)."""
    if step.kind == "drop_duplicates":
        out = frame.unique(subset=_user(frame), keep="first", maintain_order=True)
        n = frame.height - out.height
        return (
            out,
            f"Removed {n:,} exact duplicate row{'s' if n != 1 else ''} (kept the first copy).",
            0,
        )
    column = _need(frame, step.column)
    if step.kind == "unify_labels":
        if not step.mapping:
            raise CleanError("Give at least one spelling to replace.")
        col = pl.col(column).cast(pl.String)
        changed = int(frame.select(col.is_in(list(step.mapping)).sum()).item())
        out = frame.with_columns(col.replace(step.mapping).alias(column))
        pairs = ", ".join(f"'{k}' → '{v}'" for k, v in list(step.mapping.items())[:6])
        return (
            out,
            f"{column}: replaced {changed:,} label{'s' if changed != 1 else ''} ({pairs}).",
            changed,
        )
    if step.kind == "fill_missing":
        if step.value is None:
            raise CleanError("Choose the value to fill in.")
        missing = int(frame[column].null_count())
        dtype = frame.schema[column]
        try:
            fill = pl.lit(step.value).cast(dtype, strict=True)
            out = frame.with_columns(
                *([pl.col(column).is_null().alias(f"{column}_was_missing")] if step.flag else []),
                pl.col(column).fill_null(fill),
            )
        except pl.exceptions.PolarsError as exc:
            msg = f"{step.value!r} does not fit the type of {column} ({dtype})."
            raise CleanError(msg) from exc
        src = f" ({step.value_source})" if step.value_source else ""
        flag = f"; {column}_was_missing marks the filled rows" if step.flag else ""
        return (
            out,
            (
                f"{column}: filled {missing:,} empty cell{'s' if missing != 1 else ''} with "
                f"{step.value}{src}{flag}."
            ),
            missing,
        )
    if step.kind == "drop_missing":
        out = frame.filter(pl.col(column).is_not_null())
        n = frame.height - out.height
        return out, f"Removed {n:,} row{'s' if n != 1 else ''} where {column} is empty.", 0
    if step.kind == "scale":
        if step.factor is None:
            raise CleanError("Choose the factor.")
        expr = pl.col(column).cast(pl.Float64) * step.factor
        cond = None
        if step.where_column:
            _need(frame, step.where_column)
            cond = pl.col(step.where_column).cast(pl.String) == str(step.where_value)
            expr = pl.when(cond).then(expr).otherwise(pl.col(column).cast(pl.Float64))
        changed = int(
            frame.select(
                (pl.col(column).is_not_null() & (cond if cond is not None else pl.lit(True))).sum()
            ).item()
        )
        out = frame.with_columns(expr.alias(column))
        where = f" where {step.where_column} = '{step.where_value}'" if step.where_column else ""
        return (
            out,
            (
                f"{column}: multiplied {changed:,} value{'s' if changed != 1 else ''} by "
                f"{step.factor:g}{where}."
            ),
            changed,
        )
    if step.kind == "drop_column":
        return frame.drop(column), f"Removed the column {column}.", 0
    msg = f"Unknown step {step.kind}."
    raise CleanError(msg)


def apply_recipe(frame: pl.DataFrame, steps: list[Step]) -> tuple[pl.DataFrame, list[StepEffect]]:
    effects: list[StepEffect] = []
    for step in steps:
        out, summary, cells = _apply(frame, step)
        effects.append(
            StepEffect(
                step=step,
                summary=summary,
                rows_before=frame.height,
                rows_after=out.height,
                cells_changed=cells,
                rows_removed=_removed(frame, out),
            )
        )
        frame = out
    return frame, effects


# ---------------------------------------------------------------- suggestions


def _variants(series: pl.Series) -> dict[str, str]:
    """Spellings that differ only in case or surrounding spaces -> the most common spelling."""
    counts = series.drop_nulls().cast(pl.String).value_counts(sort=True)
    keep: dict[str, str] = {}
    mapping: dict[str, str] = {}
    for value, _ in counts.iter_rows():
        key = str(value).strip().casefold()
        if key in keep:
            mapping[str(value)] = keep[key]
        else:
            keep[key] = str(value)
    return mapping


def suggest_steps(frame: pl.DataFrame, columns: list[ColumnInfo]) -> list[Step]:
    """Fixes for problems found in the data. Suggestions only: nothing is applied."""
    out: list[Step] = []
    user = _user(frame)
    dups = frame.height - frame.select(user).n_unique() if user else 0
    if dups:
        out.append(
            Step(kind="drop_duplicates", note=f"{dups:,} rows are exact copies of another row.")
        )
    for info in columns:
        name = info.name
        if name not in frame.columns:
            continue
        s = frame[name]
        if info.role in {"categorical", "boolean", "identifier"} and s.dtype == pl.String:
            mapping = _variants(s)
            if mapping:
                out.append(
                    Step(
                        kind="unify_labels",
                        column=name,
                        mapping=mapping,
                        note=(
                            f"{len(mapping)} label{'s are' if len(mapping) > 1 else ' is'} "
                            f"the same as another except for case or spaces."
                        ),
                    )
                )
        nulls = s.null_count()
        if nulls == frame.height and frame.height:
            out.append(
                Step(kind="drop_column", column=name, note="the column is completely empty.")
            )
        elif nulls and info.role == "numeric" and s.dtype.is_numeric():
            med = s.drop_nulls().median()
            if isinstance(med, (int, float)):
                value = float(med)
                if s.dtype.is_integer() and value.is_integer():
                    value = int(value)
                out.append(
                    Step(
                        kind="fill_missing",
                        column=name,
                        value=value,
                        value_source="median",
                        flag=True,
                        note=(
                            f"{nulls:,} empty cells ({nulls / frame.height:.1%}). Filling "
                            f"changes distributions; the flag keeps it visible."
                        ),
                    )
                )
        elif nulls and info.role in {"categorical", "boolean"}:
            top = s.drop_nulls().cast(pl.String).value_counts(sort=True)
            if top.height:
                out.append(
                    Step(
                        kind="fill_missing",
                        column=name,
                        value="(missing)",
                        value_source="explicit label",
                        note=(
                            f"{nulls:,} empty cells ({nulls / frame.height:.1%}); an "
                            f"explicit '(missing)' label keeps them as their own group."
                        ),
                    )
                )
    return out


# ---------------------------------------------------------------- code export


def _py(value: Any) -> str:
    return json.dumps(value) if not isinstance(value, bool) else ("True" if value else "False")


def recipe_python(steps: list[Step], *, source: str, types: dict[str, str] | None = None) -> str:
    """A self-contained polars script that replays the recipe on the original file.

    ``types`` (column -> EDAForge dtype) makes ``read`` give each column the type the app read
    it as (for example yes/no as true/false), so ``clean(read(path))`` matches the app's table.
    """
    lines = [
        '"""Clean-up recipe exported by EDAForge.',
        "",
        f"Source: {source}",
        (
            "Replays the fixes in order. Values such as fill-ins and label mappings were "
            "fixed when each"
        ),
        'step was created, so this gives the same table as the app."""',
        "",
        "import sys",
        "",
        "import polars as pl",
        "",
        f"TYPES = {json.dumps(types or {})}",
        '_TRUE, _FALSE = ["true", "yes", "y", "t"], ["false", "no", "n", "f"]',
        "",
        "",
        "def read(path: str) -> pl.DataFrame:",
        '    """Read a CSV and give each column the type EDAForge read it as."""',
        "    df = pl.read_csv(path, try_parse_dates=True, infer_schema_length=None)",
        "    for name, kind in TYPES.items():",
        "        if name not in df.columns:",
        "            continue",
        "        col, dtype = pl.col(name), df.schema[name]",
        '        if kind == "boolean" and dtype == pl.String:',
        "            low = col.str.strip_chars().str.to_lowercase()",
        (
            "            df = "
            "df.with_columns(pl.when(low.is_in(_TRUE)).then(True).when(low.is_in(_FALSE)).then(False).otherwise(None).alias(name))"
        ),
        '        elif kind == "integer":',
        "            df = df.with_columns(col.cast(pl.Int64, strict=False))",
        '        elif kind == "float":',
        "            df = df.with_columns(col.cast(pl.Float64, strict=False))",
        '        elif kind == "date" and dtype == pl.String:',
        "            df = df.with_columns(col.str.to_date(strict=False))",
        '        elif kind == "datetime" and dtype == pl.String:',
        "            df = df.with_columns(col.str.to_datetime(strict=False))",
        '        elif kind == "string":',
        "            df = df.with_columns(col.cast(pl.String))",
        "    return df",
        "",
        "",
        "def clean(df: pl.DataFrame) -> pl.DataFrame:",
    ]
    for i, step in enumerate(steps, 1):
        c = _py(step.column)
        lines.append(f"    # {i}. {step.kind}{' — ' + step.note if step.note else ''}")
        if step.kind == "drop_duplicates":
            lines.append(
                "    df = df.unique(subset=[c for c in df.columns if not "
                'c.startswith("__")], keep="first", maintain_order=True)'
            )
        elif step.kind == "unify_labels":
            lines.append(
                f"    df = "
                f"df.with_columns(pl.col({c}).cast(pl.String).replace({_py(step.mapping)}).alias({c}))"
            )
        elif step.kind == "fill_missing":
            if step.flag:
                lines.append(
                    f"    df = "
                    f"df.with_columns(pl.col({c}).is_null().alias({_py(f'{step.column}_was_missing')}))"
                )
            lines.append(
                f"    df = "
                f"df.with_columns(pl.col({c}).fill_null(pl.lit({_py(step.value)}).cast(df.schema[{c}])))"
            )
        elif step.kind == "drop_missing":
            lines.append(f"    df = df.filter(pl.col({c}).is_not_null())")
        elif step.kind == "scale":
            scaled = f"pl.col({c}).cast(pl.Float64) * {step.factor!r}"
            if step.where_column:
                cond = (
                    f"pl.col({_py(step.where_column)}).cast(pl.String) == "
                    f"{_py(str(step.where_value))}"
                )
                scaled = f"pl.when({cond}).then({scaled}).otherwise(pl.col({c}).cast(pl.Float64))"
            lines.append(f"    df = df.with_columns(({scaled}).alias({c}))")
        elif step.kind == "drop_column":
            lines.append(f"    df = df.drop({c})")
    lines += [
        "    return df",
        "",
        "",
        'if __name__ == "__main__":',
        "    # usage: python recipe.py input.csv output.csv",
        "    clean(read(sys.argv[1])).write_csv(sys.argv[2])",
        "",
    ]
    return "\n".join(lines)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def recipe_sql(
    steps: list[Step],
    columns: list[str],
    *,
    source: str = "source_table",
    types: dict[str, str] | None = None,
) -> str:
    """The recipe as one standard SQL query (CTEs). ``columns`` are the source table's columns.

    Written in portable SQL (CASE, COALESCE, ROW_NUMBER); duplicate removal keeps the first row by
    ``__row__`` when the table has it.
    """
    cols = list(columns)
    ctes: list[str] = []
    prev = source
    for i, step in enumerate(steps, 1):
        name = f"step_{i}"
        c = step.column or ""
        if step.kind == "drop_duplicates":
            user = [x for x in cols if not x.startswith("__")]
            order = _q(ROW_COLUMN) if ROW_COLUMN in cols else "1"
            part = ", ".join(_q(x) for x in user)
            ctes.append(
                f"{name} AS (\n  SELECT {', '.join(_q(x) for x in cols)} FROM (\n"
                f"    SELECT *, ROW_NUMBER() OVER (PARTITION BY {part} ORDER BY {order}) AS "
                f"__dup_rank FROM {prev}\n"
                f"  ) AS d WHERE __dup_rank = 1\n)"
            )
        elif step.kind == "unify_labels":
            whens = " ".join(
                f"WHEN {_q(c)} = {_lit(k)} THEN {_lit(v)}" for k, v in step.mapping.items()
            )
            sel = [f"CASE {whens} ELSE {_q(c)} END AS {_q(c)}" if x == c else _q(x) for x in cols]
            ctes.append(f"{name} AS (SELECT {', '.join(sel)} FROM {prev})")
        elif step.kind == "fill_missing":
            sel = [
                f"COALESCE({_q(c)}, {_lit(step.value)}) AS {_q(c)}" if x == c else _q(x)
                for x in cols
            ]
            if step.flag:
                flag = f"{c}_was_missing"
                sel.append(f"({_q(c)} IS NULL) AS {_q(flag)}")
                cols = [*cols, flag]
            ctes.append(f"{name} AS (SELECT {', '.join(sel)} FROM {prev})")
        elif step.kind == "drop_missing":
            ctes.append(
                f"{name} AS (SELECT {', '.join(_q(x) for x in cols)} FROM {prev} WHERE "
                f"{_q(c)} IS NOT NULL)"
            )
        elif step.kind == "scale":
            scaled = f"CAST({_q(c)} AS DOUBLE) * {step.factor!r}"
            if step.where_column:
                scaled = (
                    f"CASE WHEN CAST({_q(step.where_column)} AS VARCHAR) = "
                    f"{_lit(str(step.where_value))} THEN {scaled} ELSE CAST({_q(c)} AS DOUBLE) END"
                )
            sel = [f"{scaled} AS {_q(c)}" if x == c else _q(x) for x in cols]
            ctes.append(f"{name} AS (SELECT {', '.join(sel)} FROM {prev})")
        elif step.kind == "drop_column":
            cols = [x for x in cols if x != c]
            ctes.append(f"{name} AS (SELECT {', '.join(_q(x) for x in cols)} FROM {prev})")
        prev = name
    head = (
        "-- Clean-up recipe exported by EDAForge.\n"
        "-- Replace source_table with your table. Values were fixed when each step was created.\n"
    )
    if types:
        head += (
            "-- It gives the app's table when source_table has these column types "
            "(as EDAForge read the file):\n"
        )
        boolean = " (yes/no, true/false, y/n, t/f as BOOLEAN)"
        head += "".join(
            f"--   {name}: {kind}{boolean if kind == 'boolean' else ''}\n"
            for name, kind in types.items()
        )
    if not ctes:
        return head + f"SELECT * FROM {source};\n"
    return head + "WITH " + ",\n".join(ctes) + f"\nSELECT * FROM {prev};\n"
