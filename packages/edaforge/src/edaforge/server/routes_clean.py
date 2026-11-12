"""Clean-up recipes: suggest, preview, apply (as a new table), remove, and export data and code."""

from __future__ import annotations

import hashlib
import io
import json
from typing import Any, Literal

import polars as pl
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from edaforge.clean import CleanError, Step, apply_recipe, recipe_python, recipe_sql, suggest_steps
from edaforge.ingest import ColumnInfo, ParseIssue, is_internal
from edaforge.server.store import DatasetMeta, Project, ProjectStore

router = APIRouter()


class RecipeIn(BaseModel):
    steps: list[Step] = Field(min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=160)


def _store(request: Request) -> ProjectStore:
    return request.app.state.store


def _base(
    store: ProjectStore, project: Project, dataset_id: str, steps: list[Step]
) -> tuple[DatasetMeta, list[Step]]:
    """A cleaned table is re-cleaned from its original source with the combined recipe."""
    meta = project.dataset(dataset_id)
    if meta.kind == "cleaned":
        return project.dataset(meta.sources[0]), [
            Step.model_validate(s) for s in meta.recipe
        ] + steps
    return meta, steps


def _columns(base: DatasetMeta, frame: pl.DataFrame) -> list[ColumnInfo]:
    """Column metadata of the cleaned table: roles carried over, missing counts recomputed."""
    known = {c.name: c for c in base.columns}
    out: list[ColumnInfo] = []
    for name in frame.columns:
        if is_internal(name):
            continue
        missing = int(frame[name].null_count())
        if name in known:
            out.append(known[name].model_copy(update={"n_missing": missing}))
        else:  # a column a step added (a was-missing flag)
            out.append(
                ColumnInfo(
                    name=name,
                    original_name=name,
                    dtype="boolean",
                    role="boolean",
                    role_reason="added by the clean-up recipe",
                    n_missing=missing,
                )
            )
    return out


def _run(store: ProjectStore, project: Project, dataset_id: str, steps: list[Step]):
    base, all_steps = _base(store, project, dataset_id, steps)
    try:
        frame, effects = apply_recipe(store.frame(project.id, base.id), all_steps)
    except CleanError as exc:
        raise HTTPException(422, str(exc)) from exc
    return base, all_steps, frame, effects


@router.get("/projects/{project_id}/datasets/{dataset_id}/clean/suggestions")
def suggestions(request: Request, project_id: str, dataset_id: str) -> list[Step]:
    store = _store(request)
    meta = store.get(project_id).dataset(dataset_id)
    return suggest_steps(store.frame(project_id, dataset_id), meta.columns)


@router.post("/projects/{project_id}/datasets/{dataset_id}/clean/preview")
def preview(request: Request, project_id: str, dataset_id: str, body: RecipeIn) -> dict[str, Any]:
    store = _store(request)
    project = store.get(project_id)
    base, all_steps, frame, effects = _run(store, project, dataset_id, body.steps)
    shown = effects[len(all_steps) - len(body.steps) :]
    user = [c for c in frame.columns if not is_internal(c)]
    return {
        "source": base.name,
        "n_before": store.frame(project_id, base.id).height,
        "n_after": frame.height,
        "effects": [e.model_dump(mode="json") for e in shown],
        "columns": user,
        "sample": [list(r) for r in frame.select(user).head(15).rows()],
    }


