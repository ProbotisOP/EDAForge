"""The Python API (section 12.3).

Phase 0 provides :func:`discover` on in-memory Polars frames and on simple files, with export,
run directories, caching and reproduction. ``edaforge.load`` with the full ingest and link layers
arrives in Phases 1 and 2.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import polars as pl

from edaforge.canonical import canonical_json, hash_file, hash_frame
from edaforge.config import Budget, EDAForgeConfig, config_hash
from edaforge.errors import ConfigError, ReproductionMismatch
from edaforge.models import AnalyzerRef, DataInput, Finding, LedgerEntry, RunManifest
from edaforge.planner.pipeline import RunResult, SearchSummary, run_pipeline
from edaforge.plugins.registry import AnalyzerRegistry
from edaforge.plugins.sdk import AnalysisData, Analyzer, profile_frame
from edaforge.report.html import render_html_report
from edaforge.runtime.cache import ContentCache
from edaforge.runtime.clock import Clock
from edaforge.runtime.events import Event
from edaforge.runtime.manifest import run_identity
from edaforge.store import FindingsStore

__all__ = [
    "Run",
    "discover",
    "ledger_entries",
    "load_run",
    "read_table",
    "reproduce_from_directory",
]

SOURCE_COLUMN = "__source__"
_RESULT_FILE = "result.json"


def read_table(path: Path) -> pl.DataFrame:
    """Read a CSV, TSV, Parquet, JSON or JSONL file (the full L0 ingest arrives in Phase 1)."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pl.read_csv(path, infer_schema_length=10_000)
    if suffix == ".tsv":
        return pl.read_csv(path, separator="\t", infer_schema_length=10_000)
    if suffix == ".parquet":
        return pl.read_parquet(path)
    if suffix in {".jsonl", ".ndjson"}:
        return pl.read_ndjson(path)
    if suffix == ".json":
        return pl.read_json(path)
    msg = f"unsupported file type {suffix!r} for {path} in Phase 0"
    raise ConfigError(msg)


def _stack(frames: Mapping[str, pl.DataFrame], source_column: str) -> pl.DataFrame:
    """Union same-schema tables, adding the ``__source__`` environment column (section 6, L1)."""
    names = sorted(frames)
    if len(names) == 1:
        return frames[names[0]]
    first = dict(frames[names[0]].schema)
    for name in names[1:]:
        if dict(frames[name].schema) != first:
            msg = (
                f"{name} and {names[0]} have different schemas; joining and aligning different "
                "tables is the Link layer's job (Phase 2)"
            )
            raise ConfigError(msg)
    tagged = [frames[n].with_columns(pl.lit(n).alias(source_column)) for n in names]
    return pl.concat(tagged, how="vertical")


def _merge_config(
    config: EDAForgeConfig | None,
    *,
    mode: str | None,
    targets: Sequence[str] | None,
    budget: Budget | None,
    seed: int | None,
    plugins: Sequence[str] | None,
) -> EDAForgeConfig:
    base = (config or EDAForgeConfig()).model_dump(mode="json")
    if mode is not None:
        base["mode"] = mode
    if targets is not None:
        base["targets"] = list(targets)
    if budget is not None:
        base["budget"] = budget
    if plugins is not None:
        base["plugins"] = sorted({*base["plugins"], *plugins})
    if seed is not None:
        base["compute"] = {**base["compute"], "seed": seed}
    return EDAForgeConfig.model_validate(base)


def _frame_inputs(tables: Mapping[str, pl.DataFrame]) -> list[DataInput]:
    return [
        DataInput(
            name=name,
            sha256=hash_frame(tables[name]),
            n_rows=tables[name].height,
            n_cols=tables[name].width,
            kind="frame",
        )
        for name in sorted(tables)
    ]


def _file_tables(paths: Sequence[Path]) -> tuple[dict[str, pl.DataFrame], list[DataInput]]:
    tables: dict[str, pl.DataFrame] = {}
    inputs: list[DataInput] = []
    for path in paths:
        table = read_table(path)
        if path.stem in tables:
            msg = f"two input files share the name {path.stem!r}"
            raise ConfigError(msg)
        tables[path.stem] = table
        inputs.append(
            DataInput(
                name=path.stem,
                sha256=hash_file(path),
                n_rows=table.height,
                n_cols=table.width,
                kind="file",
                path=str(path.resolve()),
            )
        )
    if not tables:
        msg = "no input files"
        raise ConfigError(msg)
    return tables, inputs


