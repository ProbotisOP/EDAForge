"""Column profiles, data-quality issues and the health score (milestone 2).

Every issue states the rule that produced it (``method``) and points at example values and row
numbers, so the user can check it. Outliers are flagged, never removed. The health score is a
summary aid with a published formula (:func:`health_score`); it never certifies data quality
(PROJECT_PROMPT.md section 3, step 2).
"""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import numpy as np
import polars as pl
from pydantic import BaseModel

from edaforge.ingest import ROW_COLUMN, ColumnInfo, ParseIssue, is_internal

__all__ = [
    "ColumnProfile",
    "DatasetProfile",
    "HealthComponent",
    "HealthScore",
    "QualityIssue",
    "health_score",
    "mask_value",
    "profile_dataset",
]

Severity = Literal["critical", "warning", "info"]
Category = Literal[
    "completeness", "validity", "uniqueness", "consistency", "structure", "outliers", "privacy"
]

_OUTLIER_K = 3.0  # Tukey's "far out" fences: Q1 - 3 IQR, Q3 + 3 IQR
_MAX_ROWS = 20
_NON_NEGATIVE = re.compile(
    r"(^|_|\b)(age|price|amount|qty|quantity|count|revenue|sales|cost|weight|height|duration|"
    r"distance|income|salary|units|volume|size|length|area|population|visits|clicks|spend)(s)?($|_|\b)",
    re.IGNORECASE,
)
_AGE = re.compile(r"(^|_|\b)age($|_|\b)", re.IGNORECASE)
_PERCENT = re.compile(r"(pct|percent|percentage)", re.IGNORECASE)


class HistogramBin(BaseModel):
    x0: float | str
    x1: float | str
    count: int


class TopValue(BaseModel):
    value: str
    count: int


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    role: str
    pii: str | None = None
    n: int
    n_missing: int
    missing_share: float
    n_distinct: int
    distinct_share: float
    min: float | str | None = None
    max: float | str | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    q1: float | None = None
    q3: float | None = None
    n_zero: int | None = None
    n_negative: int | None = None
    n_outliers: int | None = None
    histogram: list[HistogramBin] = []
    top_values: list[TopValue] = []
    flags: list[str] = []


class QualityIssue(BaseModel):
    id: str
    severity: Severity
    category: Category
    title: str
    detail: str
    column: str | None = None
    columns: list[str] = []
    count: int | None = None
    share: float | None = None
    method: str
    examples: list[str] = []
    rows: list[int] = []


class HealthComponent(BaseModel):
    category: str
    penalty: float
    cap: float
    issues: int
    explanation: str


class HealthScore(BaseModel):
    score: float
    label: str
    method: str
    components: list[HealthComponent]


class DatasetProfile(BaseModel):
    dataset_id: str
    n_rows: int
    n_cols: int
    n_duplicate_rows: int
    columns: list[ColumnProfile]
    issues: list[QualityIssue]
    health: HealthScore
    roles: dict[str, int]


def mask_value(value: str) -> str:
    """Hide personal data while keeping the shape of the value ("j***@e***.com")."""
    if "@" in value:
        user, _, domain = value.partition("@")
        head, _, tld = domain.rpartition(".")
        return f"{user[:1]}***@{head[:1]}***.{tld}" if head else f"{user[:1]}***@***"
    if len(value) <= 2:
        return "*" * len(value)
    return value[0] + "*" * min(len(value) - 2, 8) + value[-1]


def _finite(x: Any) -> float | None:
    if x is None:
        return None
    value = float(x)
    return value if math.isfinite(value) else None


def _rows(frame: pl.DataFrame, mask: pl.Series) -> list[int]:
    return [int(r) for r in frame[ROW_COLUMN].filter(mask).head(_MAX_ROWS).to_list()]


def _examples(values: pl.Series, pii: bool, k: int = 6) -> list[str]:
    out: list[str] = []
    for value in values.drop_nulls().unique(maintain_order=True).head(k).to_list():
        text = str(value)
        if pii:
            text = mask_value(text)
        out.append(text if len(text) <= 48 else text[:45] + "...")
    return out


