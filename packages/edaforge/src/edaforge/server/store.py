"""Local project storage (PROJECT_PROMPT.md section 9, "Local project storage").

Layout under ``EDAFORGE_HOME`` (default ``~/.edaforge``)::

    projects/<project-id>/project.json          metadata: uploads, datasets, links, runs
    projects/<project-id>/uploads/<id>/original.<ext>
    projects/<project-id>/datasets/<id>/data.parquet   typed table (``__row__`` first)
    projects/<project-id>/datasets/<id>/profile.json   cached profile
    projects/<project-id>/runs/<id>/...                 discovery results

IDs are generated here and validated on every request; uploaded file names are display text only
and never become part of a path. Writes are atomic (temporary file, then rename).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from edaforge.ingest import (
    ColumnInfo,
    IngestError,
    IngestLimits,
    ParseIssue,
    Role,
    detect_format,
    ingest_file,
)

__all__ = [
    "DatasetMeta",
    "LinkMeta",
    "NotFound",
    "Project",
    "ProjectStore",
    "RunMeta",
    "UploadMeta",
    "default_home",
    "now",
]

_ID = re.compile(r"^[pudlr]_[0-9a-f]{10}$")


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: Literal["p", "u", "d", "l", "r"]) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def default_home() -> Path:
    return Path(os.environ.get("EDAFORGE_HOME", Path.home() / ".edaforge"))


class NotFound(Exception):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class UploadMeta(_Model):
    id: str
    filename: str
    format: str | None = None
    size_bytes: int = 0
    sha256: str = ""
    uploaded_at: datetime
    status: Literal["parsed", "failed"]
    error: str | None = None
    issues: list[ParseIssue] = []
    dataset_ids: list[str] = []


class ParseHealth(_Model):
    """A traffic light computed when a table is read: missing cells, empty columns, duplicates.

    green: no empty columns, under 1% of cells missing and no duplicate rows;
    red: no rows, 20% or more of cells missing, or 10% or more of rows duplicated;
    yellow: anything in between. The counts behind the colour are always shown with it.
    """

    status: Literal["green", "yellow", "red"]
    missing_share: float
    empty_columns: list[str] = []
    duplicate_rows: int = 0
    reasons: list[str] = []


def parse_health(frame: pl.DataFrame) -> ParseHealth:
    user = frame.select([c for c in frame.columns if not c.startswith("__")])
    rows, cols = user.height, user.width
    if rows == 0 or cols == 0:
        return ParseHealth(status="red", missing_share=0.0, reasons=["the table has no rows"])
    nulls = user.null_count().row(0)
    missing = sum(nulls) / (rows * cols)
    empty = [c for c, n in zip(user.columns, nulls, strict=True) if n == rows]
    dups = rows - user.n_unique()
    reasons: list[str] = []
    if missing:
        reasons.append(f"{missing:.1%} of cells are empty")
    if empty:
        reasons.append(
            f"{len(empty)} column{'s are' if len(empty) > 1 else ' is'} completely "
            f"empty: {', '.join(empty[:5])}"
        )
    if dups:
        reasons.append(f"{dups:,} duplicate row{'s' if dups > 1 else ''} ({dups / rows:.1%})")
    if missing >= 0.20 or dups / rows >= 0.10:
        status: Literal["green", "yellow", "red"] = "red"
    elif missing >= 0.01 or empty or dups:
        status = "yellow"
    else:
        status = "green"
    return ParseHealth(
        status=status,
        missing_share=missing,
        empty_columns=empty,
        duplicate_rows=dups,
        reasons=reasons or ["no empty cells, empty columns or duplicate rows"],
    )


class DatasetMeta(_Model):
    id: str
    name: str
    kind: Literal["file", "combined", "cleaned"]
    upload_id: str | None = None
    sheet: str | None = None
    n_rows: int
    n_cols: int
    columns: list[ColumnInfo]
    issues: list[ParseIssue] = []
    fingerprint: str
    created_at: datetime
    link_id: str | None = None  # for combined datasets: the link that produced it
    sources: list[str] = []  # dataset ids this one was built from
    health: ParseHealth | None = None
    recipe: list[dict[str, Any]] = []  # cleaned tables: the steps applied to sources[0]


class LinkMeta(_Model):
    id: str
    status: Literal["confirmed", "rejected"]
    kind: Literal["join", "append", "time_aligned"]
    spec: dict[str, Any]
    result_dataset_id: str | None = None
    report: dict[str, Any] = {}
    created_at: datetime


class RunMeta(_Model):
    id: str
    dataset_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    settings: dict[str, Any] = {}
    created_at: datetime
    finished_at: datetime | None = None
    summary: dict[str, Any] = {}
    error: str | None = None


class Project(_Model):
    id: str
    name: str = Field(min_length=1, max_length=120)
    created_at: datetime
    updated_at: datetime
    uploads: list[UploadMeta] = []
    datasets: list[DatasetMeta] = []
    links: list[LinkMeta] = []
    runs: list[RunMeta] = []

    def dataset(self, dataset_id: str) -> DatasetMeta:
        for d in self.datasets:
            if d.id == dataset_id:
                return d
        msg = f"dataset {dataset_id} not found"
        raise NotFound(msg)

    def run(self, run_id: str) -> RunMeta:
        for r in self.runs:
            if r.id == run_id:
                return r
        msg = f"run {run_id} not found"
        raise NotFound(msg)

    def link(self, link_id: str) -> LinkMeta:
        for item in self.links:
            if item.id == link_id:
                return item
        msg = f"link {link_id} not found"
        raise NotFound(msg)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class ProjectStore:
    """All project state on disk, with a small in-memory cache of parsed tables."""

    def __init__(self, home: Path, limits: IngestLimits | None = None) -> None:
        self.home = home
        self.root = home / "projects"
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = limits or IngestLimits()
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()
        self._frames: OrderedDict[tuple[str, str], pl.DataFrame] = OrderedDict()
        self._frame_cache_size = 8

    # ------------------------------------------------------------------ paths and locks
    def lock(self, project_id: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(project_id, threading.RLock())

    def _dir(self, project_id: str) -> Path:
        if not _ID.match(project_id) or not project_id.startswith("p_"):
            msg = "project not found"
            raise NotFound(msg)
        return self.root / project_id

    def dataset_dir(self, project_id: str, dataset_id: str) -> Path:
        if not _ID.match(dataset_id):
            msg = "dataset not found"
            raise NotFound(msg)
        return self._dir(project_id) / "datasets" / dataset_id

    def run_dir(self, project_id: str, run_id: str) -> Path:
        if not _ID.match(run_id):
            msg = "run not found"
            raise NotFound(msg)
        return self._dir(project_id) / "runs" / run_id

    # ------------------------------------------------------------------ projects
    def list_projects(self) -> list[Project]:
        projects: list[Project] = []
        for path in sorted(self.root.glob("p_*/project.json")):
            try:
                projects.append(Project.model_validate_json(path.read_text("utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(projects, key=lambda p: p.updated_at, reverse=True)

    def get(self, project_id: str) -> Project:
        path = self._dir(project_id) / "project.json"
        if not path.is_file():
            msg = "project not found"
            raise NotFound(msg)
        return Project.model_validate_json(path.read_text("utf-8"))

    def save(self, project: Project) -> Project:
        project.updated_at = now()
        _atomic_write(self._dir(project.id) / "project.json", project.model_dump_json(indent=2))
        return project

    def create(self, name: str) -> Project:
        stamp = now()
        project = Project(id=new_id("p"), name=name.strip(), created_at=stamp, updated_at=stamp)
        self._dir(project.id).mkdir(parents=True)
        return self.save(project)

    def rename(self, project_id: str, name: str) -> Project:
        with self.lock(project_id):
            project = self.get(project_id)
            project.name = name.strip()
            return self.save(project)

    def delete(self, project_id: str) -> None:
        directory = self._dir(project_id)
        if not (directory / "project.json").is_file():
            msg = "project not found"
            raise NotFound(msg)
        with self.lock(project_id):
            shutil.rmtree(directory)
        with self._guard:
            for key in [k for k in self._frames if k[0] == project_id]:
                del self._frames[key]

    # ------------------------------------------------------------------ uploads
    def _unique_name(self, project: Project, name: str) -> str:
        taken = {d.name for d in project.datasets}
        if name not in taken:
            return name
        k = 2
        while f"{name} ({k})" in taken:
            k += 1
        return f"{name} ({k})"

    def add_upload(self, project_id: str, filename: str, stream: BinaryIO) -> UploadMeta:
        """Store and parse one uploaded file. Parsing failures are recorded, not raised."""
        display = Path(filename.replace("\\", "/")).name or "upload"
        upload_id = new_id("u")
        stamp = now()
        try:
            fmt = detect_format(display)
        except IngestError as exc:
            upload = UploadMeta(
                id=upload_id, filename=display, uploaded_at=stamp, status="failed", error=str(exc)
            )
            with self.lock(project_id):
                project = self.get(project_id)
                project.uploads.append(upload)
                self.save(project)
            return upload
        directory = self._dir(project_id) / "uploads" / upload_id
        directory.mkdir(parents=True)
        target = directory / f"original.{fmt}"
        digest = hashlib.sha256()
        size = 0
        too_big = False
        with target.open("wb") as out:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                size += len(chunk)
                if size > self.limits.max_bytes:
                    too_big = True
                    break
                digest.update(chunk)
                out.write(chunk)
        if too_big:
            target.unlink(missing_ok=True)
            limit = self.limits.max_bytes / 1e6
            upload = UploadMeta(
                id=upload_id,
                filename=display,
                format=fmt,
                size_bytes=size,
                uploaded_at=stamp,
                status="failed",
                error=f"The file is larger than the {limit:.0f} MB upload limit.",
            )
            with self.lock(project_id):
                project = self.get(project_id)
                project.uploads.append(upload)
                self.save(project)
            return upload
        sha = digest.hexdigest()
        tables: list[Any] = []
        try:
            _, tables = ingest_file(target, filename=display, scratch=directory, limits=self.limits)
        except IngestError as exc:
            upload = UploadMeta(
                id=upload_id,
                filename=display,
                format=fmt,
                size_bytes=size,
                sha256=sha,
                uploaded_at=stamp,
                status="failed",
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - unexpected parser failures are reported too
            upload = UploadMeta(
                id=upload_id,
                filename=display,
                format=fmt,
                size_bytes=size,
                sha256=sha,
                uploaded_at=stamp,
                status="failed",
                error=f"The file could not be read ({type(exc).__name__}: {exc}).",
            )
        else:
            upload = UploadMeta(
                id=upload_id,
                filename=display,
                format=fmt,
                size_bytes=size,
                sha256=sha,
                uploaded_at=stamp,
                status="parsed",
            )
        (directory / "decoded.txt").unlink(missing_ok=True)
        with self.lock(project_id):
            project = self.get(project_id)
            duplicate = next(
                (u for u in project.uploads if u.sha256 == sha and u.status == "parsed"), None
            )
            if duplicate is not None:
                upload.issues.append(
                    ParseIssue(
                        level="warning",
                        code="duplicate_upload",
                        message=(
                            f"This file is identical to {duplicate.filename!r}, uploaded before."
                        ),
                    )
                )
            if upload.status == "parsed":
                for table in tables:
                    dataset_id = new_id("d")
                    name = f"{display} › {table.sheet}" if table.sheet else display
                    folder = self.dataset_dir(project_id, dataset_id)
                    folder.mkdir(parents=True)
                    table.frame.write_parquet(folder / "data.parquet")
                    fingerprint = hashlib.sha256(f"{sha}|{table.sheet}".encode()).hexdigest()
                    project.datasets.append(
                        DatasetMeta(
                            id=dataset_id,
                            name=self._unique_name(project, name),
                            kind="file",
                            upload_id=upload_id,
                            sheet=table.sheet or None,
                            n_rows=table.frame.height,
                            n_cols=len(table.columns),
                            columns=table.columns,
                            issues=table.issues,
                            fingerprint=fingerprint,
                            created_at=stamp,
                            health=parse_health(table.frame),
                        )
                    )
                    upload.dataset_ids.append(dataset_id)
            project.uploads.append(upload)
            self.save(project)
        return upload

    def delete_upload(self, project_id: str, upload_id: str) -> Project:
        with self.lock(project_id):
            project = self.get(project_id)
            upload = next((u for u in project.uploads if u.id == upload_id), None)
            if upload is None:
                msg = "upload not found"
                raise NotFound(msg)
            removed = set(upload.dataset_ids)
            # Combined datasets built from a removed dataset are removed with it.
            changed = True
            while changed:
                changed = False
                for d in project.datasets:
                    if d.id not in removed and removed & set(d.sources):
                        removed.add(d.id)
                        changed = True
            project.datasets = [d for d in project.datasets if d.id not in removed]
            project.links = [
                link
                for link in project.links
                if not removed & {link.spec.get("left"), link.spec.get("right")}
            ]
            project.uploads = [u for u in project.uploads if u.id != upload_id]
            for dataset_id in removed:
                shutil.rmtree(self.dataset_dir(project_id, dataset_id), ignore_errors=True)
                self._forget(project_id, dataset_id)
            shutil.rmtree(self._dir(project_id) / "uploads" / upload_id, ignore_errors=True)
            return self.save(project)

    # ------------------------------------------------------------------ datasets
    def _forget(self, project_id: str, dataset_id: str) -> None:
        with self._guard:
            self._frames.pop((project_id, dataset_id), None)

    def frame(self, project_id: str, dataset_id: str) -> pl.DataFrame:
        key = (project_id, dataset_id)
        with self._guard:
            cached = self._frames.get(key)
            if cached is not None:
                self._frames.move_to_end(key)
                return cached
        path = self.dataset_dir(project_id, dataset_id) / "data.parquet"
        if not path.is_file():
            msg = "dataset not found"
            raise NotFound(msg)
        frame = pl.read_parquet(path)
        with self._guard:
            self._frames[key] = frame
            while len(self._frames) > self._frame_cache_size:
                self._frames.popitem(last=False)
        return frame

    def add_combined(
        self,
        project: Project,
        *,
        name: str,
        frame: pl.DataFrame,
        columns: list[ColumnInfo],
        issues: list[ParseIssue],
        link_id: str,
        sources: Iterable[str],
        fingerprint: str,
    ) -> DatasetMeta:
        dataset_id = new_id("d")
        folder = self.dataset_dir(project.id, dataset_id)
        folder.mkdir(parents=True)
        frame.write_parquet(folder / "data.parquet")
        meta = DatasetMeta(
            id=dataset_id,
            name=self._unique_name(project, name),
            kind="combined",
            n_rows=frame.height,
            n_cols=len(columns),
            columns=columns,
            issues=issues,
            fingerprint=fingerprint,
            created_at=now(),
            link_id=link_id,
            sources=list(sources),
            health=parse_health(frame),
        )
        project.datasets.append(meta)
        return meta

    def add_cleaned(
        self,
        project: Project,
        *,
        name: str,
        frame: pl.DataFrame,
        columns: list[ColumnInfo],
        issues: list[ParseIssue],
        source: str,
        recipe: list[dict[str, Any]],
        fingerprint: str,
    ) -> DatasetMeta:
        dataset_id = new_id("d")
        folder = self.dataset_dir(project.id, dataset_id)
        folder.mkdir(parents=True)
        frame.write_parquet(folder / "data.parquet")
        meta = DatasetMeta(
            id=dataset_id,
            name=self._unique_name(project, name),
            kind="cleaned",
            n_rows=frame.height,
            n_cols=len(columns),
            columns=columns,
            issues=issues,
            fingerprint=fingerprint,
            created_at=now(),
            sources=[source],
            health=parse_health(frame),
            recipe=recipe,
        )
        project.datasets.append(meta)
        return meta

    def remove_dataset(self, project: Project, dataset_id: str) -> None:
        project.datasets = [d for d in project.datasets if d.id != dataset_id]
        shutil.rmtree(self.dataset_dir(project.id, dataset_id), ignore_errors=True)
        self._forget(project.id, dataset_id)

    def set_role(
        self, project_id: str, dataset_id: str, column: str, role: Role | None
    ) -> DatasetMeta:
        """Override (or, with ``None``, restore) the inferred role of a column."""
        from edaforge.ingest.infer import infer_role

        with self.lock(project_id):
            project = self.get(project_id)
            meta = project.dataset(dataset_id)
            frame = self.frame(project_id, dataset_id)
            updated: list[ColumnInfo] = []
            found = False
            for info in meta.columns:
                if info.name != column:
                    updated.append(info)
                    continue
                found = True
                if role is None:
                    inferred, reason = infer_role(info.name, frame[info.name], info.dtype)
                    update = {"role": inferred, "role_reason": reason, "role_source": "inferred"}
                else:
                    update = {"role": role, "role_reason": "set by you", "role_source": "user"}
                updated.append(info.model_copy(update=update))
            if not found:
                msg = "column not found"
                raise NotFound(msg)
            meta.columns = updated
            (self.dataset_dir(project_id, dataset_id) / "profile.json").unlink(missing_ok=True)
            self.save(project)
            return meta

    # ------------------------------------------------------------------ cached JSON artifacts
    def read_json(self, path: Path) -> Any | None:
        if not path.is_file():
            return None
        return json.loads(path.read_text("utf-8"))

    def write_json(self, path: Path, value: Any) -> None:
        _atomic_write(path, json.dumps(value, ensure_ascii=False, default=str))
