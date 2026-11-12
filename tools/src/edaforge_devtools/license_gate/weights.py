"""Model-weight manifest (section 13.3: the license policy applies equally to model weights).

``model-weights.toml`` lists every checkpoint the project may download::

    [[model]]
    name = "example-checkpoint"
    version = "1.0"
    license = "Apache-2.0"
    scope = "core"  # or "plugin:<distribution>"
    source = "where it is downloaded from"

Checkpoints in the ``core`` scope must pass the policy like any dependency. Plugin-scoped
checkpoints may carry other licenses (for example non-commercial weights), but must name their
plugin and must not be referenced by the core.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from edaforge_devtools._json import as_dict, as_list, as_str
from edaforge_devtools.license_gate.classify import Decision, Verdict, classify_expression
from edaforge_devtools.license_gate.policy import Policy
from edaforge_devtools.license_gate.python_env import PackageVerdict

__all__ = ["check_weights_manifest"]


def check_weights_manifest(path: Path, policy: Policy) -> list[PackageVerdict]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    models = as_list(raw.get("model", []))
    if models is None:
        msg = f"{path}: [[model]] must be an array of tables"
        raise ValueError(msg)
    results: list[PackageVerdict] = []
    for raw_item in models:
        item = as_dict(raw_item)
        if item is None:
            msg = f"{path}: every [[model]] must be a table"
            raise ValueError(msg)
        name = as_str(item.get("name"), "?")
        version = as_str(item.get("version"), "?")
        license_ = as_str(item.get("license")).strip()
        scope = as_str(item.get("scope"))
        if not license_:
            verdict = Verdict(Decision.UNKNOWN, "<none>", "", "checkpoint has no license")
        elif scope == "core":
            verdict = classify_expression(license_, policy)
        elif scope.startswith("plugin:") and len(scope) > len("plugin:"):
            verdict = Verdict(
                Decision.ALLOWED,
                license_,
                license_,
                f"plugin-scoped checkpoint ({scope}); never loaded by the core",
            )
        else:
            verdict = Verdict(
                Decision.UNKNOWN, license_, "", "scope must be 'core' or 'plugin:<distribution>'"
            )
        results.append(PackageVerdict("model-weights", name, version, verdict, f"scope={scope}"))
    return results
