"""Discovery runs: choose the applicable methods, run the Rigor Kernel pipeline, build the feed.

:func:`prepare` turns a stored table and the user's choices into the analysis frame and the list
of analyses with the reason each one runs or is skipped (PROJECT_PROMPT.md section 3, step 4:
"show which analyses are being run and why they are applicable"). Every change made to the data
on the way (columns left out, rare labels combined, rows sampled) is listed in ``notes``.

:func:`execute` runs the kernel pipeline (holdout, cross-fitting or small-sample mode, chosen by
the number of rows), adds the descriptive checks and returns everything the app stores.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import polars as pl
from pydantic import BaseModel, Field

from edaforge.canonical import hash_frame
from edaforge.config import EDAForgeConfig
from edaforge.discovery.base import AnalysisSpec, BaseAnalyzer
from edaforge.discovery.conditional import Conditional
from edaforge.discovery.crossfile import CrossFile
from edaforge.discovery.describe import Observation, anomalies, leakage, quality_observations
from edaforge.discovery.feed import SESOI, build_feed
from edaforge.discovery.formulas import formulas
from edaforge.discovery.grain import ENTITY_COLUMN, detect_grain, entity_codes
from edaforge.discovery.redundancy import find_redundant
from edaforge.discovery.relationships import (
    SMALL_MIN_N,
    CategoryAssociations,
    GroupDifferences,
    NumericPairs,
)
from edaforge.discovery.subgroups import Subgroups
from edaforge.discovery.time import ChangePoints, choose_grain
from edaforge.explain.language import fmt_num
from edaforge.explain.render import RENDER_ERRORS
from edaforge.ingest import ROW_COLUMN, ColumnInfo, is_internal
from edaforge.link import SOURCE_COLUMN, scale_mismatch
from edaforge.models import AnalyzerRef, DataInput, Finding
from edaforge.planner.pipeline import RunResult, run_pipeline
from edaforge.plugins.sdk import AnalysisData, profile_frame
from edaforge.profile import DatasetProfile
from edaforge.runtime.events import Event

__all__ = ["PlanItem", "Prepared", "RunCancelled", "RunSettings", "execute", "prepare"]

Intent = Literal["auto", "target", "compare", "anomalies", "health"]
SEED = 20261110
MAX_ROWS = 200_000
MAX_NUMERIC = 25
MAX_CATEGORICAL = 15
SMALL_TABLE = 30  # below this, permutation tests only and groups of SMALL_GROUP rows
SMALL_GROUP = 5
MAX_LEVELS = 20
OTHER = "(other)"


class RunSettings(BaseModel):
    dataset_id: str = ""
    # Several tables: they are connected into one (see edaforge.link.scope) before the analysis.
    scope: list[str] = Field(default_factory=list)
    acknowledged: bool = False
    scope_notes: list[str] = Field(default_factory=list)  # set by the server, shown with the run
    target: str | None = None
    focus: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    time_column: str | None = None
    group_column: str | None = None
    intent: Intent = "auto"
    # Labels with fewer rows are combined into "(other)". Never below 10: smaller groups give
    # effect sizes and chi-square cells that cannot be trusted.
    min_group_size: Annotated[int, Field(ge=10, le=1000)] = 10


class PlanItem(BaseModel):
    analyzer: str
    label: str
    family: str
    status: Literal["run", "skipped"]
    reason: str
    n_tests: int | None = None
    method: str = ""


class RunCancelled(Exception):
    pass


class SettingsError(ValueError):
    """The chosen settings cannot be analyzed; the message explains why."""


@dataclass
class Prepared:
    spec: AnalysisSpec
    frame: pl.DataFrame
    rows: pl.Series
    analyzers: list[BaseAnalyzer]
    plan: list[PlanItem]
    notes: list[str]
    describe: dict[str, bool] = field(default_factory=dict[str, bool])
    n_dataset_rows: int = 0


def _target_kind(frame: pl.DataFrame, info: ColumnInfo) -> tuple[str, str | None]:
    if info.role == "numeric":
        return "numeric", None
    if info.role in {"categorical", "boolean"}:
        levels = sorted(
            str(v) for v in frame[info.name].drop_nulls().cast(pl.String).unique().to_list()
        )
        if len(levels) == 2:
            lower = [lv.lower() for lv in levels]
            for yes in ("true", "1", "yes", "y"):
                if yes in lower:
                    return "binary", levels[lower.index(yes)]
            counts = frame[info.name].cast(pl.String).value_counts(sort=True)
            return "binary", str(counts[counts.columns[0]][-1])
        if 3 <= len(levels) <= 12:
            return "categorical", None
        msg = f"{info.name} has {len(levels)} labels; a categorical target needs 2 to 12."
        raise SettingsError(msg)
    msg = (
        f"{info.name} is a {info.role} column and cannot be the outcome. Choose a number or "
        f"a category."
    )
    raise SettingsError(msg)


def prepare(columns: list[ColumnInfo], frame: pl.DataFrame, settings: RunSettings) -> Prepared:
    notes: list[str] = list(settings.scope_notes)
    infos = {c.name: c for c in columns}
    n_total = frame.height
    for name in [
        settings.target,
        settings.time_column,
        settings.group_column,
        *settings.focus,
        *settings.exclude,
    ]:
        if name is not None and name not in infos:
            msg = f"Unknown column {name!r}."
            raise SettingsError(msg)
    if settings.intent == "target" and not settings.target:
        msg = "Choose the outcome column to explain."
        raise SettingsError(msg)
    if settings.target in settings.exclude:
        msg = "The outcome column cannot also be excluded."
        raise SettingsError(msg)
    keep_always = {c for c in (settings.target, settings.time_column, settings.group_column) if c}
    left_out: dict[str, list[str]] = {}

    def leave(reason: str, name: str) -> None:
        left_out.setdefault(reason, []).append(name)

    numeric: list[str] = []
    categorical: list[str] = []
    datetimes: list[str] = []
    for info in columns:
        name = info.name
        if name in settings.exclude:
            leave("excluded by you", name)
            continue
        if settings.focus and name not in settings.focus and name not in keep_always:
            leave("outside your focus", name)
            continue
        if info.pii and name not in keep_always:
            leave("personal data", name)
            continue
        if info.role in {"identifier", "text", "empty"} and name not in keep_always:
            leave(
                {"identifier": "identifiers", "text": "free text", "empty": "empty"}[info.role],
                name,
            )
            continue
        if info.role != "datetime" and frame[name].drop_nulls().n_unique() <= 1:
            leave("a single value", name)
            continue
        if info.role == "numeric":
            numeric.append(name)
        elif info.role in {"categorical", "boolean"}:
            categorical.append(name)
        elif info.role == "datetime":
            datetimes.append(name)
    for reason, names in left_out.items():
        notes.append(f"Not analyzed ({reason}): {', '.join(names)}.")

    # A column recorded on different scales in different source files (cents and dollars) mixes
    # two populations: every within-table analysis of it would mostly rediscover the files. It is
    # compared between the files only, and cannot be the outcome until the units are aligned.
    mixed = _mixed_units(
        frame,
        [
            *numeric,
            *(
                [settings.target]
                if settings.target and infos[settings.target].role == "numeric"
                else []
            ),
        ],
    )
    if settings.target in mixed:
        a, ma, b, mb, hint = mixed[settings.target]
        msg = (
            f"{settings.target} is recorded on different scales in the appended files: "
            f"typical value {_num(ma)} in {a} "
            f"and {_num(mb)} in {b} ({hint}), which usually means different units. Align the "
            f"units when appending "
            "the files (Connect, review the link, rescale) before using it as the outcome."
        )
        raise SettingsError(msg)
    across_only = [c for c in numeric if c in mixed]
    numeric = [c for c in numeric if c not in mixed]

    target = settings.target
    target_kind: str | None = None
    positive: str | None = None
    if target:
        info = infos[target]
        target_kind, positive = _target_kind(frame, info)
        if target_kind == "numeric" and target not in numeric:
            numeric.insert(0, target)
        if target_kind != "numeric" and target not in categorical:
            categorical.insert(0, target)
    if settings.group_column and settings.group_column not in categorical:
        if infos[settings.group_column].role in {"categorical", "boolean", "identifier"}:
            categorical.append(settings.group_column)
        else:
            msg = (
                "The comparison column must hold categories (for example a region or a file name)."
            )
            raise SettingsError(msg)

    def cap(names: list[str], limit: int, kind: str) -> list[str]:
        if len(names) <= limit:
            return names
        priority = [n for n in names if n in keep_always or n in settings.focus]
        rest = sorted((n for n in names if n not in priority), key=lambda n: frame[n].null_count())
        kept = (priority + rest)[:limit]
        notes.append(
            f"Only {limit} {kind} columns are analyzed at a time; left out: "
            f"{', '.join(n for n in names if n not in kept)}. "
            "Use Focus to choose others."
        )
        return [n for n in names if n in kept]

    numeric = cap(numeric, MAX_NUMERIC, "numeric")
    categorical = cap(categorical, MAX_CATEGORICAL, "categorical")

    time_column = settings.time_column
    if time_column is None and datetimes and settings.intent in {"auto", "anomalies", "target"}:
        time_column = datetimes[0]
        notes.append(
            f"Time patterns use {time_column} (the first date column). Choose another "
            f"under Options."
        )

    environment = None
    env_label = "file"
    if (
        SOURCE_COLUMN in frame.columns
        and frame[SOURCE_COLUMN].n_unique() >= 2
        and not settings.group_column
    ):
        environment = SOURCE_COLUMN
    elif settings.group_column:
        environment = settings.group_column
        env_label = "group"
    if settings.intent == "compare" and environment is None:
        msg = "Comparing needs a table built by appending files, or a column to compare groups by."
        raise SettingsError(msg)
    if environment != SOURCE_COLUMN and across_only:
        notes.append(
            f"Not analyzed (recorded on different scales in the source files): "
            f"{', '.join(across_only)}. "
            "Align the units on the Connect page to include them."
        )
        across_only = []
    for name in across_only:
        a, ma, b, mb, hint = mixed[name]
        notes.append(
            f"{name} is only compared between the source files: its typical value is "
            f"{_num(ma)} in {a} and {_num(mb)} "
            f"in {b} ({hint}), which usually means different units. Other analyses leave it "
            f"out so that they do not "
            "rediscover the unit difference; align the units on the Connect page to include it."
        )

    # The analysis frame: only the columns analyzed, with rare labels combined.
    keep = list(
        dict.fromkeys(
            [
                *numeric,
                *across_only,
                *categorical,
                *([time_column] if time_column else []),
                *([environment] if environment else []),
            ]
        )
    )
    rows = (
        frame[ROW_COLUMN]
        if ROW_COLUMN in frame.columns
        else pl.Series(ROW_COLUMN, range(1, frame.height + 1))
    )
    grain = detect_grain(frame, columns, extra=(SOURCE_COLUMN,))
    entity_columns: frozenset[str] = frozenset()
    data = frame.select(keep).with_columns(rows.alias(ROW_COLUMN))
    if grain is not None:
        entity_columns = frozenset(c for c in keep if c in grain.columns)
        data = data.with_columns(entity_codes(frame[grain.key]))
        described = (
            ", ".join(
                c if c != SOURCE_COLUMN else "the source file" for c in sorted(entity_columns)
            )
            or "none of the analyzed columns"
        )
        notes.append(
            f"Rows repeat per {grain.key}: {grain.describe()}. Columns that describe a "
            f"{grain.key} rather than a row "
            f"({described}) are compared using one row per {grain.key}; tests that mix them "
            f"with row-level columns are "
            f"corrected for the repetition (design effect), and the check holds out whole "
            f"{grain.key} values."
        )
    if data.height > MAX_ROWS:
        if grain is not None:
            data = _sample_entities(data, MAX_ROWS)
            notes.append(
                f"Discovery uses a random sample of whole {grain.key} values "
                f"({data.height:,} of {n_total:,} rows, seed {SEED}); profiles use every row."
            )
        else:
            data = data.sample(n=MAX_ROWS, seed=SEED)
            notes.append(
                f"Discovery uses a random sample of {MAX_ROWS:,} of {n_total:,} rows "
                f"(seed {SEED}); profiles use every row."
            )
    rows = data[ROW_COLUMN]
    data = data.drop(ROW_COLUMN)
    exprs: list[pl.Expr | pl.Series] = []
    levels: dict[str, tuple[str, ...]] = {}
    per_entity = (
        data.unique(subset=[ENTITY_COLUMN], keep="first", maintain_order=True)
        if grain is not None
        else data
    )
    small = per_entity.height < SMALL_TABLE
    min_group = SMALL_GROUP if small else settings.min_group_size
    if small:
        notes.append(
            f"Small table ({per_entity.height:,} rows): only permutation tests are used "
            f"(exact at any size), groups need "
            f"{SMALL_GROUP} rows, and every finding is exploratory: there are too few rows "
            f"to set some aside and check it."
        )
    dropped_names: list[str] = []
    exprs.extend(pl.col(name).cast(pl.Float64) for name in [*numeric, *across_only])
    for name in [
        *categorical,
        *([environment] if environment and environment not in categorical else []),
    ]:
        col = data[name].cast(pl.String)
        counted = per_entity[name].cast(pl.String) if name in entity_columns else col
        if infos.get(name) is not None and infos[name].dtype == "boolean":
            col = data[name].cast(pl.Boolean).cast(pl.String)
            counted = (
                (per_entity if name in entity_columns else data)[name]
                .cast(pl.Boolean)
                .cast(pl.String)
            )
        counts = counted.drop_nulls().value_counts(sort=True)
        values = [str(v) for v in counts[counts.columns[0]].to_list()]
        sizes = [int(v) for v in counts["count"].to_list()]
        rare: set[str] = {v for v, s in zip(values, sizes, strict=True) if s < min_group}
        if name in (environment, target):
            rare = set()
        if (
            name not in {environment, target}
            and len(values) >= 0.9 * max(len(counted.drop_nulls()), 1)
            and len(values) > 5
        ):
            dropped_names.append(name)  # a different label on (almost) every row: it names the rows
            continue
        kept_levels = [v for v in values if v not in rare]
        if len(kept_levels) > MAX_LEVELS and name not in {environment, target}:
            rare |= set(kept_levels[MAX_LEVELS - 1 :])
            kept_levels = kept_levels[: MAX_LEVELS - 1]
        if rare:
            col = pl.select(
                pl.when(col.is_in(list(rare))).then(pl.lit(OTHER)).otherwise(col)
            ).to_series()
            unit = f"{grain.key} values" if grain is not None and name in entity_columns else "rows"
            notes.append(
                f"{name}: {len(rare)} rare label{'s' if len(rare) > 1 else ''} (under "
                f"{min_group} {unit}) combined into '{OTHER}' for comparisons."
            )
            kept_levels.append(OTHER)
        levels[name] = tuple(kept_levels)
        exprs.append(col.alias(name))
    data = data.with_columns(exprs)
    if dropped_names:
        categorical = [c for c in categorical if c not in dropped_names]
        data = data.drop([c for c in dropped_names if c in data.columns])
        notes.append(
            f"Not compared as groups: {', '.join(dropped_names)} has a different value on "
            f"(almost) every row, so it names "
            "the rows rather than grouping them."
        )
    if (
        target
        and target_kind == "binary"
        and positive is not None
        and infos[target].dtype == "boolean"
    ):
        positive = positive.lower()

    aliases, alias_notes = find_redundant(
        data, list(numeric), [c for c in categorical if c != environment]
    )
    notes.extend(alias_notes)
    spec = AnalysisSpec(
        dataset_name="",
        numeric=tuple(numeric),
        categorical=tuple(c for c in categorical if c != environment or settings.group_column),
        target=target,
        target_kind=target_kind,  # pyright: ignore[reportArgumentType]
        positive=positive,
        time_column=time_column,
        environment=environment,
        environment_label=env_label,
        intent=settings.intent,
        levels=levels,
        entity_key=grain.key if grain is not None else None,
        entity_columns=entity_columns,
        across_only=tuple(across_only),
        aliases=aliases,
        min_cell=SMALL_GROUP if small else 10,
    )
    analyzers, plan, describe = _plan(spec, data, settings.intent)
    return Prepared(
        spec=spec,
        frame=data,
        rows=rows,
        analyzers=analyzers,
        plan=plan,
        notes=notes,
        describe=describe,
        n_dataset_rows=n_total,
    )


def _sample_entities(data: pl.DataFrame, limit: int) -> pl.DataFrame:
    """Whole entities in random order until ``limit`` rows (an entity is never split)."""
    sizes = (
        data.group_by(ENTITY_COLUMN)
        .len()
        .sort(ENTITY_COLUMN)
        .sample(fraction=1.0, shuffle=True, seed=SEED)
    )
    within = sizes.with_columns(pl.col("len").cum_sum().alias("cum")).filter(pl.col("cum") <= limit)
    return data.filter(pl.col(ENTITY_COLUMN).is_in(within[ENTITY_COLUMN].implode()))


def _mixed_units(
    frame: pl.DataFrame, numeric: list[str]
) -> dict[str, tuple[str, float, str, float, str]]:
    """Numeric columns whose typical value differs by about ×100 or ×1,000 between source files.

    Returns column -> (source a, median a, source b, median b, hint) for the first such pair of
    sources. Only tables built by appending files have a source column to compare.
    """
    if SOURCE_COLUMN not in frame.columns:
        return {}
    sources = sorted(str(s) for s in frame[SOURCE_COLUMN].drop_nulls().unique().to_list())
    if len(sources) < 2:
        return {}
    labels = frame[SOURCE_COLUMN].cast(pl.String)
    out: dict[str, tuple[str, float, str, float, str]] = {}
    for name in dict.fromkeys(numeric):
        column = frame[name]
        for i, a in enumerate(sources):
            for b in sources[i + 1 :]:
                found = scale_mismatch(column.filter(labels == a), column.filter(labels == b))
                if found is not None:
                    out[name] = (a, found[0], b, found[1], found[3])
                    break
            if name in out:
                break
    return out


def _num(value: float) -> str:
    return fmt_num(value)


def _plan(
    spec: AnalysisSpec, frame: pl.DataFrame, intent: str
) -> tuple[list[BaseAnalyzer], list[PlanItem], dict[str, bool]]:
    _numeric, categorical = spec.predictors()
    n = frame.height
    t, tk = spec.target, spec.target_kind
    allowed: set[str] = {
        "auto": {
            "numeric_pairs",
            "group_differences",
            "category_associations",
            "subgroups",
            "conditional",
            "change_points",
            "cross_file",
        },
        "target": {
            "numeric_pairs",
            "group_differences",
            "category_associations",
            "subgroups",
            "conditional",
            "change_points",
        },
        "compare": {"cross_file", "group_differences"},
        "anomalies": {"change_points"},
        "health": set[str](),
    }[intent]
    items: list[tuple[BaseAnalyzer | None, PlanItem]] = []

    def add(analyzer: BaseAnalyzer, key: str, ok: bool, reason: str, n_tests: int | None) -> None:
        if key not in allowed:
            ok, reason = False, f"not part of the '{intent}' analysis"
        items.append(
            (
                analyzer if ok else None,
                PlanItem(
                    analyzer=analyzer.name,
                    label=analyzer.label,
                    family=analyzer.family,
                    status="run" if ok else "skipped",
                    reason=reason,
                    n_tests=n_tests if ok else None,
                    method=analyzer.method_summary,
                ),
            )
        )

    np_ = NumericPairs(spec)
    pairs = len(np_.pairs())
    few = f"needs at least {SMALL_MIN_N} rows; this table has {n}"
    add(
        np_,
        "numeric_pairs",
        pairs > 0 and n >= SMALL_MIN_N,
        (f"{pairs} pairs of numeric columns" if n >= SMALL_MIN_N else few)
        if pairs
        else "needs at least two numeric columns",
        pairs,
    )
    gd = GroupDifferences(spec)
    tasks = len(gd.tasks())
    add(
        gd,
        "group_differences",
        tasks > 0 and n >= SMALL_MIN_N,
        (f"{tasks} number-by-group comparisons" if n >= SMALL_MIN_N else few)
        if tasks
        else "needs a numeric and a categorical column",
        tasks,
    )
    ca = CategoryAssociations(spec)
    tasks = len(ca.tasks())
    add(
        ca,
        "category_associations",
        tasks > 0 and n >= 30,
        (
            f"{tasks} pairs of categorical columns"
            if n >= 30
            else f"needs at least 30 rows for a table of counts; this table has {n}"
        )
        if tasks
        else "needs two categorical columns",
        tasks,
    )
    sg = Subgroups(spec)
    ok = bool(t) and tk in {"numeric", "binary"} and n >= 2 * spec.min_support
    reason = (
        f"segments where {t} differs, and pairs of conditions that matter together"
        if ok
        else (
            "choose a numeric or yes/no outcome to search for segments"
            if not t
            else f"needs a numeric or yes/no outcome and at least {2 * spec.min_support} rows"
        )
    )
    add(sg, "subgroups", ok, reason, None)
    cd = Conditional(spec)
    ok = len(spec.numeric) >= 2 and len(spec.numeric) + len(categorical) >= 3 and n >= 100
    add(
        cd,
        "conditional",
        ok,
        "checks whether associations disappear or reverse after accounting for a third column"
        if ok
        else "needs two numeric columns, a third column and 100 rows",
        None,
    )
    cp = ChangePoints(spec)
    grain, periods = choose_grain(frame, spec.time_column) if spec.time_column else (None, 0)
    add(
        cp,
        "change_points",
        grain is not None,
        f"{periods} {grain}s of {spec.time_column}"
        if grain
        else (
            "no date column"
            if not spec.time_column
            else f"{spec.time_column} has too few periods (needs 30)"
        ),
        None,
    )
    cf = CrossFile(spec)
    env = spec.environment
    k = len(spec.levels.get(env, ())) if env else 0
    sizes_ok = (
        bool(env)
        and all(
            int(frame.filter(pl.col(env) == lv).height) >= 30 for lv in spec.levels.get(env, ())
        )
        if env
        else False
    )
    ok = bool(env) and 2 <= k <= 6 and sizes_ok
    add(
        cf,
        "cross_file",
        ok,
        f"compares {k} {spec.environment_label}s column by column"
        if ok
        else (
            "needs appended files or a comparison column"
            if not env
            else "needs 2 to 6 sources with at least 30 rows each"
        ),
        None,
    )
    describe = {
        "quality": True,
        "leakage": bool(t) and intent in {"auto", "target", "health"},
        "anomalies": intent in {"auto", "anomalies"} and len(spec.numeric) >= 2 and n >= 200,
    }
    plan = [p for _, p in items]
    plan.append(
        PlanItem(
            analyzer="describe.quality",
            label="Data-quality checks",
            family="data_quality",
            status="run",
            reason="always: every finding depends on the data",
            method="profile rules (see Data)",
        )
    )
    plan.append(
        PlanItem(
            analyzer="describe.leakage",
            label="Leakage check",
            family="data_quality",
            status="run" if describe["leakage"] else "skipped",
            reason="columns that almost determine the outcome"
            if describe["leakage"]
            else "needs an outcome column",
            method="near-perfect association with the target",
        )
    )
    plan.append(
        PlanItem(
            analyzer="describe.anomaly",
            label="Unusual records",
            family="anomalies",
            status="run" if describe["anomalies"] else "skipped",
            reason="Isolation Forest over the numeric columns"
            if describe["anomalies"]
            else (
                "needs two numeric columns and 200 rows"
                if intent in {"auto", "anomalies"}
                else f"not part of the '{intent}' analysis"
            ),
            method="Isolation Forest, top 1%",
        )
    )
    return [a for a, _ in items if a is not None], plan, describe


@dataclass
class Outcome:
    result: RunResult
    feed: list[dict[str, Any]]
    details: dict[str, dict[str, Any]]
    plan: list[PlanItem]
    notes: list[str]
    warnings: list[str]
    seconds: float


def execute(
    prepared: Prepared,
    *,
    dataset_name: str,
    fingerprint: str,
    profile: DatasetProfile,
    on_event: Callable[[Event], None],
) -> Outcome:
    started = _time.monotonic()
    spec = prepared.spec
    frame = prepared.frame
    analyzers = prepared.analyzers
    config = EDAForgeConfig(
        budget="deep",
        targets=[spec.target] if spec.target else [],
        environments_from=spec.environment,
        sesoi={k: v for k, v in SESOI.items() if v > 0},
        compute={"seed": SEED},  # pyright: ignore[reportArgumentType]
    )
    data = AnalysisData(
        frame=frame,
        name=dataset_name,
        data_hash=hash_frame(frame),
        profile=profile_frame(
            frame,
            environment_column=spec.environment,
            targets=[spec.target] if spec.target else [],
            group_column=ENTITY_COLUMN if spec.entity_key else None,
        ),
    )
    RENDER_ERRORS.clear()
    result = run_pipeline(
        data,
        analyzers,
        config,
        analyzer_refs=[AnalyzerRef(name=a.name, version=a.version) for a in analyzers],
        inputs=[
            DataInput(
                name=dataset_name,
                sha256=fingerprint,
                n_rows=prepared.n_dataset_rows,
                n_cols=frame.width,
                kind="frame",
            )
        ],
        on_event=on_event,
    )
    observations: list[Observation] = []
    if prepared.describe.get("quality"):
        observations.extend(quality_observations(profile, spec))
    if prepared.describe.get("leakage"):
        observations.extend(leakage(frame, spec))
    if prepared.describe.get("anomalies"):
        observations.extend(anomalies(frame, prepared.rows, spec, SEED))
    observations.extend(formulas(frame, [*spec.numeric]))
    by_name = {a.name: a for a in analyzers}
    charts: dict[str, Any] = {}
    warnings = list(result.warnings)
    for finding in result.findings:
        analyzer = by_name.get(finding.provenance.analyzer)
        if analyzer is None:
            continue
        try:
            charts[finding.id] = analyzer.charts(finding, frame)
        except Exception as exc:  # noqa: BLE001 - a chart failure must not lose the finding
            warnings.append(
                f"{finding.id}: the chart could not be drawn ({type(exc).__name__}: {exc})."
            )
            charts[finding.id] = []
    findings: list[Finding] = list(result.findings)
    feed, details = build_feed(
        findings, charts, observations, spec, frame.height, dataset_name, result.ledger
    )
    warnings.extend(f"template fallback: {e}" for e in RENDER_ERRORS)
    return Outcome(
        result=result,
        feed=feed,
        details=details,
        plan=prepared.plan,
        notes=prepared.notes,
        warnings=warnings,
        seconds=_time.monotonic() - started,
    )


def is_user_column(name: str) -> bool:
    return not is_internal(name)