@router.post("/projects/{project_id}/datasets/{dataset_id}/clean", status_code=201)
def create(request: Request, project_id: str, dataset_id: str, body: RecipeIn) -> dict[str, Any]:
    store = _store(request)
    with store.lock(project_id):
        project = store.get(project_id)
        base, all_steps, frame, effects = _run(store, project, dataset_id, body.steps)
        recipe = [s.model_dump(mode="json") for s in all_steps]
        fingerprint = hashlib.sha256(
            json.dumps({"source": base.fingerprint, "recipe": recipe}, sort_keys=True).encode()
        ).hexdigest()
        issues = [
            ParseIssue(
                level="info",
                code="cleaned",
                message=(
                    f"Cleaned from {base.name} with {len(all_steps)} step(s); the original "
                    f"is unchanged."
                ),
            )
        ]
        issues += [
            ParseIssue(
                level="warning"
                if e.step.kind in {"fill_missing", "drop_missing", "scale"}
                else "info",
                code=f"clean_{e.step.kind}",
                column=e.step.column,
                message=e.summary,
            )
            for e in effects
        ]
        meta = store.add_cleaned(
            project,
            name=body.name or f"{base.name} (cleaned)",
            frame=frame,
            columns=_columns(base, frame),
            issues=issues,
            source=base.id,
            recipe=recipe,
            fingerprint=fingerprint,
        )
        store.save(project)
        return {"project": project, "dataset": meta}


@router.delete("/projects/{project_id}/datasets/{dataset_id}")
def remove(request: Request, project_id: str, dataset_id: str) -> Project:
    """Remove a cleaned table (and anything built from it).

    Uploaded files are removed via uploads.
    """
    store = _store(request)
    with store.lock(project_id):
        project = store.get(project_id)
        meta = project.dataset(dataset_id)
        if meta.kind != "cleaned":
            raise HTTPException(
                409,
                (
                    "Only cleaned tables are removed here; remove files on the Data page and "
                    "links on Connect."
                ),
            )
        doomed = {dataset_id}
        changed = True
        while changed:
            changed = False
            for d in project.datasets:
                if d.id not in doomed and doomed & set(d.sources):
                    doomed.add(d.id)
                    changed = True
        for d in doomed:
            store.remove_dataset(project, d)
        project.links = [
            link
            for link in project.links
            if link.result_dataset_id not in doomed
            and not ({link.spec.get("left"), link.spec.get("right")} & doomed)
        ]
        return store.save(project)


def _safe_text(frame: pl.DataFrame) -> pl.DataFrame:
    """Neutralize spreadsheet formulas in text cells (a leading ', as in the findings export)."""
    return frame.with_columns(
        pl.when(pl.col(c).str.contains(r"^[=+\-@\t\r]"))
        .then(pl.lit("'") + pl.col(c))
        .otherwise(pl.col(c))
        .alias(c)
        for c, t in frame.schema.items()
        if t == pl.String
    )


@router.get("/projects/{project_id}/datasets/{dataset_id}/export/{fmt}")
def export(
    request: Request,
    project_id: str,
    dataset_id: str,
    fmt: Literal["csv", "parquet", "recipe.py", "recipe.sql"],
) -> Response:
    store = _store(request)
    project = store.get(project_id)
    meta = project.dataset(dataset_id)
    stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in meta.name)[:80] or "table"
    if fmt in {"recipe.py", "recipe.sql"}:
        if meta.kind != "cleaned":
            raise HTTPException(404, "Only cleaned tables have a recipe.")
        steps = [Step.model_validate(s) for s in meta.recipe]
        source = project.dataset(meta.sources[0])
        if fmt == "recipe.py":
            body = recipe_python(
                steps, source=source.name, types={c.name: c.dtype for c in source.columns}
            )
            return Response(
                body,
                media_type="text/x-python",
                headers={"Content-Disposition": f'attachment; filename="{stem}-recipe.py"'},
            )
        cols = [c.name for c in source.columns]
        body = recipe_sql(steps, cols, types={c.name: c.dtype for c in source.columns})
        return Response(
            body,
            media_type="application/sql",
            headers={"Content-Disposition": f'attachment; filename="{stem}-recipe.sql"'},
        )
    frame = store.frame(project_id, dataset_id)
    frame = frame.select([c for c in frame.columns if not is_internal(c)])
    buf = io.BytesIO()
    if fmt == "csv":
        _safe_text(frame).write_csv(buf)
        return Response(
            buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
        )
    frame.write_parquet(buf)
    return Response(
        buf.getvalue(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{stem}.parquet"'},
    )