def _analysis(frame: pl.DataFrame, config: EDAForgeConfig, name: str) -> AnalysisData:
    return AnalysisData(
        frame=frame,
        name=name,
        data_hash=hash_frame(frame),
        profile=profile_frame(
            frame, environment_column=config.environments_from, targets=config.targets
        ),
    )


def _registry(analyzers: Sequence[Analyzer], plugins: Sequence[str]) -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    for analyzer in analyzers:
        registry.register(analyzer)
    registry.load_plugins(plugins)
    return registry


class Run:
    """The result of :func:`discover`."""

    def __init__(
        self,
        result: RunResult,
        *,
        data: AnalysisData | None,
        analyzers: Sequence[Analyzer],
        analyzer_refs: Sequence[AnalyzerRef],
        inputs: Sequence[DataInput],
        from_cache: bool = False,
    ) -> None:
        self.result = result
        self.findings = FindingsStore(result.findings)
        self.from_cache = from_cache
        self._data = data
        self._analyzers = list(analyzers)
        self._analyzer_refs = list(analyzer_refs)
        self._inputs = list(inputs)

    @property
    def run_id(self) -> str:
        return self.result.manifest.run_id

    @property
    def manifest(self) -> RunManifest:
        return self.result.manifest

    @property
    def ledger(self) -> list[LedgerEntry]:
        return ledger_entries(self.result)

    @property
    def searched(self) -> tuple[SearchSummary, ...]:
        return self.result.searched

    @property
    def warnings(self) -> tuple[str, ...]:
        return self.result.warnings

    def findings_json(self) -> str:
        return self.findings.to_json()

    def html(self) -> str:
        return _html(self.result)

    def export(self, path: str | Path) -> Path:
        """Write ``.json`` (findings) or ``.html`` (report)."""
        target = Path(path)
        suffix = target.suffix.lower()
        if suffix == ".json":
            target.write_text(self.findings_json(), encoding="utf-8")
        elif suffix in {".html", ".htm"}:
            target.write_text(self.html(), encoding="utf-8")
        else:
            msg = f"unsupported export format {suffix!r} (Phase 0 supports .json and .html)"
            raise ConfigError(msg)
        return target

    def save(self, directory: str | Path, *, include_data: bool = False) -> Path:
        """Write the run directory: result, manifest, findings, ledger, events and report."""
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        _write_result(root, self.result, self._inputs)
        if include_data and self._data is not None:
            self._data.frame.write_parquet(root / "data.parquet")
        return root

    def reproduce(self, finding_id: str) -> Finding:
        """Re-execute from provenance without the cache; the finding must match byte for byte."""
        if self._data is None:
            msg = "this run was loaded without its data; reproduce from a run directory instead"
            raise ReproductionMismatch(msg)
        recorded = self.findings[finding_id]
        fresh = run_pipeline(
            self._data,
            self._analyzers,
            self.result.config,
            analyzer_refs=self._analyzer_refs,
            inputs=self._inputs,
        )
        if fresh.manifest.run_id != self.run_id:
            msg = f"re-execution produced run {fresh.manifest.run_id}, expected {self.run_id}"
            raise ReproductionMismatch(msg)
        matches = [f for f in fresh.findings if f.id == finding_id]
        if not matches:
            msg = f"{finding_id} did not reappear on re-execution"
            raise ReproductionMismatch(msg)
        if canonical_json(matches[0]) != canonical_json(recorded):
            msg = f"{finding_id} differs on re-execution"
            raise ReproductionMismatch(msg)
        return matches[0]


def ledger_entries(result: RunResult) -> list[LedgerEntry]:
    raw = result.ledger.get("entries")
    if not isinstance(raw, list):
        msg = "run result has no ledger entries"
        raise ReproductionMismatch(msg)
    return [LedgerEntry.model_validate(e) for e in raw]


def _html(result: RunResult) -> str:
    return render_html_report(
        manifest=result.manifest,
        manifest_hash=result.manifest_hash,
        findings=result.findings,
        searched=[s.as_row() for s in result.searched],
        warnings=result.warnings,
        locale=result.config.explain.locale,
    )


def _write_result(root: Path, result: RunResult, inputs: Sequence[DataInput]) -> None:
    files = {
        _RESULT_FILE: canonical_json(result, indent=2),
        "manifest.json": canonical_json(result.manifest, indent=2),
        "findings.json": canonical_json(list(result.findings), indent=2),
        "ledger.json": canonical_json(result.ledger, indent=2),
        "events.jsonl": "".join(canonical_json(e) + "\n" for e in result.events),
        "inputs.json": canonical_json(list(inputs), indent=2),
        "report.html": _html(result),
    }
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")


