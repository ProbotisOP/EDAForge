"""Scan installed Python distributions.

Two scopes:

* ``closure``: the requirement closure of root distributions (for example the core ``edaforge``
  package), following ``Requires-Dist`` with environment markers and requested extras;
* ``installed``: every distribution in the environment (development tools included).

License information is resolved in this order, and the source is reported:
``License-Expression`` (PEP 639), a short ``License`` field, Trove classifiers, license files
in the ``.dist-info`` directory, and finally the start of a long ``License`` field. A reviewed
exception in the policy file overrides all of them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from packaging.markers import UndefinedEnvironmentName
from packaging.requirements import InvalidRequirement, Requirement

from edaforge_devtools.license_gate.classify import (
    Decision,
    Verdict,
    classifier_to_spdx,
    classify_expression,
    fingerprint_text,
    parse_spdx,
    synonym_to_spdx,
)
from edaforge_devtools.license_gate.policy import Policy, normalize_name

__all__ = ["PackageVerdict", "check_distributions", "closure", "installed"]

_SHORT_LICENSE = 120


@dataclass(frozen=True)
class PackageVerdict:
    ecosystem: str
    package: str
    version: str
    verdict: Verdict
    source: str

    @property
    def failed(self) -> bool:
        return self.verdict.decision in {Decision.UNKNOWN, Decision.DENIED}


def _index(paths: Sequence[Path] | None) -> dict[str, metadata.Distribution]:
    found = (
        metadata.distributions(path=[str(p) for p in paths]) if paths else metadata.distributions()
    )
    index: dict[str, metadata.Distribution] = {}
    for dist in found:
        name = dist.metadata.get("Name")
        if name:
            index.setdefault(normalize_name(name), dist)
    return index


def closure(
    roots: Iterable[str], *, paths: Sequence[Path] | None = None
) -> tuple[list[metadata.Distribution], list[str]]:
    """Distributions required by ``roots`` (``name`` or ``name[extra1,extra2]``)."""
    index = _index(paths)
    seen: dict[str, set[str]] = {}
    missing: list[str] = []
    stack: list[tuple[str, frozenset[str]]] = []
    for root in roots:
        requirement = Requirement(root)
        stack.append((normalize_name(requirement.name), frozenset(requirement.extras)))
    while stack:
        name, extras = stack.pop()
        if name in seen and extras <= seen[name]:
            continue
        seen.setdefault(name, set()).update(extras)
        dist = index.get(name)
        if dist is None:
            missing.append(name)
            continue
        for raw in dist.requires or []:
            try:
                requirement = Requirement(raw)
            except InvalidRequirement:
                missing.append(f"{name}: unparsable requirement {raw!r}")
                continue
            if requirement.marker is not None:
                try:
                    active = any(
                        requirement.marker.evaluate({"extra": extra})
                        for extra in (seen[name] or {""})
                    )
                except UndefinedEnvironmentName:
                    active = False
                if not active:
                    continue
            stack.append((normalize_name(requirement.name), frozenset(requirement.extras)))
    dists = [index[n] for n in sorted(seen) if n in index]
    return dists, sorted(set(missing))


def installed(*, paths: Sequence[Path] | None = None) -> list[metadata.Distribution]:
    index = _index(paths)
    return [index[n] for n in sorted(index)]


def _license_files(dist: metadata.Distribution) -> list[str]:
    texts: list[str] = []
    for file in dist.files or []:
        name = file.name.upper()
        if name.startswith(("LICENSE", "LICENCE", "COPYING")):
            try:
                texts.append(file.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
    return texts


def _resolve(dist: metadata.Distribution, policy: Policy) -> tuple[Verdict, str]:
    meta = dist.metadata
    name = meta.get("Name") or "?"
    exception = policy.exception_for("python", name)
    if exception is not None:
        verdict = classify_expression(exception.license, policy)
        return verdict, f"policy exception: {exception.reason}"
    expression = meta.get("License-Expression")
    if expression:
        return classify_expression(expression, policy), "License-Expression"
    license_field = (meta.get("License") or "").strip()
    if license_field and len(license_field) <= _SHORT_LICENSE and "\n" not in license_field:
        spdx = synonym_to_spdx(license_field)
        if spdx is None:
            try:
                parse_spdx(license_field)
                spdx = license_field
            except ValueError:
                spdx = None
        if spdx is not None:
            return classify_expression(spdx, policy), "License"
    classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    mapped = sorted({s for c in classifiers if (s := classifier_to_spdx(c)) is not None})
    if mapped:
        # Classifiers do not say AND or OR; the gate assumes AND (the conservative reading).
        return classify_expression(" AND ".join(mapped), policy), "Trove classifiers"
    for text in _license_files(dist):
        if (spdx := fingerprint_text(text)) is not None:
            return classify_expression(spdx, policy), "license file fingerprint"
    if license_field and (spdx := fingerprint_text(license_field)) is not None:
        return classify_expression(spdx, policy), "License text fingerprint"
    return (
        Verdict(Decision.UNKNOWN, license_field[:40] or "<none>", "", "no license metadata found"),
        "none",
    )


def check_distributions(
    dists: Iterable[metadata.Distribution], policy: Policy
) -> list[PackageVerdict]:
    results: list[PackageVerdict] = []
    for dist in dists:
        verdict, source = _resolve(dist, policy)
        results.append(
            PackageVerdict(
                ecosystem="python",
                package=dist.metadata.get("Name") or "?",
                version=dist.version,
                verdict=verdict,
                source=source,
            )
        )
    return results
