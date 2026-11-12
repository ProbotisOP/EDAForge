"""Discovery runs: start, stream progress, read results, cancel, export (milestones 4 to 6)."""

from __future__ import annotations

import csv
import io
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from edaforge.canonical import canonical_json
from edaforge.discovery.run import (
    Prepared,
    RunCancelled,
    RunSettings,
    SettingsError,
    execute,
    prepare,
)
from edaforge.report.app_report import render_run_report
from edaforge.runtime.events import Event
from edaforge.server.routes_data import load_profile
from edaforge.server.store import NotFound, ProjectStore, RunMeta, new_id, now

router = APIRouter()
_TERMINAL = {"run_finished", "run_failed", "run_cancelled"}


@dataclass
class _Live:
    events: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    cond: threading.Condition = field(default_factory=threading.Condition)
    cancel: bool = False
    done: bool = False

    def emit(
        self, kind: str, message: str, data: dict[str, Any] | None = None, stage: str | None = None
    ) -> None:
        with self.cond:
            self.events.append(
                {
                    "seq": len(self.events) + 1,
                    "kind": kind,
                    "stage": stage,
                    "message": message,
                    "data": data or {},
                }
            )
            if kind in _TERMINAL:
                self.done = True
            self.cond.notify_all()


class _PayloadCache:
    """Parsed ``feed.json`` files of recent runs, so a request does not re-read a whole feed.

    A run writes its feed once, when it completes. An entry is used only while the file's
    modification time and size are unchanged. Callers must not modify what :meth:`get` returns.
    """

    def __init__(self, max_entries: int = 4, max_bytes: int = 64 * 1024 * 1024) -> None:
        self._lock = threading.Lock()
        self._entries: OrderedDict[Path, tuple[tuple[int, int], dict[str, Any]]] = OrderedDict()
        self._max_entries = max_entries
        self._max_bytes = max_bytes

    def get(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        version = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            hit = self._entries.get(path)
            if hit is not None and hit[0] == version:
                self._entries.move_to_end(path)
                return hit[1]
        data: dict[str, Any] = json.loads(path.read_text("utf-8"))
        with self._lock:
            self._entries[path] = (version, data)
            self._entries.move_to_end(path)
            while self._entries and (
                len(self._entries) > self._max_entries
                or sum(v[1] for v, _ in self._entries.values()) > self._max_bytes
            ):
                self._entries.popitem(last=False)
        return data

    def forget(self, path: Path) -> None:
        with self._lock:
            self._entries.pop(path, None)


class RunManager:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self.live: dict[str, _Live] = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="edaforge-run")
        self.lock = threading.Lock()
        self.payloads = _PayloadCache()

    def start(self, project_id: str, settings: RunSettings) -> RunMeta:
        with self.store.lock(project_id):
            project = self.store.get(project_id)
            meta = project.dataset(settings.dataset_id)
            frame = self.store.frame(project_id, meta.id)
            prepared = prepare(meta.columns, frame, settings)
            run = RunMeta(
                id=new_id("r"),
                dataset_id=meta.id,
                status="queued",
                settings=settings.model_dump(mode="json"),
                created_at=now(),
                summary={
                    "dataset": meta.name,
                    "plan": [p.model_dump(mode="json") for p in prepared.plan],
                    "notes": prepared.notes,
                },
            )
            project.runs.append(run)
            self.store.save(project)
        live = _Live()
        with self.lock:
            self.live[run.id] = live
        live.emit("run_queued", f"Queued analysis of {meta.name}", {"dataset": meta.name})
        self.pool.submit(
            self._run, project_id, run.id, prepared, meta.name, meta.fingerprint, meta.id, live
        )
        return run

    def _set(self, project_id: str, run_id: str, **changes: Any) -> None:
        with self.store.lock(project_id):
            project = self.store.get(project_id)
            run = project.run(run_id)
            for key, value in changes.items():
                setattr(run, key, value)
            self.store.save(project)

    def _run(
        self,
        project_id: str,
        run_id: str,
        prepared: Prepared,
        name: str,
        fingerprint: str,
        dataset_id: str,
        live: _Live,
    ) -> None:
        directory = self.store.run_dir(project_id, run_id)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            self._set(project_id, run_id, status="running")
            live.emit(
                "run_started",
                f"Analyzing {prepared.frame.height:,} rows of {name}",
                {
                    "rows": prepared.frame.height,
                    "plan": [p.model_dump(mode="json") for p in prepared.plan],
                },
            )
            profile = load_profile(self.store, project_id, dataset_id)
            live.emit("progress", "Data profile ready", {"stage": "profile"}, "profile")

            def on_event(event: Event) -> None:
                if live.cancel:
                    raise RunCancelled
                kind = (
                    "pipeline_finished"
                    if event.kind == "run_finished"
                    else ("pipeline_started" if event.kind == "run_started" else event.kind)
                )
                live.emit(kind, event.message, dict(event.data), event.stage)

            outcome = execute(
                prepared,
                dataset_name=name,
                fingerprint=fingerprint,
                profile=profile,
                on_event=on_event,
            )
            live.emit("progress", "Building the Insight Feed", {"stage": "feed"}, "feed")
            (directory / "result.json").write_text(canonical_json(outcome.result), encoding="utf-8")
            payload: dict[str, Any] = {
                "feed": outcome.feed,
                "details": outcome.details,
                "plan": [p.model_dump(mode="json") for p in outcome.plan],
                "notes": outcome.notes,
                "warnings": outcome.warnings,
                "searched": [s.model_dump(mode="json") for s in outcome.result.searched],
                "split": outcome.result.manifest.split.model_dump(mode="json")
                if outcome.result.manifest.split
                else {},
                "manifest": outcome.result.manifest.model_dump(mode="json"),
                "seconds": outcome.seconds,
                "spec": {
                    "target": prepared.spec.target,
                    "target_kind": prepared.spec.target_kind,
                    "positive": prepared.spec.positive,
                    "time_column": prepared.spec.time_column,
                    "environment": prepared.spec.environment,
                    "numeric": list(prepared.spec.numeric),
                    "categorical": list(prepared.spec.categorical),
                    "rows": prepared.frame.height,
                },
            }
            (directory / "feed.json").write_text(
                json.dumps(payload, default=str, ensure_ascii=False), encoding="utf-8"
            )
            leaders = [i for i in outcome.feed if not i.get("merged_into")]
            summary: dict[str, Any] = {
                "dataset": name,
                "n_findings": sum(
                    1
                    for i in leaders
                    if i["evidence"]["basis"] == "inferential"
                    and i["evidence"]["grade"] in {"A", "B", "C", "D"}
                ),
                "n_confirmed": sum(
                    1 for i in leaders if i["evidence"]["confirmation"].startswith("confirmed")
                ),
                "n_facts": sum(1 for i in leaders if i["evidence"]["basis"] == "descriptive"),
                "n_tested": sum(s.tested for s in outcome.result.searched),
                "mode": payload["split"].get("mode"),
                "seconds": round(outcome.seconds, 1),
                "plan": payload["plan"],
                "notes": outcome.notes,
            }
            self._set(project_id, run_id, status="completed", finished_at=now(), summary=summary)
            live.emit(
                "run_finished",
                f"{summary['n_findings']} findings, {summary['n_facts']} data facts",
                summary,
            )
        except RunCancelled:
            self._set(project_id, run_id, status="cancelled", finished_at=now())
            live.emit("run_cancelled", "The run was cancelled; no results were kept.")
        except Exception as exc:  # noqa: BLE001 - the user sees the failure, the server keeps running
            self._set(
                project_id,
                run_id,
                status="failed",
                finished_at=now(),
                error=f"{type(exc).__name__}: {exc}",
            )
            live.emit("run_failed", f"The analysis failed: {type(exc).__name__}: {exc}")
        finally:
            (directory / "events.jsonl").write_text(
                "".join(json.dumps(e, default=str) + "\n" for e in live.events), encoding="utf-8"
            )

    def cancel(self, run_id: str) -> bool:
        live = self.live.get(run_id)
        if live is None or live.done:
            return False
        live.cancel = True
        return True

    def stream(self, project_id: str, run_id: str) -> Iterator[str]:
        live = self.live.get(run_id)
        if live is None:
            path = self.store.run_dir(project_id, run_id) / "events.jsonl"
            events = (
                [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]
                if path.is_file()
                else []
            )
            if not events or events[-1]["kind"] not in _TERMINAL:
                status = self.store.get(project_id).run(run_id).status
                events.append(
                    {
                        "seq": len(events) + 1,
                        "kind": "run_failed" if status != "completed" else "run_finished",
                        "message": "The server restarted during this run."
                        if status in {"running", "queued"}
                        else status,
                        "data": {},
                    }
                )
            for e in events:
                yield f"data: {json.dumps(e, default=str)}\n\n"
            return
        sent = 0
        last = time.monotonic()
        while True:
            with live.cond:
                if sent >= len(live.events) and not live.done:
                    live.cond.wait(timeout=10)
                batch = live.events[sent:]
                done = live.done
            for e in batch:
                yield f"data: {json.dumps(e, default=str)}\n\n"
            sent += len(batch)
            if done and sent >= len(live.events):
                return
            if time.monotonic() - last > 10:
                yield ": keep-alive\n\n"
                last = time.monotonic()


