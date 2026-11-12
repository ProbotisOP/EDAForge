"""Scan npm lockfiles (``package-lock.json`` v2/v3)."""

from __future__ import annotations

import json
from pathlib import Path

from edaforge_devtools._json import as_dict, as_str
from edaforge_devtools.license_gate.classify import Decision, Verdict, classify_expression
from edaforge_devtools.license_gate.policy import Policy
from edaforge_devtools.license_gate.python_env import PackageVerdict

__all__ = ["check_npm_lockfile"]


def check_npm_lockfile(path: Path, policy: Policy) -> list[PackageVerdict]:
    data = as_dict(json.loads(path.read_text(encoding="utf-8")))
    packages = as_dict(data.get("packages")) if data is not None else None
    if packages is None:
        msg = f"{path}: not an npm lockfile v2/v3 (no 'packages' table)"
        raise ValueError(msg)
    results: list[PackageVerdict] = []
    for key in sorted(packages):
        entry = as_dict(packages[key])
        if not key or entry is None:  # "" is the root project itself
            continue
        name = key.rsplit("node_modules/", 1)[-1]
        version = as_str(entry.get("version"), "?")
        exception = policy.exception_for("npm", name)
        raw_license = as_str(entry.get("license")).strip()
        if exception is not None:
            verdict = classify_expression(exception.license, policy)
            source = f"policy exception: {exception.reason}"
        elif raw_license:
            verdict = classify_expression(raw_license, policy)
            source = "package-lock license"
        else:
            verdict = Verdict(Decision.UNKNOWN, "<none>", "", "no license in the lockfile")
            source = "none"
        results.append(PackageVerdict("npm", name, version, verdict, source))
    return results