def _numeric_histogram(
    values: np.ndarray[Any, np.dtype[np.float64]], integral: bool
) -> list[HistogramBin]:
    lo, hi = float(values.min()), float(values.max())
    if lo == hi:
        return [HistogramBin(x0=lo, x1=hi, count=int(values.size))]
    n_bins = 24
    if integral and hi - lo + 1 <= 30:
        edges = np.arange(lo - 0.5, hi + 1.5, 1.0)
    else:
        edges = np.linspace(lo, hi, n_bins + 1)
    counts, edges = np.histogram(values, bins=edges)
    return [
        HistogramBin(x0=float(edges[i]), x1=float(edges[i + 1]), count=int(counts[i]))
        for i in range(counts.size)
    ]


def _time_histogram(series: pl.Series) -> list[HistogramBin]:
    as_int = series.drop_nulls().cast(pl.Datetime("us")).cast(pl.Int64).to_numpy()
    if as_int.size == 0:
        return []
    lo, hi = int(as_int.min()), int(as_int.max())
    if lo == hi:
        stamp = datetime.fromtimestamp(lo / 1e6, tz=UTC).isoformat()
        return [HistogramBin(x0=stamp, x1=stamp, count=int(as_int.size))]
    counts, edges = np.histogram(as_int, bins=24)
    return [
        HistogramBin(
            x0=datetime.fromtimestamp(float(edges[i]) / 1e6, tz=UTC).isoformat(),
            x1=datetime.fromtimestamp(float(edges[i + 1]) / 1e6, tz=UTC).isoformat(),
            count=int(counts[i]),
        )
        for i in range(counts.size)
    ]


def _normalize_label(value: str) -> str:
    return re.sub(r"[\s_\-.]+", " ", value.strip().lower()).strip()


