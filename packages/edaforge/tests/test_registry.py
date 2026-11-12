"""Plugin discovery is opt-in and validated (section 12.2, section 20)."""

from __future__ import annotations

import pytest

from edaforge.errors import PluginError
from edaforge.plugins.registry import AnalyzerRegistry, discover_plugins


def test_installed_plugins_are_listed_without_loading() -> None:
    plugins = discover_plugins()
    assert any(p.distribution == "edaforge-plugin-example" for p in plugins)


def test_plugins_load_only_when_enabled() -> None:
    registry = AnalyzerRegistry()
    assert registry.load_plugins([]) == []
    assert len(registry) == 0
    assert registry.load_plugins(["edaforge_plugin_example"]) == ["example.mean_shift"]
    ref = registry.refs()[0]
    assert (ref.name, ref.distribution) == ("example.mean_shift", "edaforge-plugin-example")


def test_enabling_a_missing_plugin_fails_loudly() -> None:
    with pytest.raises(PluginError, match="not installed"):
        AnalyzerRegistry().load_plugins(["edaforge-plugin-does-not-exist"])


def test_invalid_analyzers_are_rejected() -> None:
    class NoProtocol:
        pass

    registry = AnalyzerRegistry()
    with pytest.raises(PluginError, match="protocol"):
        registry.register(NoProtocol())
    from edaforge_plugin_example import MeanShiftAnalyzer

    registry.register(MeanShiftAnalyzer())
    with pytest.raises(PluginError, match="already registered"):
        registry.register(MeanShiftAnalyzer())

    class BadName(MeanShiftAnalyzer):
        name = "NotDotted"

    with pytest.raises(PluginError, match="dotted lowercase"):
        AnalyzerRegistry().register(BadName())