def load_run(directory: str | Path) -> RunResult:
    """Read a run directory written by :meth:`Run.save`."""
    path = Path(directory) / _RESULT_FILE
    if not path.is_file():
        msg = f"{directory} is not a run directory (no {_RESULT_FILE})"
        raise ConfigError(msg)
    return RunResult.model_validate_json(path.read_text("utf-8"))


def discover(
    data: pl.DataFrame | Mapping[str, pl.DataFrame] | Sequence[str | Path],
    *,
    mode: str | None = None,
    targets: Sequence[str] | None = None,
    budget: Budget | None = None,
    config: EDAForgeConfig | None = None,
    analyzers: Sequence[Analyzer] = (),
    plugins: Sequence[str] | None = None,
    seed: int | None = None,
    name: str = "data",
    cache_dir: str | Path | None = None,
    clock: Clock | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> Run:
    """Run the discovery funnel.

    ``data`` is a frame, a mapping of table names to same-schema frames (stacked with a
    ``__source__`` environment column), or a list of file paths.
    """
    cfg = _merge_config(
        config, mode=mode, targets=targets, budget=budget, seed=seed, plugins=plugins
    )
    source_column = cfg.environments_from or SOURCE_COLUMN
    if isinstance(data, pl.DataFrame):
        tables: dict[str, pl.DataFrame] = {name: data}
        inputs = _frame_inputs(tables)
    elif isinstance(data, Mapping):
        tables = dict(data)
        inputs = _frame_inputs(tables)
    else:
        tables, inputs = _file_tables([Path(p) for p in data])
    frame = _stack(tables, source_column)
    registry = _registry(analyzers, cfg.plugins)
    selected = registry.analyzers()
    refs = registry.refs()
    analysis = _analysis(frame, cfg, name)

    cache = ContentCache(Path(cache_dir)) if cache_dir is not None else None
    if cache is not None:
        run_id, _ = run_identity(
            seed=cfg.compute.seed, config_hash=config_hash(cfg), inputs=inputs, analyzers=refs
        )
        cached = cache.get_bytes(ContentCache.key("run", run_id=run_id))
        if cached is not None:
            return Run(
                RunResult.model_validate_json(cached),
                data=analysis,
                analyzers=selected,
                analyzer_refs=refs,
                inputs=inputs,
                from_cache=True,
            )
    result = run_pipeline(
        analysis, selected, cfg, analyzer_refs=refs, inputs=inputs, clock=clock, on_event=on_event
    )
    if cache is not None:
        cache.put_bytes(
            ContentCache.key("run", run_id=result.manifest.run_id),
            canonical_json(result).encode("utf-8"),
        )
    return Run(result, data=analysis, analyzers=selected, analyzer_refs=refs, inputs=inputs)


def reproduce_from_directory(directory: str | Path, finding_id: str) -> Finding:
    """Re-execute a saved run from its inputs and check that ``finding_id`` matches exactly.

    File inputs are re-read from their recorded paths and must match their recorded SHA-256;
    in-memory inputs need the ``data.parquet`` written by ``Run.save(include_data=True)``.
    """
    root = Path(directory)
    recorded = load_run(root)
    raw_inputs: list[object] = json.loads((root / "inputs.json").read_text("utf-8"))
    inputs = [DataInput.model_validate(i) for i in raw_inputs]
    cfg = recorded.config
    if inputs and all(i.kind == "file" for i in inputs):
        paths: list[Path] = []
        for item in inputs:
            if item.path is None or not Path(item.path).is_file():
                msg = f"input {item.name} is no longer at {item.path}"
                raise ReproductionMismatch(msg)
            if hash_file(Path(item.path)) != item.sha256:
                msg = f"input {item.name} changed since the run (SHA-256 mismatch)"
                raise ReproductionMismatch(msg)
            paths.append(Path(item.path))
        tables, _ = _file_tables(paths)
        frame = _stack(tables, cfg.environments_from or SOURCE_COLUMN)
    elif (root / "data.parquet").is_file():
        frame = pl.read_parquet(root / "data.parquet")
    else:
        msg = "the run used in-memory data that was not saved; rerun with save(include_data=True)"
        raise ReproductionMismatch(msg)
    registry = _registry((), cfg.plugins)
    run = Run(
        recorded,
        data=_analysis(frame, cfg, "data"),
        analyzers=registry.analyzers(),
        analyzer_refs=registry.refs(),
        inputs=inputs,
    )
    return run.reproduce(finding_id)
