"""Column typing, semantic roles and PII hints for uploaded tables.

Every change to a value is recorded as a :class:`ParseIssue`: placeholder tokens read as missing,
values that could not be parsed, thousands separators or currency symbols removed, dates read
with a format. Nothing is coerced silently (PROJECT_PROMPT.md section 6, "Data handling").

Roles decide how the discovery engine may use a column. Identifiers, codes and timestamps are
never treated as numeric measurements (section 12, anti-pattern 8); the user can override a role.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import time
from typing import Literal, cast

import polars as pl

from edaforge.models import Contract

__all__ = [
    "NA_TOKENS",
    "ColumnInfo",
    "DType",
    "ParseIssue",
    "Role",
    "detect_pii",
    "infer_role",
    "type_column",
]

Role = Literal["numeric", "categorical", "boolean", "datetime", "identifier", "text", "empty"]
DType = Literal["integer", "float", "boolean", "date", "datetime", "string"]

# Cell contents read as "missing" when the rest of the column parses as numbers or dates.
NA_TOKENS: frozenset[str] = frozenset(
    {
        "",
        "na",
        "n/a",
        "nan",
        "null",
        "none",
        "nil",
        "-",
        "--",
        "?",
        "#n/a",
        "#null!",
        "missing",
        ".",
    }
)
_PARSE_SHARE = 0.95  # share of present values that must parse for a column to take a type
_MAX_EXAMPLES = 5
_MAX_ROWS = 20


class ParseIssue(Contract):
    level: Literal["error", "warning", "info"]
    code: str
    message: str
    column: str | None = None
    count: int | None = None
    examples: list[str] = []
    rows: list[int] = []  # 1-based data-row numbers, a sample


class ColumnInfo(Contract):
    name: str
    original_name: str
    dtype: DType
    role: Role
    role_reason: str
    role_source: Literal["inferred", "user"] = "inferred"
    pii: str | None = None
    n_missing: int
    n_invalid: int = 0  # values that could not be read as ``dtype``; they are now missing
    parse_note: str | None = None


def _share(mask: pl.Series) -> float:
    """Share of true values in a boolean series (0.0 when it is empty)."""
    return float(cast("float | None", mask.mean()) or 0.0)


def _examples(values: pl.Series) -> list[str]:
    out: list[str] = []
    for value in values.drop_nulls().unique(maintain_order=True).head(_MAX_EXAMPLES).to_list():
        text = str(value)
        out.append(text if len(text) <= 40 else text[:37] + "...")
    return out


def _rows(mask: pl.Series, row_numbers: pl.Series) -> list[int]:
    return [int(r) for r in row_numbers.filter(mask).head(_MAX_ROWS).to_list()]


# ---------------------------------------------------------------- string columns

_NUMBER_FORMATTED = r"^[+-]?[$€£¥]?\s?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?\s?%?$"
_LEADING_ZERO = r"^[+-]?0\d"
_INTEGER_TEXT = r"^[+-]?\d+$"

_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%m/%d/%y",
    "%d/%m/%y",
    "%b %d, %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%d %B %Y",
)
_DATETIME_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S%.f",
    "%Y-%m-%dT%H:%M:%S%.f",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
)
_TZ_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S%.f%z",
)
_DAY_FIRST = {"%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"}
_MONTH_FIRST = {"%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"}
_DATE_LIKE = re.compile(
    r"^(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} "
    r"[A-Za-z]{3,9}\.? \d{4})"
)


def _format_label(fmt: str) -> str:
    return (
        fmt.replace("%Y", "YYYY")
        .replace("%y", "YY")
        .replace("%m", "MM")
        .replace("%d", "DD")
        .replace("%H", "hh")
        .replace("%M", "mm")
        .replace("%S", "ss")
        .replace("%.f", ".fff")
        .replace("%z", "±hh:mm")
        .replace("%b", "Mon")
        .replace("%B", "Month")
    )


def _try_dates(present: pl.Series) -> tuple[str, str, int, bool] | None:
    """Best (format, kind, parsed count, ambiguous day/month) among the known formats."""
    sample = present.head(5000)
    looks = sample.map_elements(lambda v: bool(_DATE_LIKE.match(v)), return_dtype=pl.Boolean)
    if looks.mean() is None or float(looks.mean()) < _PARSE_SHARE:  # pyright: ignore[reportArgumentType]
        return None
    scores: list[tuple[int, str, str]] = []
    for fmt in _DATE_FORMATS:
        n = int(present.str.to_date(fmt, strict=False).is_not_null().sum())
        scores.append((n, fmt, "date"))
    for fmt in _DATETIME_FORMATS:
        n = int(present.str.to_datetime(fmt, strict=False).is_not_null().sum())
        scores.append((n, fmt, "datetime"))
    for fmt in _TZ_FORMATS:
        try:
            parsed = present.str.to_datetime(fmt, strict=False, time_zone="UTC")
        except pl.exceptions.PolarsError:
            continue
        scores.append((int(parsed.is_not_null().sum()), fmt, "datetime_tz"))
    best = max(scores, key=lambda s: s[0])
    if best[0] < _PARSE_SHARE * present.len():
        return None
    tied = {fmt for n, fmt, _ in scores if n == best[0]}
    ambiguous = bool(tied & _DAY_FIRST) and bool(tied & _MONTH_FIRST)
    fmt = best[1]
    if ambiguous:
        # Prefer month-first (the more common export convention) and say so.
        fmt = next(f for n, f, _ in scores if n == best[0] and f in _MONTH_FIRST)
    kind = next(k for n, f, k in scores if f == fmt and n == best[0])
    return fmt, kind, best[0], ambiguous


def type_column(
    name: str, raw: pl.Series, row_numbers: pl.Series
) -> tuple[pl.Series, DType, list[ParseIssue], int, str | None]:
    """Type a column read as text. Returns (typed series, dtype, issues, n_invalid, parse note)."""
    issues: list[ParseIssue] = []
    stripped = raw.str.strip_chars()
    lower = stripped.str.to_lowercase()
    token = lower.is_in(list(NA_TOKENS)) & stripped.is_not_null()
    present_mask = stripped.is_not_null() & ~token
    present = stripped.filter(present_mask)
    n_present = present.len()
    if n_present == 0:
        return raw.alias(name), "string", issues, 0, None

    def placeholder_issue() -> None:
        named = token & (lower != "")
        count = int(named.sum())
        if count:
            issues.append(
                ParseIssue(
                    level="info",
                    code="placeholder_as_missing",
                    message=(
                        f"{count} cells contained a missing-value placeholder and are treated as "
                        "missing."
                    ),
                    column=name,
                    count=count,
                    examples=_examples(stripped.filter(named)),
                )
            )

    def invalid_issue(mask: pl.Series, what: str) -> int:
        count = int(mask.sum())
        if count:
            issues.append(
                ParseIssue(
                    level="warning",
                    code="unparseable_values",
                    message=(
                        f"{count} values could not be read as {what}; they are treated as missing "
                        "in the analysis (the original file is unchanged)."
                    ),
                    column=name,
                    count=count,
                    examples=_examples(stripped.filter(mask)),
                    rows=_rows(mask, row_numbers),
                )
            )
        return count

    # Booleans: every present value is one of a known pair.
    values = set(present.str.to_lowercase().unique().to_list())
    for pair in ({"true", "false"}, {"yes", "no"}, {"y", "n"}, {"t", "f"}):
        if values <= pair:
            typed = (
                pl.when(present_mask)
                .then(lower.is_in(["true", "yes", "y", "t"]))
                .otherwise(None)
                .alias(name)
            )
            series = pl.select(typed).to_series()
            placeholder_issue()
            return series, "boolean", issues, 0, f"read {'/'.join(sorted(pair))} as true/false"

    # Numbers.
    cleaned_full = pl.select(pl.when(present_mask).then(stripped).otherwise(None)).to_series()
    as_float = cleaned_full.cast(pl.Float64, strict=False)
    finite = as_float.is_not_null() & as_float.is_finite()
    rate = float(finite.sum()) / n_present
    note: str | None = None
    if rate < _PARSE_SHARE:
        formatted = present.str.contains(_NUMBER_FORMATTED)
        if bool(present.str.contains(r"[,$€£¥%]").any()):
            cleaned_rate = (
                float(
                    present.filter(formatted).len()
                    + (~formatted & present.cast(pl.Float64, strict=False).is_not_null()).sum()
                )
                / n_present
            )
        else:
            cleaned_rate = 0.0
        if cleaned_rate >= _PARSE_SHARE:
            cleaned_full = cleaned_full.str.replace_all(r"[,$€£¥%\s]", "")
            as_float = cleaned_full.cast(pl.Float64, strict=False)
            finite = as_float.is_not_null() & as_float.is_finite()
            rate = float(finite.sum()) / n_present
            removed = [
                label
                for pattern, label in (
                    (",", "thousands separators"),
                    (r"[$€£¥]", "currency symbols"),
                    ("%", "percent signs (values stay in percent units)"),
                )
                if bool(present.str.contains(pattern).any())
            ]
            note = "removed " + ", ".join(removed)
            issues.append(
                ParseIssue(
                    level="info",
                    code="number_formatting_removed",
                    message=f"Read as numbers after removing {', '.join(removed)}.",
                    column=name,
                    examples=_examples(present.filter(present.str.contains(r"[,$€£¥%]"))),
                )
            )
    if rate >= _PARSE_SHARE:
        leading = present.str.contains(_LEADING_ZERO)
        if bool(leading.any()) and _share(leading) >= 0.01:
            issues.append(
                ParseIssue(
                    level="info",
                    code="kept_as_text_leading_zeros",
                    message=(
                        "Kept as text because some values have leading zeros (codes such as ZIP "
                        "codes or IDs lose information when read as numbers)."
                    ),
                    column=name,
                    examples=_examples(present.filter(leading)),
                )
            )
            placeholder_issue()
            return cleaned_full.alias(name), "string", issues, 0, "kept as text (leading zeros)"
        invalid = present_mask & ~finite
        placeholder_issue()
        n_invalid = invalid_issue(invalid, "numbers")
        integral_text = cleaned_full.filter(finite).str.contains(_INTEGER_TEXT)
        max_abs = as_float.filter(finite).abs().max()
        if bool(integral_text.all()) and max_abs is not None and float(max_abs) < 2**53:  # pyright: ignore[reportArgumentType]
            typed = (
                pl.select(pl.when(finite).then(as_float).otherwise(None)).to_series().cast(pl.Int64)
            )
            return typed.alias(name), "integer", issues, n_invalid, note
        typed = pl.select(pl.when(finite).then(as_float).otherwise(None)).to_series()
        return typed.alias(name), "float", issues, n_invalid, note

    # Dates and timestamps.
    found = _try_dates(present)
    if found is not None:
        fmt, kind, _, ambiguous = found
        if kind == "date":
            parsed = cleaned_full.str.to_date(fmt, strict=False)
        elif kind == "datetime":
            parsed = cleaned_full.str.to_datetime(fmt, strict=False, time_unit="us")
        else:
            parsed = cleaned_full.str.to_datetime(
                fmt, strict=False, time_zone="UTC", time_unit="us"
            ).dt.replace_time_zone(None)
        invalid = present_mask & parsed.is_null()
        placeholder_issue()
        n_invalid = invalid_issue(invalid, f"dates in the format {_format_label(fmt)}")
        note = f"dates read with the format {_format_label(fmt)}"
        if kind == "datetime_tz":
            note += "; converted to UTC"
        if ambiguous:
            issues.append(
                ParseIssue(
                    level="warning",
                    code="ambiguous_date_format",
                    message=(
                        "Every date in this column could be read as month/day or as day/month; "
                        f"it was read as {_format_label(fmt)}. Check that this is right."
                    ),
                    column=name,
                    examples=_examples(present),
                )
            )
        dtype: DType = "date" if kind == "date" else "datetime"
        if dtype == "datetime":
            valid = parsed.drop_nulls()
            if valid.len() and bool((valid.dt.time() == time(0, 0)).all()):
                parsed = parsed.dt.date()
                dtype = "date"
                note += "; every time was midnight, so the column holds dates"
        return parsed.alias(name), dtype, issues, n_invalid, note

    if rate < _PARSE_SHARE and bool(present.str.contains(r"[,$€£¥%]").any()):
        rate = max(rate, _share(present.str.contains(_NUMBER_FORMATTED)))
        finite = cleaned_full.str.contains(_NUMBER_FORMATTED).fill_null(False) | finite
    if 0.5 <= rate < _PARSE_SHARE:
        bad = present_mask & ~finite
        issues.append(
            ParseIssue(
                level="warning",
                code="mixed_types",
                message=(
                    f"{rate:.0%} of the values are numbers but the rest are text, so the column "
                    "was kept as text. Fix the text values to analyze it as a number."
                ),
                column=name,
                count=int(bad.sum()),
                examples=_examples(stripped.filter(bad)),
                rows=_rows(bad, row_numbers),
            )
        )
    named_tokens = token & (lower != "")
    if bool(named_tokens.any()):
        issues.append(
            ParseIssue(
                level="info",
                code="possible_placeholder",
                message=(
                    f"{int(named_tokens.sum())} cells look like missing-value placeholders; they "
                    "were kept as text because the column holds text."
                ),
                column=name,
                count=int(named_tokens.sum()),
                examples=_examples(stripped.filter(named_tokens)),
            )
        )
    whitespace = raw.is_not_null() & (raw != stripped)
    if bool(whitespace.any()):
        issues.append(
            ParseIssue(
                level="info",
                code="whitespace_trimmed",
                message=f"{int(whitespace.sum())} values had leading or trailing spaces, trimmed.",
                column=name,
                count=int(whitespace.sum()),
            )
        )
    empty_strings = raw.is_not_null() & (stripped == "")
    typed = pl.select(pl.when(empty_strings).then(None).otherwise(stripped)).to_series()
    return typed.alias(name), "string", issues, 0, None


# ---------------------------------------------------------------- roles

_ID_SNAKE = re.compile(
    r"(^|[_\s.\-])(id|uuid|guid|key|pk|fk|sku|ref|nr|no|num|number|code)$", re.IGNORECASE
)
_ID_PREFIX = re.compile(r"^(id|uuid|guid)([_\s.\-]|$)", re.IGNORECASE)
_ID_CAMEL = re.compile(r"[a-z0-9](ID|Id)$")
_CODE_NAME = re.compile(r"(code|zip|postal|postcode)", re.IGNORECASE)
_CATEGORY_NAME = re.compile(
    r"(type|category|cat|class|group|segment|region|status|level|tier|cluster|kind|flag|label|"
    r"gender|sex|state|country|channel|plan)",
    re.IGNORECASE,
)


def _id_name(name: str) -> bool:
    return bool(_ID_SNAKE.search(name) or _ID_PREFIX.search(name) or _ID_CAMEL.search(name))


def infer_role(name: str, series: pl.Series, dtype: DType) -> tuple[Role, str]:
    """How the analysis may use a column, with the reason shown to the user."""
    present = series.drop_nulls()
    n = present.len()
    if n == 0:
        return "empty", "every value is missing"
    n_distinct = present.n_unique()
    if dtype == "boolean":
        return "boolean", "true/false values"
    if dtype in {"date", "datetime"}:
        return "datetime", "dates or timestamps"
    if dtype in {"integer", "float"}:
        integral = dtype == "integer" or bool((present.cast(pl.Float64) % 1 == 0).all())
        if integral and _id_name(name):
            return "identifier", "the name suggests an identifier, so it is not used as a number"
        if integral and n >= 20 and n_distinct == n:
            span = float(present.max() - present.min()) + 1.0  # pyright: ignore[reportOperatorIssue, reportArgumentType]
            if span <= 1.05 * n:
                return (
                    "identifier",
                    "unique, consecutive whole numbers: looks like a row number or ID",
                )
        if n_distinct <= 2:
            levels = {float(v) for v in present.unique().to_list()}
            if levels <= {0.0, 1.0} or n >= 30:
                return "boolean", "only two distinct values: treated as a yes/no indicator"
        if integral and n_distinct <= 12 and _CATEGORY_NAME.search(name):
            return "categorical", "few whole-number codes and the name suggests a category"
        if integral and _CODE_NAME.search(name):
            return "categorical" if n_distinct <= 50 else "identifier", (
                "the name suggests a code, so it is not used as a number"
            )
        return "numeric", "numbers"
    # Text.
    lengths = present.str.len_chars()
    mean_len = float(lengths.mean() or 0.0)  # pyright: ignore[reportArgumentType]
    spaces = _share(present.str.contains(" "))
    ratio = n_distinct / n
    if _id_name(name) and (n_distinct > 50 or ratio > 0.5):
        return "identifier", "the name suggests an identifier"
    if n >= 20 and ratio >= 0.98 and mean_len <= 64 and spaces < 0.5:
        return "identifier", "nearly every value is unique"
    if mean_len > 60 or (spaces > 0.5 and ratio > 0.5 and n_distinct > 50):
        return "text", "long or mostly unique free text"
    if n_distinct <= 200 and (ratio <= 0.5 or n_distinct <= 20):
        return "categorical", f"{n_distinct} distinct labels"
    if spaces < 0.5:
        return "identifier", "many distinct short codes"
    return "text", "many distinct text values"


# ---------------------------------------------------------------- PII

_EMAIL = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"
_PHONE = r"^\+?[\d\s().\-]{7,20}$"
_SSN = r"^\d{3}-\d{2}-\d{4}$"
_IPV4 = r"^\d{1,3}(\.\d{1,3}){3}$"
_NAME_HINTS: Sequence[tuple[re.Pattern[str], str]] = (
    (
        re.compile(r"(^|_)(first|last|full|given|family|sur|middle)_?name$", re.IGNORECASE),
        "person_name",
    ),
    (
        re.compile(r"^(name|customer_?name|contact_?name|patient_?name)$", re.IGNORECASE),
        "person_name",
    ),
    (re.compile(r"(e-?mail)", re.IGNORECASE), "email"),
    (re.compile(r"(phone|mobile|tel$|telephone|cell)", re.IGNORECASE), "phone"),
    (re.compile(r"(address|street)", re.IGNORECASE), "address"),
    (re.compile(r"(^dob$|birth)", re.IGNORECASE), "date_of_birth"),
    (re.compile(r"(ssn|social_?security|passport|national_?id)", re.IGNORECASE), "national_id"),
)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def detect_pii(name: str, series: pl.Series, dtype: DType, role: Role) -> str | None:
    """A likely personal-data category for the column, or ``None``."""
    for pattern, label in _NAME_HINTS:
        if pattern.search(name) and (label == "date_of_birth" or dtype == "string"):
            if label == "person_name" and series.drop_nulls().n_unique() <= 20:
                continue
            return label
    if dtype != "string":
        return None
    sample = series.drop_nulls().head(2000)
    if sample.len() == 0:
        return None

    def share(pattern: str) -> float:
        return _share(sample.str.contains(pattern))

    if share(_EMAIL) >= 0.8:
        return "email"
    if share(_SSN) >= 0.8:
        return "national_id"
    if share(_IPV4) >= 0.8:
        return "ip_address"
    if share(_PHONE) >= 0.8 and _share(sample.str.contains(r"[\s().+\-]")) >= 0.5:
        return "phone"
    digits = sample.str.replace_all(r"[\s\-]", "")
    card_like = digits.str.contains(r"^\d{13,19}$")
    if _share(card_like) >= 0.8:
        valid = sum(1 for d in digits.filter(card_like).to_list() if _luhn(str(d)))
        if valid >= 0.8 * sample.len():
            return "payment_card"
    return None