class _Builder:
    def __init__(self, frame: pl.DataFrame, columns: list[ColumnInfo]) -> None:
        self.frame = frame
        self.columns = columns
        self.n = frame.height
        self.issues: list[QualityIssue] = []

    def add(self, **kwargs: Any) -> None:
        self.issues.append(QualityIssue(id=f"Q{len(self.issues) + 1:03d}", **kwargs))

    # ------------------------------------------------------------------ per column
    def column(self, info: ColumnInfo) -> ColumnProfile:
        series = self.frame[info.name]
        n_missing = int(series.null_count())
        present = series.drop_nulls()
        n_distinct = int(present.n_unique()) if present.len() else 0
        pii = info.pii is not None
        profile = ColumnProfile(
            name=info.name,
            dtype=info.dtype,
            role=info.role,
            pii=info.pii,
            n=self.n,
            n_missing=n_missing,
            missing_share=n_missing / self.n if self.n else 0.0,
            n_distinct=n_distinct,
            distinct_share=n_distinct / present.len() if present.len() else 0.0,
        )
        if present.len() == 0:
            self.add(
                severity="warning",
                category="completeness",
                title=f"{info.name} is empty",
                detail="Every value in this column is missing, so it cannot be analyzed.",
                column=info.name,
                columns=[info.name],
                count=self.n,
                share=1.0,
                method="count of missing values = number of rows",
            )
            profile.flags.append("empty")
            return profile
        share = n_missing / self.n
        if share >= 0.05:
            severity: Severity = (
                "critical" if share >= 0.5 else "warning" if share >= 0.2 else "info"
            )
            self.add(
                severity=severity,
                category="completeness",
                title=f"{info.name} is missing in {share:.0%} of rows",
                detail=(
                    f"{n_missing:,} of {self.n:,} rows have no value. Analyses that use this "
                    f"column "
                    "only use rows where it is present, and say how many rows they used."
                ),
                column=info.name,
                columns=[info.name],
                count=n_missing,
                share=share,
                method=(
                    "share of missing values; flagged at 5% or more (20%: warning, 50%: critical)"
                ),
                rows=_rows(self.frame, series.is_null()),
            )
        if info.n_invalid:
            self.add(
                severity="warning",
                category="validity",
                title=(
                    f"{info.n_invalid:,} unreadable "
                    f"value{'' if info.n_invalid == 1 else 's'} in {info.name}"
                ),
                detail=(
                    f"These values could not be read as {info.dtype} values and are treated "
                    f"as missing. "
                    "See 'How it was read' for examples and row numbers."
                ),
                column=info.name,
                columns=[info.name],
                count=info.n_invalid,
                share=info.n_invalid / self.n,
                method="values that failed to parse with the column's detected type",
            )
        if n_distinct == 1 and self.n > 1:
            profile.flags.append("constant")
            self.add(
                severity="info",
                category="structure",
                title=f"{info.name} has a single value",
                detail=(
                    "A column with one value carries no information for comparisons; it is skipped."
                ),
                column=info.name,
                columns=[info.name],
                method="number of distinct non-missing values = 1",
                examples=_examples(present, pii, 1),
            )
        if info.dtype in {"integer", "float"}:
            self._numeric(info, series, present, profile)
        elif info.dtype in {"date", "datetime"}:
            self._temporal(info, series, present, profile)
        else:
            self._labels(info, series, present, profile)
        if info.pii is not None:
            profile.flags.append("pii")
            self.add(
                severity="info",
                category="privacy",
                title=f"{info.name} looks like personal data ({info.pii.replace('_', ' ')})",
                detail=(
                    "It is excluded from discovery and its values are masked in profiles and "
                    "exports. You can still see it in the row preview on this computer."
                ),
                column=info.name,
                columns=[info.name],
                method="column-name hints and value patterns (e-mail, phone, card numbers, IDs)",
            )
        return profile

    def _numeric(
        self, info: ColumnInfo, series: pl.Series, present: pl.Series, profile: ColumnProfile
    ) -> None:
        values = present.cast(pl.Float64).to_numpy()
        q1, median, q3 = (float(v) for v in np.quantile(values, [0.25, 0.5, 0.75]))
        profile.min = float(values.min())
        profile.max = float(values.max())
        profile.mean = _finite(values.mean())
        profile.median = median
        profile.std = _finite(values.std(ddof=1)) if values.size > 1 else None
        profile.q1, profile.q3 = q1, q3
        profile.n_zero = int((values == 0).sum())
        profile.n_negative = int((values < 0).sum())
        profile.histogram = _numeric_histogram(values, info.dtype == "integer")
        if info.role == "identifier":
            return
        iqr = q3 - q1
        low, high = q1 - _OUTLIER_K * iqr, q3 + _OUTLIER_K * iqr
        method = (
            f"Tukey far-out fences: below Q1 − 3·IQR ({low:.4g}) or above Q3 + 3·IQR ({high:.4g})"
        )
        if iqr == 0:
            mad = float(np.median(np.abs(values - median)))
            if mad == 0:
                low = high = None
            else:
                scale = 1.4826 * mad
                low, high = median - 5 * scale, median + 5 * scale
                method = (
                    f"robust z-score above 5 (median ± 5 × 1.4826 × MAD: {low:.4g} to {high:.4g})"
                )
        if low is not None and high is not None:
            col = series.cast(pl.Float64)
            mask = col.is_not_null() & ((col < low) | (col > high))
            n_out = int(mask.sum())
            profile.n_outliers = n_out
            if n_out:
                self.add(
                    severity="info",
                    category="outliers",
                    title=f"{n_out:,} unusual value{'' if n_out == 1 else 's'} in {info.name}",
                    detail=(
                        "These values are far from the bulk of the column. They are flagged, "
                        "not removed: "
                        "they may be errors or genuine extremes. Check them in the preview."
                    ),
                    column=info.name,
                    columns=[info.name],
                    count=n_out,
                    share=n_out / self.n,
                    method=method,
                    examples=[f"{v:.6g}" for v in col.filter(mask).head(6).to_list()],
                    rows=_rows(self.frame, mask),
                )
        col = series.cast(pl.Float64)
        if _NON_NEGATIVE.search(info.name) and profile.n_negative:
            mask = col.is_not_null() & (col < 0)
            self.add(
                severity="warning",
                category="validity",
                title=f"Negative values in {info.name}",
                detail=(
                    f"{profile.n_negative:,} values are below zero, which the column name "
                    f"suggests is "
                    "impossible (a refund or correction may be recorded this way). Check them."
                ),
                column=info.name,
                columns=[info.name],
                count=profile.n_negative,
                share=profile.n_negative / self.n,
                method="the name suggests a non-negative quantity; values < 0 are flagged",
                examples=[f"{v:.6g}" for v in col.filter(mask).head(6).to_list()],
                rows=_rows(self.frame, mask),
            )
        if _AGE.search(info.name) and profile.max > 120:  # set to a float at the top
            mask = col > 120
            self.add(
                severity="warning",
                category="validity",
                title=f"Ages above 120 in {info.name}",
                detail="Some ages exceed 120 years, which is almost certainly a data error.",
                column=info.name,
                columns=[info.name],
                count=int(mask.sum()),
                method="age values > 120 are flagged",
                rows=_rows(self.frame, mask.fill_null(False)),
            )
        if _PERCENT.search(info.name):
            mask = col.is_not_null() & ((col < 0) | (col > 100))
            if int(mask.sum()):
                self.add(
                    severity="warning",
                    category="validity",
                    title=f"Percentages outside 0–100 in {info.name}",
                    detail=(
                        "The name suggests a percentage, but some values are below 0 or above 100."
                    ),
                    column=info.name,
                    columns=[info.name],
                    count=int(mask.sum()),
                    method="values outside [0, 100] in a column named like a percentage",
                    rows=_rows(self.frame, mask),
                )
        self._units(info, values)

    def _units(self, info: ColumnInfo, values: np.ndarray[Any, np.dtype[np.float64]]) -> None:
        """Two clusters of magnitude about 100x or 1000x apart can mean mixed units."""
        positive = np.sort(values[values > 0])
        if positive.size < 40:
            return
        logs = np.log10(positive)
        gaps = np.diff(logs)
        i = int(gaps.argmax())
        gap = float(gaps[i])
        lower, upper = logs[: i + 1], logs[i + 1 :]
        if gap < 1.0 or min(lower.size, upper.size) < 0.05 * logs.size:
            return
        ratio = float(np.median(upper) - np.median(lower))
        for decades, label in ((2.0, "100"), (3.0, "1,000")):
            if abs(ratio - decades) <= 0.3:
                self.add(
                    severity="warning",
                    category="consistency",
                    title=f"{info.name} may mix units",
                    detail=(
                        f"Values form two groups whose typical sizes differ by about ×{label} "
                        f"({lower.size:,} small, {upper.size:,} large values) with nothing "
                        f"in between. "
                        "This often means two units (for example grams and kilograms) were mixed."
                    ),
                    column=info.name,
                    columns=[info.name],
                    count=int(min(lower.size, upper.size)),
                    method=(
                        "largest gap in log10(value) ≥ 1 decade, both groups ≥ 5% of values, "
                        "median ratio within 0.3 decades of 100 or 1,000"
                    ),
                    examples=[
                        f"{10 ** float(np.median(lower)):.4g}",
                        f"{10 ** float(np.median(upper)):.4g}",
                    ],
                )
                return

    def _temporal(
        self, info: ColumnInfo, series: pl.Series, present: pl.Series, profile: ColumnProfile
    ) -> None:
        lo, hi = present.min(), present.max()
        profile.min = str(lo)
        profile.max = str(hi)
        profile.histogram = _time_histogram(series)
        today = datetime.now(UTC).date()
        as_date = series.cast(pl.Date) if info.dtype == "datetime" else series
        future = as_date.is_not_null() & (as_date > today + timedelta(days=1))
        old = as_date.is_not_null() & (as_date < date(1900, 1, 1))
        for mask, title, method in (
            (future, f"Dates in the future in {info.name}", "dates later than tomorrow"),
            (old, f"Dates before 1900 in {info.name}", "dates earlier than 1900-01-01"),
        ):
            count = int(mask.sum())
            if count:
                self.add(
                    severity="warning",
                    category="validity",
                    title=title,
                    detail=(
                        f"{count:,} dates look implausible. They may be typos or placeholder dates."
                    ),
                    column=info.name,
                    columns=[info.name],
                    count=count,
                    share=count / self.n,
                    method=method,
                    examples=_examples(series.filter(mask), False),
                    rows=_rows(self.frame, mask),
                )

    def _labels(
        self, info: ColumnInfo, series: pl.Series, present: pl.Series, profile: ColumnProfile
    ) -> None:
        pii = info.pii is not None
        counts = present.cast(pl.String).value_counts(sort=True).head(12)
        names = counts.columns
        profile.top_values = [
            TopValue(value=mask_value(str(v)) if pii else str(v), count=int(c))
            for v, c in zip(counts[names[0]].to_list(), counts[names[1]].to_list(), strict=True)
        ]
        if (
            info.role == "identifier"
            and profile.distinct_share >= 0.95
            and profile.distinct_share < 1.0
        ):
            duplicated = series.is_duplicated() & series.is_not_null()
            n_dup = int(present.len() - present.n_unique())
            self.add(
                severity="warning",
                category="uniqueness",
                title=f"Duplicate identifiers in {info.name}",
                detail=(
                    f"{info.name} looks like a unique ID (≥ 95% of values are unique), but "
                    f"{n_dup:,} values "
                    "repeat. Joining on it may duplicate rows."
                ),
                column=info.name,
                columns=[info.name],
                count=n_dup,
                method="identifier column with ≥ 95% (but not 100%) unique values",
                examples=_examples(series.filter(duplicated), pii),
                rows=_rows(self.frame, duplicated),
            )
        if info.role in {"categorical", "boolean"} and info.dtype == "string":
            # First-appearance order: plain unique() order varies between runs.
            values = present.unique(maintain_order=True).to_list()
            groups: dict[str, list[str]] = {}
            for value in values:
                groups.setdefault(_normalize_label(str(value)), []).append(str(value))
            variants = [sorted(v) for v in groups.values() if len(v) > 1]
            if variants:
                shown = "; ".join(" / ".join(f"'{x}'" for x in v[:4]) for v in variants[:4])
                self.add(
                    severity="warning",
                    category="consistency",
                    title=f"Inconsistent labels in {info.name}",
                    detail=(
                        f"{len(variants)} labels are written in more than one way ({shown}). "
                        f"They are "
                        "counted as different categories unless you fix them."
                    ),
                    column=info.name,
                    columns=[info.name],
                    count=len(variants),
                    method=(
                        "labels that become identical after lower-casing and removing "
                        "spaces, '_', '-' and '.'"
                    ),
                    examples=[x for v in variants[:3] for x in v[:3]],
                )
        if info.role == "categorical" and profile.n_distinct > 50:
            profile.flags.append("many_categories")
            self.add(
                severity="info",
                category="structure",
                title=f"{info.name} has {profile.n_distinct:,} categories",
                detail=(
                    "Group comparisons use the most frequent categories and combine the rest into "
                    "'other', so that every group shown has enough records."
                ),
                column=info.name,
                columns=[info.name],
                method="more than 50 distinct labels",
            )

    # ------------------------------------------------------------------ dataset level
    def duplicates(self) -> int:
        user = [c for c in self.frame.columns if not is_internal(c)]
        if not user or self.n < 2:
            return 0
        first = self.frame.select(pl.struct(user).is_first_distinct()).to_series()
        mask = ~first
        n_dup = int(mask.sum())
        if n_dup:
            share = n_dup / self.n
            self.add(
                severity="warning" if share < 0.05 else "critical",
                category="uniqueness",
                title=f"{n_dup:,} duplicate row{'' if n_dup == 1 else 's'}",
                detail=(
                    f"{n_dup:,} rows ({share:.1%}) repeat an earlier row in every column. "
                    f"Duplicates can "
                    "double-count records; they are kept until you decide what they mean."
                ),
                count=n_dup,
                share=share,
                method="rows identical to an earlier row in every column (row numbers excluded)",
                rows=_rows(self.frame, mask),
            )
        return n_dup

    def parse_issues(self, issues: list[ParseIssue]) -> None:
        for issue in issues:
            if issue.code == "ambiguous_date_format":
                self.add(
                    severity="warning",
                    category="consistency",
                    title=f"Ambiguous date format in {issue.column}",
                    detail=issue.message,
                    column=issue.column,
                    columns=[issue.column] if issue.column else [],
                    method="every date fits both day/month and month/day orders",
                    examples=issue.examples,
                )
            elif issue.code == "mixed_types":
                self.add(
                    severity="warning",
                    category="consistency",
                    title=f"Numbers and text mixed in {issue.column}",
                    detail=issue.message,
                    column=issue.column,
                    columns=[issue.column] if issue.column else [],
                    count=issue.count,
                    method="50–95% of the values parse as numbers",
                    examples=issue.examples,
                    rows=issue.rows,
                )
            elif issue.code == "short_rows":
                self.add(
                    severity="warning",
                    category="structure",
                    title="Rows with missing fields",
                    detail=issue.message,
                    count=issue.count,
                    method="rows with fewer delimited fields than the header",
                    rows=issue.rows,
                )


