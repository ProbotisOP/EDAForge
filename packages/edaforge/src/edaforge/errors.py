"""Exception hierarchy for the engine."""

from __future__ import annotations

__all__ = [
    "BlindAnalysisError",
    "ConfigError",
    "ContractViolation",
    "EDAForgeError",
    "LedgerError",
    "PluginError",
    "ReproductionMismatch",
]


class EDAForgeError(Exception):
    """Base class for every error raised by the engine."""


class ConfigError(EDAForgeError):
    """Invalid or inconsistent configuration."""


class ContractViolation(EDAForgeError):
    """An analyzer or component broke a Rigor Kernel contract (e.g. an unledgered p-value)."""


class LedgerError(EDAForgeError):
    """Misuse of the Hypothesis Ledger (unknown hypothesis, double testing, ...)."""


class BlindAnalysisError(EDAForgeError):
    """Sealed confirmation data was requested in a way that the blind-analysis rules forbid."""


class PluginError(EDAForgeError):
    """A plugin could not be discovered, loaded or validated."""


class ReproductionMismatch(EDAForgeError):
    """Re-execution from provenance did not reproduce the recorded numbers."""
