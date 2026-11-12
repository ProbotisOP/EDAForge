"""Relationship endpoints (milestone 3): suggest, preview, confirm, reject and remove links."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from edaforge.link import (
    LinkError,
    LinkPreview,
    LinkSpec,
    LinkSuggestion,
    Table,
    build_link,
    suggest_links,
)
from edaforge.server.store import LinkMeta, Project, ProjectStore, new_id, now

router = APIRouter()


def _store(request: Request) -> ProjectStore:
    return request.app.state.store


class ConfirmIn(BaseModel):
    spec: LinkSpec
    acknowledged: bool = False


def table_for(store: ProjectStore, project: Project, dataset_id: str) -> Table:
    meta = project.dataset(dataset_id)
    return Table(
        id=meta.id,
        name=meta.name,
        frame=store.frame(project.id, meta.id),
        columns=meta.columns,
        fingerprint=meta.fingerprint,
        sources=tuple(meta.sources),
    )


def ancestry(project: Project) -> dict[str, set[str]]:
    """Every dataset id each dataset was built from (directly or indirectly), plus itself."""
    by_id = {d.id: d for d in project.datasets}
    out: dict[str, set[str]] = {}

    def walk(dataset_id: str) -> set[str]:
        if dataset_id in out:
            return out[dataset_id]
        meta = by_id.get(dataset_id)
        found = {dataset_id}
        if meta is not None:
            for source in meta.sources:
                found |= walk(source)
        out[dataset_id] = found
        return found

    for d in project.datasets:
        walk(d.id)
    # A file's ancestry is just itself; strip self so that siblings from one upload compare.
    return {k: v - {k} | ({k} if by_id[k].kind == "combined" else set()) for k, v in out.items()}


def _same(link: LinkMeta, s: LinkSuggestion) -> bool:
    spec = link.spec
    if {spec.get("left"), spec.get("right")} != {s.left, s.right}:
        return False
    if s.kind == "unrelated":
        return False
    kind_link = "join" if link.kind in {"join", "time_aligned"} else "append"
    kind_s = "join" if s.kind in {"join", "time_aligned"} else "append"
    if kind_link != kind_s:
        return False
    keys = {frozenset((k["left"], k["right"])) for k in spec.get("keys", [])}
    return keys == {frozenset((k.left, k.right)) for k in s.keys}


@router.get("/projects/{project_id}/links/suggestions")
def suggestions(request: Request, project_id: str) -> list[LinkSuggestion]:
    store = _store(request)
    project = store.get(project_id)
    tables = [table_for(store, project, d.id) for d in project.datasets]
    found = suggest_links(tables, ancestry(project))
    for s in found:
        for link in project.links:
            if _same(link, s):
                s.status = link.status
                s.link_id = link.id
    return found


@router.post("/projects/{project_id}/links/preview")
def preview(request: Request, project_id: str, spec: LinkSpec) -> LinkPreview:
    store = _store(request)
    project = store.get(project_id)
    try:
        built = build_link(
            spec, table_for(store, project, spec.left), table_for(store, project, spec.right)
        )
    except LinkError as exc:
        raise HTTPException(422, str(exc)) from exc
    return built.preview


@router.post("/projects/{project_id}/links", status_code=201)
def confirm(request: Request, project_id: str, body: ConfirmIn) -> dict[str, Any]:
    store = _store(request)
    spec = body.spec
    with store.lock(project_id):
        project = store.get(project_id)
        left = table_for(store, project, spec.left)
        right = table_for(store, project, spec.right)
        try:
            built = build_link(spec, left, right)
        except LinkError as exc:
            raise HTTPException(422, str(exc)) from exc
        if built.preview.requires_ack and not body.acknowledged:
            reasons = (
                "; ".join(built.preview.ack_reasons) or "this link needs a review of its warnings"
            )
            raise HTTPException(409, f"Confirm that you have reviewed this: {reasons}.")
        link_id = new_id("l")
        name = spec.name or f"{left.name} + {right.name}"
        dataset = store.add_combined(
            project,
            name=name,
            frame=built.frame,
            columns=built.columns,
            issues=built.issues,
            link_id=link_id,
            sources=[left.id, right.id],
            fingerprint=built.fingerprint,
        )
        report = built.preview.model_dump(mode="json", exclude={"sample"})
        report["acknowledged"] = body.acknowledged
        project.links = [
            item
            for item in project.links
            if not (
                item.status == "rejected"
                and {item.spec.get("left"), item.spec.get("right")} == {spec.left, spec.right}
            )
        ]
        project.links.append(
            LinkMeta(
                id=link_id,
                status="confirmed",
                kind=spec.kind,
                spec=spec.model_dump(mode="json"),
                result_dataset_id=dataset.id,
                report=report,
                created_at=now(),
            )
        )
        store.save(project)
        return {"project": project, "dataset": dataset}


@router.post("/projects/{project_id}/links/reject")
def reject(request: Request, project_id: str, spec: LinkSpec) -> Project:
    store = _store(request)
    with store.lock(project_id):
        project = store.get(project_id)
        project.dataset(spec.left)
        project.dataset(spec.right)
        project.links.append(
            LinkMeta(
                id=new_id("l"),
                status="rejected",
                kind=spec.kind,
                spec=spec.model_dump(mode="json"),
                created_at=now(),
            )
        )
        return store.save(project)


@router.delete("/projects/{project_id}/links/{link_id}")
def remove(request: Request, project_id: str, link_id: str) -> Project:
    """Undo a rejection, or remove a confirmed link with the combined tables built on it."""
    store = _store(request)
    with store.lock(project_id):
        project = store.get(project_id)
        link = project.link(link_id)
        doomed: set[str] = set()
        if link.result_dataset_id:
            doomed.add(link.result_dataset_id)
            changed = True
            while changed:
                changed = False
                for d in project.datasets:
                    if d.id not in doomed and doomed & set(d.sources):
                        doomed.add(d.id)
                        changed = True
        for dataset_id in doomed:
            store.remove_dataset(project, dataset_id)
        project.links = [
            item
            for item in project.links
            if item.id != link_id
            and item.result_dataset_id not in doomed
            and not ({item.spec.get("left"), item.spec.get("right")} & doomed)
        ]
        return store.save(project)
