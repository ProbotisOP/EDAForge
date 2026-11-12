"""Analyzer registry and plugin discovery.

Plugins register through the ``edaforge.analyzers`` entry-point group. The core never imports a
plugin module by name. A plugin is loaded only when its distribution is listed in the run
configuration's ``plugins`` list (section 20): enabling a plugin is an explicit act, taken after
its license has been reviewed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib import metadata

from edaforge.errors import PluginError
from edaforge.models import AnalyzerRef, PatternClass
from edaforge.plugins.sdk import Analyzer

__all__ = ["ENTRY_POINT_GROUP", "AnalyzerRegistry", "PluginInfo", "discover_plugins"]

ENTRY_POINT_GROUP = "edaforge.analyzers"
_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class PluginInfo:
    entry_point: str
    value: str
    distribution: str | None
    version: str | None


def discover_plugins(group: str = ENTRY_POINT_GROUP) -> list[PluginInfo]:
    """List installed analyzer entry points without importing them."""
    found: list[PluginInfo] = []
    for ep in metadata.entry_points(group=group):
        dist = ep.dist
        found.append(
            PluginInfo(
                entry_point=ep.name,
                value=ep.value,
                distribution=None if dist is None else dist.name,
                version=None if dist is None else dist.version,
            )
        )
    return sorted(found, key=lambda p: (p.distribution or "", p.entry_point))


def _validate(analyzer: object, origin: str) -> Analyzer:
    if not isinstance(analyzer, Analyzer):
        msg = f"{origin} does not implement the Analyzer protocol"
        raise PluginError(msg)
    name: object = getattr(analyzer, "name", None)
    version: object = getattr(analyzer, "version", None)
    pattern_class: object = getattr(analyzer, "pattern_class", None)
    if not isinstance(name, str) or not _NAME.match(name):
        msg = f"{origin}: analyzer name must be dotted lowercase, like 'reveal.subgroups.emm'"
        raise PluginError(msg)
    if not isinstance(version, str) or not version:
        msg = f"{origin}: analyzer version must be a non-empty string"
        raise PluginError(msg)
    if not isinstance(pattern_class, PatternClass):
        msg = f"{origin}: pattern_class must be a PatternClass"
        raise PluginError(msg)
    return analyzer


@dataclass(frozen=True)
class _Entry:
    analyzer: Analyzer
    distribution: str | None


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def register(self, analyzer: object, *, distribution: str | None = None) -> str:
        checked = _validate(analyzer, type(analyzer).__name__)
        if checked.name in self._entries:
            msg = f"analyzer {checked.name!r} is already registered"
            raise PluginError(msg)
        self._entries[checked.name] = _Entry(checked, distribution)
        return checked.name

    def get(self, name: str) -> Analyzer:
        try:
            return self._entries[name].analyzer
        except KeyError:
            msg = f"no analyzer named {name!r}"
            raise PluginError(msg) from None

    def analyzers(self) -> list[Analyzer]:
        return [self._entries[k].analyzer for k in sorted(self._entries)]

    def refs(self) -> list[AnalyzerRef]:
        return [
            AnalyzerRef(name=k, version=e.analyzer.version, distribution=e.distribution)
            for k, e in sorted(self._entries.items())
        ]

    def __len__(self) -> int:
        return len(self._entries)

    def load_plugins(
        self, enabled_distributions: Iterable[str], *, group: str = ENTRY_POINT_GROUP
    ) -> list[str]:
        """Load analyzers from the enabled distributions; returns the analyzer names loaded."""
        enabled = {_normalize(d) for d in enabled_distributions}
        if not enabled:
            return []
        loaded: list[str] = []
        seen: set[str] = set()
        for ep in sorted(metadata.entry_points(group=group), key=lambda e: (e.value, e.name)):
            dist = ep.dist
            dist_name = None if dist is None else _normalize(dist.name)
            if dist_name is None or dist_name not in enabled:
                continue
            seen.add(dist_name)
            try:
                target = ep.load()
            except Exception as exc:
                msg = f"plugin entry point {ep.name!r} from {dist_name} failed to import: {exc}"
                raise PluginError(msg) from exc
            instance = target() if isinstance(target, type) else target
            loaded.append(self.register(instance, distribution=dist_name))
        missing = sorted(enabled - seen)
        if missing:
            msg = f"enabled plugins are not installed or expose no analyzers: {', '.join(missing)}"
            raise PluginError(msg)
        return loaded


def registry_for(analyzers: Sequence[object] = (), plugins: Iterable[str] = ()) -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    for analyzer in analyzers:
        registry.register(analyzer)
    registry.load_plugins(plugins)
    return registry