def health_score(
    issues: list[QualityIssue],
    *,
    n_rows: int,
    n_cols: int,
    missing_cells: int,
    invalid_cells: int,
    duplicate_rows: int,
) -> HealthScore:
    """``100 − Σ min(cap, penalty)`` over five categories.

    Outliers and privacy notes cost nothing.
    """
    cells = max(1, n_rows * max(n_cols, 1))

    def count(category: str) -> int:
        return sum(1 for i in issues if i.category == category)

    missing_share = missing_cells / cells
    invalid_share = invalid_cells / cells
    duplicate_share = duplicate_rows / max(1, n_rows)
    impossible = sum(
        1
        for i in issues
        if i.category == "validity"
        and i.title.startswith(("Negative", "Ages", "Percentages", "Dates"))
    )
    dup_ids = sum(1 for i in issues if i.category == "uniqueness" and i.column)
    components = [
        HealthComponent(
            category="Completeness",
            penalty=min(25.0, 50.0 * missing_share),
            cap=25.0,
            issues=count("completeness"),
            explanation=f"50 × share of missing cells ({missing_share:.1%}), at most 25",
        ),
        HealthComponent(
            category="Validity",
            penalty=min(25.0, 100.0 * invalid_share + 3.0 * impossible),
            cap=25.0,
            issues=count("validity"),
            explanation=(
                f"100 × share of unreadable cells ({invalid_share:.2%}) + 3 per implausible-value "
                f"check that fired ({impossible}), at most 25"
            ),
        ),
        HealthComponent(
            category="Uniqueness",
            penalty=min(20.0, 50.0 * duplicate_share + 5.0 * dup_ids),
            cap=20.0,
            issues=count("uniqueness"),
            explanation=(
                f"50 × share of duplicate rows ({duplicate_share:.1%}) + 5 per ID column with "
                f"duplicates ({dup_ids}), at most 20"
            ),
        ),
        HealthComponent(
            category="Consistency",
            penalty=min(15.0, 4.0 * count("consistency")),
            cap=15.0,
            issues=count("consistency"),
            explanation=(
                "4 per inconsistency (labels, mixed types, units, ambiguous dates), at most 15"
            ),
        ),
        HealthComponent(
            category="Structure",
            penalty=min(
                15.0,
                1.0
                * sum(1 for i in issues if i.category == "structure" and "single value" in i.title)
                + 5.0 * sum(1 for i in issues if i.title == "Rows with missing fields"),
            ),
            cap=15.0,
            issues=count("structure"),
            explanation="1 per constant column + 5 if rows had missing fields, at most 15",
        ),
    ]
    for c in components:
        c.penalty = round(c.penalty, 1)
    score = round(max(0.0, 100.0 - sum(c.penalty for c in components)), 1)
    label = (
        "Good"
        if score >= 90
        else "Fair"
        if score >= 75
        else "Needs attention"
        if score >= 50
        else "Poor"
    )
    return HealthScore(
        score=score,
        label=label,
        method=(
            "Starts at 100 and subtracts a capped penalty per category. Outliers and personal-data "
            "notes are listed but not penalized. The score summarizes the checks below; it "
            "does not certify that the data are correct."
        ),
        components=components,
    )


def profile_dataset(
    dataset_id: str, frame: pl.DataFrame, columns: list[ColumnInfo], parse_issues: list[ParseIssue]
) -> DatasetProfile:
    builder = _Builder(frame, columns)
    profiles = [builder.column(info) for info in columns]
    n_dup = builder.duplicates()
    builder.parse_issues(parse_issues)
    order = {"critical": 0, "warning": 1, "info": 2}
    builder.issues.sort(key=lambda i: (order[i.severity], i.id))
    roles: dict[str, int] = {}
    for info in columns:
        roles[info.role] = roles.get(info.role, 0) + 1
    health = health_score(
        builder.issues,
        n_rows=frame.height,
        n_cols=len(columns),
        missing_cells=sum(p.n_missing for p in profiles),
        invalid_cells=sum(info.n_invalid for info in columns),
        duplicate_rows=n_dup,
    )
    return DatasetProfile(
        dataset_id=dataset_id,
        n_rows=frame.height,
        n_cols=len(columns),
        n_duplicate_rows=n_dup,
        columns=profiles,
        issues=builder.issues,
        health=health,
        roles=roles,
    )