def _store(request: Request) -> ProjectStore:
    return request.app.state.store


def manager(request: Request) -> RunManager:
    app = request.app
    if not hasattr(app.state, "runs"):
        app.state.runs = RunManager(app.state.store)
    return app.state.runs


def _payload(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
    path = _store(request).run_dir(project_id, run_id) / "feed.json"
    if not path.is_file():
        raise HTTPException(409, "This run has no results yet.")
    return manager(request).payloads.get(path)


def _scope_tables(store: ProjectStore, project: Any, ids: list[str]) -> list[Any]:
    from edaforge.server.routes_links import table_for

    if len(set(ids)) != len(ids):
        raise HTTPException(422, "A table is listed twice.")
    return [table_for(store, project, i) for i in ids]


@router.post("/projects/{project_id}/scope/plan")
def scope_plan(request: Request, project_id: str, body: dict[str, list[str]]) -> dict[str, Any]:
    """How the chosen tables would be connected, previewed step by step. Nothing is stored."""
    from edaforge.link import LinkError
    from edaforge.link.scope import plan_scope

    store = _store(request)
    project = store.get(project_id)
    try:
        result, _ = plan_scope(_scope_tables(store, project, body.get("dataset_ids", [])))
    except LinkError as exc:
        raise HTTPException(422, str(exc)) from exc
    return result.model_dump(mode="json")


def _materialize(store: ProjectStore, project_id: str, settings: RunSettings) -> RunSettings:
    """Build (or reuse) the combined tables of a multi-table scope.

    Returns the settings for the result.
    """
    from edaforge.link import LinkError
    from edaforge.link.scope import build_scope
    from edaforge.server.store import LinkMeta

    with store.lock(project_id):
        project = store.get(project_id)
        try:
            plan, built = build_scope(
                _scope_tables(store, project, settings.scope), acknowledged=settings.acknowledged
            )
        except LinkError as exc:
            raise HTTPException(409 if "Confirm" in str(exc) else 422, str(exc)) from exc
        if built is None or not built.steps:
            raise HTTPException(
                422,
                "These tables do not connect: "
                + "; ".join(f"{u['table']}: {u['reason']}" for u in plan.unconnected),
            )
        real: dict[str, str] = {}
        final = ""
        for k, (step, link) in enumerate(built.steps, start=1):
            spec = step.spec.model_copy(
                update={
                    "left": real.get(step.spec.left, step.spec.left),
                    "right": real.get(step.spec.right, step.spec.right),
                }
            )
            existing = next(
                (d for d in project.datasets if d.fingerprint == link.fingerprint), None
            )
            if existing is None:
                link_id = new_id("l")
                existing = store.add_combined(
                    project,
                    name=step.result_name,
                    frame=link.frame,
                    columns=link.columns,
                    issues=link.issues,
                    link_id=link_id,
                    sources=[spec.left, spec.right],
                    fingerprint=link.fingerprint,
                )
                report = link.preview.model_dump(mode="json", exclude={"sample"})
                report["acknowledged"] = settings.acknowledged
                report["created_by"] = "discovery scope"
                project.links.append(
                    LinkMeta(
                        id=link_id,
                        status="confirmed",
                        kind=spec.kind,
                        spec=spec.model_dump(mode="json"),
                        result_dataset_id=existing.id,
                        report=report,
                        created_at=now(),
                    )
                )
            real[f"scope-{k}"] = existing.id
            final = existing.id
        store.save(project)
    notes = [
        (
            f"Connected {', '.join(plan.tables)} in {len(plan.steps)} "
            f"step{'s' if len(plan.steps) > 1 else ''} (see Connect)."
        )
    ]
    notes += [f"{u['table']} was left out: {u['reason']}." for u in plan.unconnected]
    return settings.model_copy(update={"dataset_id": final, "scope_notes": notes})


@router.post("/projects/{project_id}/runs/plan")
def plan(request: Request, project_id: str, settings: RunSettings) -> dict[str, Any]:
    from edaforge.link import LinkError
    from edaforge.link.scope import plan_scope

    store = _store(request)
    project = store.get(project_id)
    extra: list[str] = []
    try:
        if len(settings.scope) > 1:
            try:
                scope, built = plan_scope(_scope_tables(store, project, settings.scope))
            except LinkError as exc:
                raise HTTPException(422, str(exc)) from exc
            if built is None or not built.steps:
                raise HTTPException(
                    422, "These tables do not connect, so they cannot be analyzed together."
                )
            columns, frame = built.table.columns, built.table.frame
            extra = [f"{u['table']} is left out: {u['reason']}." for u in scope.unconnected]
        else:
            meta = project.dataset(settings.scope[0] if settings.scope else settings.dataset_id)
            columns, frame = meta.columns, store.frame(project_id, meta.id)
        prepared = prepare(columns, frame, settings)
    except SettingsError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "plan": [p.model_dump(mode="json") for p in prepared.plan],
        "notes": extra + prepared.notes,
        "rows": prepared.frame.height,
    }


