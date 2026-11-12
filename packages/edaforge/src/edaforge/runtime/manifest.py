"""Run manifests: seeds, library versions and data hashes (Law 11).

The run ID is derived from content only (inputs, configuration, seed, analyzer versions and
library versions), so a rerun with unchanged inputs gets the same ID and the same cache entries.
"""

from __future__ import annotations

import platform
import re
import sys
from collections.abc import Iterable, Sequence
from importlib import metadata

from edaforge.canonical import content_hash, short_hash
from edaforge.models import AnalyzerRef, DataInput, RunManifest, SplitRecord
from edaforge.runtime.clock import Clock, SystemClock

__all__ = [
    "build_manifest",
    "dependency_versions",
    "edaforge_version",
    "manifest_hash",
    "run_identity",
]

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXTRA_MARKER = re.compile(r";.*\bextra\s*==")


def edaforge_version() -> str:
    try:
        return metadata.version("edaforge")
    except metadata.PackageNotFoundError:  # running from a source tree without installation
        return "0+unknown"


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_versions(roots: Iterable[str]) -> dict[str, str]:
    """Installed versions of ``roots`` and their (non-extra) requirement closure."""
    seen: dict[str, str] = {}
    stack = [_normalize(r) for r in roots]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[name] = dist.version
        for requirement in dist.requires or []:
            if _EXTRA_MARKER.search(requirement):
                continue
            match = _NAME.match(requirement)
            if match:
                stack.append(_normalize(match.group(1)))
    return dict(sorted(seen.items()))


def run_identity(
    *,
    seed: int,
    config_hash: str,
    inputs: Sequence[DataInput],
    analyzers: Sequence[AnalyzerRef],
    extra_roots: Iterable[str] = (),
) -> tuple[str, dict[str, str]]:
    """The content-derived run ID and the library versions it covers."""
    roots = ["edaforge", *[a.distribution for a in analyzers if a.distribution], *extra_roots]
    libraries = dependency_versions(roots)
    identity = {
        "edaforge_version": edaforge_version(),
        "python": platform.python_version(),
        "platform": f"{sys.platform}-{platform.machine()}",
        "seed": seed,
        "config_hash": config_hash,
        "inputs": [i.model_dump(mode="json", exclude={"path"}) for i in inputs],
        "analyzers": [a.model_dump(mode="json") for a in analyzers],
        "libraries": libraries,
    }
    return "R-" + short_hash(content_hash(identity)), libraries


def build_manifest(
    *,
    seed: int,
    config_hash: str,
    inputs: Sequence[DataInput],
    analyzers: Sequence[AnalyzerRef],
    split: SplitRecord | None = None,
    extra_roots: Iterable[str] = (),
    clock: Clock | None = None,
) -> RunManifest:
    run_id, libraries = run_identity(
        seed=seed,
        config_hash=config_hash,
        inputs=inputs,
        analyzers=analyzers,
        extra_roots=extra_roots,
    )
    return RunManifest(
        run_id=run_id,
        edaforge_version=edaforge_version(),
        python_version=platform.python_version(),
        platform=f"{sys.platform}-{platform.machine()}",
        seed=seed,
        config_hash=config_hash,
        inputs=list(inputs),
        libraries=libraries,
        analyzers=list(analyzers),
        split=split,
        created_at=(clock or SystemClock()).now(),
    )


def manifest_hash(manifest: RunManifest) -> str:
    """Hash of everything in the manifest except the wall-clock timestamp."""
    return content_hash(manifest.model_dump(mode="json", exclude={"created_at"}))
