"""Statistical CI gates (section 16.3).

Phase 0 runs gate-1-style null control and a recall check on the example analyzer only. The full
gates 1-5 over every analyzer are Phase 3 acceptance criteria.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import edaforge as gh
from edaforge.config import EDAForgeConfig
from edaforge.runtime.clock import FixedClock
from edaforge_bench.generators import (
    NULL_VARIANTS,
    MultiEnvSpec,
    multi_environment,
    null_world,
)

__all__ = ["GateResult", "null_control_mean_shift", "recall_mean_shift"]

_PLUGIN = "edaforge-plugin-example"


@dataclass(frozen=True)
class GateResult:
    name: str
    metric: str
    value: float
    threshold: float
    passed: bool
    details: dict[str, float] = field(default_factory=dict[str, float])

    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"[{verdict}] {self.name}: {self.metric} = {self.value:.4f} "
            f"(threshold {self.threshold})"
        )


def _config(seed: int) -> EDAForgeConfig:
    return EDAForgeConfig.model_validate(
        {"budget": "quick", "plugins": [_PLUGIN], "compute": {"seed": seed}}
    )


def null_control_mean_shift(n_datasets: int = 200, seed: int = 20261110) -> GateResult:
    """Gate 1 criterion for the example analyzer: mean Confirmed findings per null dataset <= 0.10.

    Datasets cycle through the ten null-world variants (``NULL_VARIANTS``).
    """
    variants = sorted(NULL_VARIANTS)
    confirmed_total = 0
    per_variant: dict[str, float] = dict.fromkeys(variants, 0.0)
    for i in range(n_datasets):
        variant = variants[i % len(variants)]
        world = null_world(NULL_VARIANTS[variant], seed=seed + i)
        run = gh.discover(world.frame, config=_config(seed + i), clock=FixedClock())
        confirmed = sum(1 for f in run.findings if f.evidence.confirmation.status == "confirmed")
        confirmed_total += confirmed
        per_variant[variant] += confirmed
    mean = confirmed_total / n_datasets
    return GateResult(
        name="null control (example.mean_shift)",
        metric="mean Confirmed findings per null dataset",
        value=mean,
        threshold=0.10,
        passed=mean <= 0.10,
        details={"datasets": float(n_datasets), **per_variant},
    )


_BANDS: tuple[tuple[str, float, float], ...] = (
    ("small [0.1, 0.2)", 0.1, 0.2),
    ("between [0.2, 0.5)", 0.2, 0.5),
    ("medium+ [0.5, inf)", 0.5, float("inf")),
)


def recall_mean_shift(
    n_datasets: int = 50, seed: int = 20261111, shift_size: float = 0.5
) -> GateResult:
    """Recall of planted mean shifts at Confirmed, by standardized effect size, at n = 5,000.

    The gate applies section 16.3 gate 3 to "medium planted effects", read as a standardized
    shift of at least 0.5 (Cohen's conventional "medium"). Smaller shifts arise in descendants of
    the shifted node; their recall is reported in ``details`` and is expected to be lower, because
    the sealed split (30%) has limited power for them.
    """
    found = dict.fromkeys([b[0] for b in _BANDS], 0)
    planted = dict.fromkeys([b[0] for b in _BANDS], 0)
    false_confirmed = 0
    confirmed_all = 0
    for i in range(n_datasets):
        data = multi_environment(
            MultiEnvSpec(n_per_env=2500, shift_size=shift_size, shift_nodes=(0,)), seed=seed + i
        )
        run = gh.discover(data.frame, config=_config(seed + i), clock=FixedClock())
        confirmed = {
            f.variables[0].column
            for f in run.findings
            if f.evidence.confirmation.status == "confirmed"
        }
        confirmed_all += len(confirmed)
        for name, d in data.mean_shift.items():
            size = abs(d)
            for band, low, high in _BANDS:
                if low <= size < high:
                    planted[band] += 1
                    found[band] += int(name in confirmed)
            if size == 0.0 and name in confirmed:
                false_confirmed += 1
    medium = "medium+ [0.5, inf)"
    recall = found[medium] / planted[medium] if planted[medium] else 1.0
    details: dict[str, float] = {
        "false_confirmed_unshifted": float(false_confirmed),
        "fdr_among_confirmed": false_confirmed / confirmed_all if confirmed_all else 0.0,
    }
    for band, _, _ in _BANDS:
        details[f"planted {band}"] = float(planted[band])
        details[f"recall {band}"] = found[band] / planted[band] if planted[band] else float("nan")
    return GateResult(
        name="recall (example.mean_shift, medium shifts, n = 5,000)",
        metric="recall at Confirmed for standardized shifts >= 0.5",
        value=recall,
        threshold=0.80,
        passed=recall >= 0.80,
        details=details,
    )
