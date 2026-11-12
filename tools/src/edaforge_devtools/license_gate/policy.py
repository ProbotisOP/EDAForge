"""License policy file (``license-policy.toml`` at the repository root)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from edaforge_devtools._json import as_dict, as_list

__all__ = ["Exception_", "Policy", "load_policy", "normalize_name"]


def normalize_name(name: str) -> str:
    """PEP 503 normalization for Python distributions (npm names are left lowercase)."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class Exception_:  # noqa: N801 - "Exception" would shadow the builtin
    """A reviewed override for one package whose metadata is missing or wrong."""

    package: str
    license: str
    reason: str
    ecosystem: str = "python"


def _exceptions() -> dict[tuple[str, str], Exception_]:
    return {}


@dataclass(frozen=True)
class Policy:
    allowed: frozenset[str]
    allowed_unmodified: frozenset[str]
    denied_prefixes: tuple[str, ...]
    denied_text: tuple[str, ...]
    exceptions: dict[tuple[str, str], Exception_] = field(default_factory=_exceptions)

    def exception_for(self, ecosystem: str, package: str) -> Exception_ | None:
        key = (ecosystem, normalize_name(package) if ecosystem == "python" else package.lower())
        return self.exceptions.get(key)


def _str_list(table: dict[str, object], key: str) -> list[str]:
    values = as_list(table.get(key, []))
    if values is None or not all(isinstance(v, str) for v in values):
        msg = f"policy key {key!r} must be a list of strings"
        raise ValueError(msg)
    return [str(v) for v in values]


def load_policy(path: Path) -> Policy:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    table = as_dict(raw.get("policy"))
    if table is None:
        msg = f"{path}: missing [policy] table"
        raise ValueError(msg)
    exceptions: dict[tuple[str, str], Exception_] = {}
    for item in as_list(raw.get("exception", [])) or []:
        entry = as_dict(item)
        if entry is None:
            msg = f"{path}: every [[exception]] must be a table"
            raise ValueError(msg)
        package, license_, reason = entry.get("package"), entry.get("license"), entry.get("reason")
        ecosystem = entry.get("ecosystem", "python")
        if not (
            isinstance(package, str)
            and isinstance(license_, str)
            and isinstance(reason, str)
            and isinstance(ecosystem, str)
            and reason.strip()
        ):
            msg = f"{path}: exceptions need package, license and a non-empty reason"
            raise ValueError(msg)
        key_name = normalize_name(package) if ecosystem == "python" else package.lower()
        exceptions[(ecosystem, key_name)] = Exception_(package, license_, reason, ecosystem)
    return Policy(
        allowed=frozenset(_str_list(table, "allowed")),
        allowed_unmodified=frozenset(_str_list(table, "allowed_unmodified")),
        denied_prefixes=tuple(_str_list(table, "denied_prefixes")),
        denied_text=tuple(t.lower() for t in _str_list(table, "denied_text")),
        exceptions=exceptions,
    )
