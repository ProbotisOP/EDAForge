"""Findings store and content-addressed artifact store."""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from edaforge.canonical import canonical_json, sha256_hex
from edaforge.models import GRADE_ORDER, Finding, Grade, PatternClass, Rung

__all__ = ["ArtifactStore", "FindingsStore"]


class FindingsStore:
    """An ordered, read-only collection of findings with the queries the UI and API need."""

    def __init__(self, findings: Iterable[Finding]) -> None:
        self._findings = tuple(findings)
        self._by_id = {f.id: f for f in self._findings}
        if len(self._by_id) != len(self._findings):
            msg = "duplicate finding IDs"
            raise ValueError(msg)

    def __len__(self) -> int:
        return len(self._findings)

    def __iter__(self) -> Iterator[Finding]:
        return iter(self._findings)

    def __getitem__(self, finding_id: str) -> Finding:
        return self._by_id[finding_id]

    def top(self, k: int = 10) -> list[Finding]:
        """Highest interestingness first; ties broken by grade, then by ID (never by p-value)."""
        ranked = sorted(
            self._findings,
            key=lambda f: (-f.interestingness.value, GRADE_ORDER.index(f.evidence.grade), f.id),
        )
        return ranked[:k]

    def filter(
        self,
        *,
        pattern_class: PatternClass | None = None,
        grade: Grade | None = None,
        rung: Rung | None = None,
        variable: str | None = None,
    ) -> list[Finding]:
        out: list[Finding] = []
        for f in self._findings:
            if pattern_class is not None and f.pattern_class != pattern_class:
                continue
            if grade is not None and f.evidence.grade != grade:
                continue
            if rung is not None and f.evidence.rung != rung:
                continue
            if variable is not None and all(v.column != variable for v in f.variables):
                continue
            out.append(f)
        return out

    def to_json(self) -> str:
        return canonical_json([f.model_dump(mode="json") for f in self._findings], indent=2)


class ArtifactStore:
    """Immutable blobs addressed by the SHA-256 of their bytes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest[2:]

    def put(self, payload: bytes) -> str:
        digest = sha256_hex(payload)
        path = self._path(digest)
        if path.exists():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                Path(tmp).unlink()
            raise
        return digest

    def get(self, digest: str) -> bytes:
        payload = self._path(digest).read_bytes()
        if sha256_hex(payload) != digest:
            msg = f"artifact {digest} is corrupted"
            raise ValueError(msg)
        return payload