@router.post("/projects/{project_id}/runs", status_code=201)
def start(request: Request, project_id: str, settings: RunSettings) -> dict[str, Any]:
    if len(settings.scope) > 1:
        settings = _materialize(_store(request), project_id, settings)
    elif settings.scope:
        settings = settings.model_copy(update={"dataset_id": settings.scope[0]})
    try:
        run = manager(request).start(project_id, settings)
    except SettingsError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"run_id": run.id, "project": _store(request).get(project_id)}


@router.get("/projects/{project_id}/runs/{run_id}")
def get_run(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
    store = _store(request)
    project = store.get(project_id)
    run = project.run(run_id)
    try:
        dataset = project.dataset(run.dataset_id)
        ds = {
            "id": dataset.id,
            "name": dataset.name,
            "n_rows": dataset.n_rows,
            "n_cols": dataset.n_cols,
        }
    except NotFound:
        ds = {
            "id": run.dataset_id,
            "name": run.summary.get("dataset", "(removed)"),
            "n_rows": 0,
            "n_cols": 0,
        }
    if run.status != "completed":
        return {
            "run": run,
            "dataset": ds,
            "plan": run.summary.get("plan", []),
            "feed": [],
            "searched": [],
            "split": {},
            "warnings": [],
            "manifest": {},
            "null_results": [],
            "notes": run.summary.get("notes", []),
        }
    data = _payload(request, project_id, run_id)
    labels = {p["analyzer"]: p["label"] for p in data["plan"]}
    found = {d["method"]["analyzer"] for d in data["details"].values()}
    searched = [{**s, "label": labels.get(s["analyzer"], s["analyzer"])} for s in data["searched"]]
    null_results = [
        {
            "analyzer": s["analyzer"],
            "label": s["label"],
            "message": (
                f"Tested {s['tested']:,} hypotheses; none held up after false-discovery control."
            ),
        }
        for s in searched
        if s["analyzer"] not in found
        or not any(
            d["method"]["analyzer"] == s["analyzer"]
            and d["evidence"]["grade"] in {"A", "B", "C", "D"}
            for d in data["details"].values()
        )
    ]
    return {
        "run": run,
        "dataset": ds,
        "plan": data["plan"],
        "feed": data["feed"],
        "searched": searched,
        "split": data["split"],
        "warnings": data["warnings"],
        "manifest": data["manifest"],
        "null_results": null_results,
        "notes": data["notes"],
        "spec": data.get("spec", {}),
    }


@router.get("/projects/{project_id}/runs/{run_id}/events")
def events(request: Request, project_id: str, run_id: str) -> StreamingResponse:
    store = _store(request)
    store.get(project_id).run(run_id)
    return StreamingResponse(
        manager(request).stream(project_id, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/projects/{project_id}/runs/{run_id}/cancel", status_code=204)
def cancel(request: Request, project_id: str, run_id: str) -> None:
    _store(request).get(project_id).run(run_id)
    if not manager(request).cancel(run_id):
        raise HTTPException(409, "The run is not running.")


@router.delete("/projects/{project_id}/runs/{run_id}")
def delete_run(request: Request, project_id: str, run_id: str) -> Any:
    store = _store(request)
    with store.lock(project_id):
        project = store.get(project_id)
        run = project.run(run_id)
        if run.status in {"queued", "running"}:
            raise HTTPException(409, "Cancel the run before deleting it.")
        import shutil

        shutil.rmtree(store.run_dir(project_id, run_id), ignore_errors=True)
        manager(request).payloads.forget(store.run_dir(project_id, run_id) / "feed.json")
        project.runs = [r for r in project.runs if r.id != run_id]
        return store.save(project)


@router.get("/projects/{project_id}/runs/{run_id}/universe")
def universe(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
    """The run's findings as a graph of columns (nodes) and relationships (edges)."""
    from edaforge.discovery.universe import build_universe

    store = _store(request)
    project = store.get(project_id)
    run = project.run(run_id)
    data = _payload(request, project_id, run_id)
    roles: dict[str, str] = {}
    frame = None
    if any(d.id == run.dataset_id for d in project.datasets):
        roles = {c.name: c.role for c in project.dataset(run.dataset_id).columns}
        frame = store.frame(project_id, run.dataset_id)
    return build_universe(data, roles, frame)


@router.get("/projects/{project_id}/runs/{run_id}/findings/{finding_id}")
def finding(request: Request, project_id: str, run_id: str, finding_id: str) -> dict[str, Any]:
    data = _payload(request, project_id, run_id)
    detail = data["details"].get(finding_id)
    if detail is None:
        raise HTTPException(404, "finding not found")
    return detail


def _safe_cell(value: Any) -> str:
    """CSV cell text that spreadsheet programs will not execute as a formula."""
    text = "" if value is None else str(value)
    if text[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text
    return text


@router.get("/projects/{project_id}/runs/{run_id}/export/{fmt}")
def export(request: Request, project_id: str, run_id: str, fmt: str) -> Response:
    store = _store(request)
    project = store.get(project_id)
    run = project.run(run_id)
    data = _payload(request, project_id, run_id)
    stem = f"edaforge-{run_id}"
    if fmt == "json":
        body = {
            "about": "EDAForge findings export. Every number was computed by the "
            "analysis engine; "
            "grades A-E summarize evidence; 'fact' items are exact descriptive checks.",
            "workspace": project.name,
            "run": run.model_dump(mode="json"),
            "manifest": data["manifest"],
            "split": data["split"],
            "plan": data["plan"],
            "notes": data["notes"],
            "searched": data["searched"],
            "findings": [
                {
                    **{k: v for k, v in d.items() if k not in {"charts", "chart"}},
                    "lenses": {k: v["markdown"] for k, v in d["lenses"].items()},
                }
                for d in (data["details"][i["id"]] for i in data["feed"])
            ],
        }
        return Response(
            json.dumps(body, indent=2, default=str, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{stem}-findings.json"'},
        )
    if fmt in {"csv", "quality.csv"}:
        out = io.StringIO()
        writer = csv.writer(out)
        if fmt == "csv":
            writer.writerow(
                [
                    "rank",
                    "id",
                    "pattern_type",
                    "headline",
                    "variables",
                    "effect",
                    "records",
                    "evidence",
                    "grade",
                    "confirmation",
                    "q_value",
                    "caveats",
                    "merged_into",
                ]
            )
            for i in data["feed"]:
                ev = i["evidence"]
                writer.writerow(
                    [
                        _safe_cell(v)
                        for v in [
                            i["rank"],
                            i["id"],
                            i["family_label"],
                            i["headline"],
                            "; ".join(i["variables"]),
                            f"{i['effect_label']}: {i['effect_text']}"
                            if i.get("effect_text")
                            else "",
                            i.get("records_label") or "",
                            ev["basis"],
                            ev.get("grade") or "",
                            ev["confirmation"],
                            ev.get("q_value") if ev.get("q_value") is not None else "",
                            " | ".join(i["caveats"]),
                            i.get("merged_into") or "",
                        ]
                    ]
                )
        else:
            profile = load_profile(store, project_id, run.dataset_id)
            writer.writerow(
                [
                    "id",
                    "severity",
                    "category",
                    "title",
                    "columns",
                    "count",
                    "share",
                    "rule",
                    "examples",
                    "rows",
                ]
            )
            for q in profile.issues:
                writer.writerow(
                    [
                        _safe_cell(v)
                        for v in [
                            q.id,
                            q.severity,
                            q.category,
                            q.title,
                            "; ".join(q.columns),
                            q.count or "",
                            q.share or "",
                            q.method,
                            "; ".join(q.examples),
                            "; ".join(str(r) for r in q.rows),
                        ]
                    ]
                )
        name = "findings" if fmt == "csv" else "data-quality"
        return Response(
            out.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}-{name}.csv"'},
        )
    raise HTTPException(404, "Unknown export format.")


class ReportIn(BaseModel):
    charts: dict[str, str] = {}


@router.post("/projects/{project_id}/runs/{run_id}/report")
def report(request: Request, project_id: str, run_id: str, body: ReportIn) -> HTMLResponse:
    store = _store(request)
    project = store.get(project_id)
    run = project.run(run_id)
    data = _payload(request, project_id, run_id)
    profile = (
        load_profile(store, project_id, run.dataset_id)
        if any(d.id == run.dataset_id for d in project.datasets)
        else None
    )
    html = render_run_report(
        project_name=project.name,
        run=run.model_dump(mode="json"),
        data=data,
        profile=profile,
        charts=body.charts,
    )
    return HTMLResponse(
        html,
        headers={"Content-Disposition": f'attachment; filename="edaforge-{run_id}-report.html"'},
    )
