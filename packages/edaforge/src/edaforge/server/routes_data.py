"""Workspace, upload and dataset endpoints (milestones 1 and 2)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from edaforge.ingest import Role
from edaforge.profile import DatasetProfile, profile_dataset
from edaforge.server.store import DatasetMeta, NotFound, Project, ProjectStore

router = APIRouter()


def _store(request: Request) -> ProjectStore:
    return request.app.state.store


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class RoleIn(BaseModel):
    column: str
    role: Role | None  # None restores the inferred role


def project_summary(project: Project) -> dict[str, Any]:
    latest = max(project.runs, key=lambda r: r.created_at, default=None)
    return {
        "id": project.id,
        "name": project.name,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "n_uploads": len(project.uploads),
        "n_datasets": len(project.datasets),
        "n_failed_uploads": sum(1 for u in project.uploads if u.status == "failed"),
        "latest_run": None
        if latest is None
        else {
            "id": latest.id,
            "status": latest.status,
            "created_at": latest.created_at,
            "n_findings": latest.summary.get("n_findings"),
        },
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/projects")
def list_projects(request: Request) -> list[dict[str, Any]]:
    return [project_summary(p) for p in _store(request).list_projects()]


@router.post("/projects", status_code=201)
def create_project(request: Request, body: ProjectIn) -> Project:
    if not body.name.strip():
        raise HTTPException(422, "The name cannot be blank.")
    return _store(request).create(body.name)


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str) -> Project:
    return _store(request).get(project_id)


@router.patch("/projects/{project_id}")
def rename_project(request: Request, project_id: str, body: ProjectIn) -> Project:
    if not body.name.strip():
        raise HTTPException(422, "The name cannot be blank.")
    return _store(request).rename(project_id, body.name)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(request: Request, project_id: str) -> None:
    _store(request).delete(project_id)


@router.post("/projects/{project_id}/uploads")
def upload_files(
    request: Request, project_id: str, files: Annotated[list[UploadFile], File()]
) -> dict[str, Any]:
    store = _store(request)
    store.get(project_id)
    uploads = [store.add_upload(project_id, f.filename or "upload", f.file) for f in files]
    return {"uploads": uploads, "project": store.get(project_id)}


@router.delete("/projects/{project_id}/uploads/{upload_id}")
def delete_upload(request: Request, project_id: str, upload_id: str) -> Project:
    return _store(request).delete_upload(project_id, upload_id)


@router.get("/projects/{project_id}/datasets/{dataset_id}")
def get_dataset(request: Request, project_id: str, dataset_id: str) -> DatasetMeta:
    return _store(request).get(project_id).dataset(dataset_id)


@router.get("/projects/{project_id}/datasets/{dataset_id}/rows")
def dataset_rows(
    request: Request,
    project_id: str,
    dataset_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    sort: str | None = None,
    desc: bool = False,
) -> dict[str, Any]:
    store = _store(request)
    meta = store.get(project_id).dataset(dataset_id)
    frame = store.frame(project_id, dataset_id)
    if sort is not None:
        if sort not in frame.columns:
            raise HTTPException(422, f"Unknown column {sort!r}.")
        frame = frame.sort(sort, descending=desc, nulls_last=True)
    page = frame.slice(offset, limit)
    info = {c.name: c for c in meta.columns}
    columns = [
        {
            "name": name,
            "dtype": info[name].dtype if name in info else "integer",
            "role": info[name].role if name in info else "internal",
            "pii": info[name].pii if name in info else None,
            "internal": name not in info,
        }
        for name in page.columns
    ]
    return {
        "columns": columns,
        "rows": [list(r) for r in page.rows()],
        "total": frame.height,
        "offset": offset,
        "limit": limit,
    }


@router.patch("/projects/{project_id}/datasets/{dataset_id}/columns")
def set_column_role(
    request: Request, project_id: str, dataset_id: str, body: RoleIn
) -> DatasetMeta:
    try:
        return _store(request).set_role(project_id, dataset_id, body.column, body.role)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


def load_profile(store: ProjectStore, project_id: str, dataset_id: str) -> DatasetProfile:
    """The dataset's profile, computed once and cached until a column role changes."""
    meta = store.get(project_id).dataset(dataset_id)
    path = store.dataset_dir(project_id, dataset_id) / "profile.json"
    cached = store.read_json(path)
    if cached is not None:
        return DatasetProfile.model_validate(cached)
    frame = store.frame(project_id, dataset_id)
    profile = profile_dataset(dataset_id, frame, meta.columns, meta.issues)
    store.write_json(path, profile.model_dump(mode="json"))
    return profile


@router.get("/projects/{project_id}/datasets/{dataset_id}/profile")
def dataset_profile(request: Request, project_id: str, dataset_id: str) -> DatasetProfile:
    return load_profile(_store(request), project_id, dataset_id)
