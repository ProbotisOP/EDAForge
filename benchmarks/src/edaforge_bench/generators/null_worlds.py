"""Null worlds: data with no planted pattern (section 16.1).

A null world mixes column types and marginal shapes (skewed, heavy-tailed, discrete, bimodal)
so that a detector that is only calibrated for Gaussian data fails visibly. Rows are i.i.d. and
columns independent; the optional environment column is assigned at random, so no column differs
between environments in distribution.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import polars as pl
from numpy.typing import NDArray

__all__ = ["NULL_VARIANTS", "NullWorld", "NullWorldSpec", "null_world", "permuted_copy"]

FloatArray = NDArray[np.float64]
_Sampler = Callable[[np.random.Generator, int], FloatArray]


def _normal(rng: np.random.Generator, n: int) -> FloatArray:
    return rng.normal(size=n)


def _lognormal(rng: np.random.Generator, n: int) -> FloatArray:
    return rng.lognormal(mean=0.0, sigma=1.0, size=n)


def _student_t3(rng: np.random.Generator, n: int) -> FloatArray:
    return rng.standard_t(df=3, size=n)


def _exponential(rng: np.random.Generator, n: int) -> FloatArray:
    return rng.exponential(scale=2.0, size=n)


def _uniform(rng: np.random.Generator, n: int) -> FloatArray:
    return rng.uniform(-1.0, 1.0, size=n)


def _poisson(rng: np.random.Generator, n: int) -> FloatArray:
    return rng.poisson(lam=3.0, size=n).astype(np.float64)


def _bimodal(rng: np.random.Generator, n: int) -> FloatArray:
    mode = rng.random(n) < 0.5
    return np.where(mode, rng.normal(-2.0, 0.7, n), rng.normal(2.0, 0.7, n))


SAMPLERS: dict[str, _Sampler] = {
    "normal": _normal,
    "lognormal": _lognormal,
    "student_t3": _student_t3,
    "exponential": _exponential,
    "uniform": _uniform,
    "poisson": _poisson,
    "bimodal": _bimodal,
}


@dataclass(frozen=True)
class NullWorldSpec:
    n: int = 2400
    numeric: tuple[str, ...] = ("normal", "lognormal", "student_t3", "poisson")
    categorical_levels: tuple[int, ...] = (3,)
    n_environments: int = 2
    environment_column: str = "__source__"
    missing_rate: float = 0.0  # MCAR missingness on numeric columns


@dataclass(frozen=True)
class NullWorld:
    frame: pl.DataFrame
    spec: NullWorldSpec
    truth: dict[str, list[str]] = field(default_factory=lambda: {"patterns": []})


def null_world(spec: NullWorldSpec, seed: int) -> NullWorld:
    rng = np.random.default_rng(seed)
    columns: dict[str, object] = {}
    for i, kind in enumerate(spec.numeric):
        values = SAMPLERS[kind](rng, spec.n)
        if spec.missing_rate > 0.0:
            mask = rng.random(spec.n) < spec.missing_rate
            columns[f"num{i}_{kind}"] = pl.Series(values).set(pl.Series(mask), None)
        else:
            columns[f"num{i}_{kind}"] = values
    for j, levels in enumerate(spec.categorical_levels):
        probs = rng.dirichlet(np.ones(levels) * 2.0)
        codes = rng.choice(levels, size=spec.n, p=probs)
        columns[f"cat{j}"] = [f"L{c}" for c in codes.tolist()]
    if spec.n_environments >= 2:
        envs = rng.integers(0, spec.n_environments, size=spec.n)
        columns[spec.environment_column] = [f"E{e}" for e in envs.tolist()]
    return NullWorld(frame=pl.DataFrame(columns), spec=spec)


def permuted_copy(
    frame: pl.DataFrame,
    rng: np.random.Generator,
    *,
    within: str | None = None,
    keep: tuple[str, ...] = (),
) -> pl.DataFrame:
    """Permute every column independently (optionally within strata of ``within``).

    This destroys every dependence between columns while keeping each marginal distribution:
    the cross-sectional Nullverse construction of section 8.5.
    """
    out: dict[str, pl.Series] = {}
    if within is None:
        for name in frame.columns:
            series = frame[name]
            out[name] = series if name in keep else series.gather(rng.permutation(frame.height))
        return pl.DataFrame(out)
    groups = frame[within].to_numpy()
    order = np.arange(frame.height)
    for name in frame.columns:
        series = frame[name]
        if name in keep or name == within:
            out[name] = series
            continue
        index = order.copy()
        for level in np.unique(groups):
            positions = np.nonzero(groups == level)[0]
            index[positions] = rng.permutation(positions)
        out[name] = series.gather(index)
    return pl.DataFrame(out)


NULL_VARIANTS: dict[str, NullWorldSpec] = {
    "gaussian": NullWorldSpec(numeric=("normal", "normal", "normal", "normal")),
    "skewed": NullWorldSpec(numeric=("lognormal", "exponential", "lognormal", "exponential")),
    "heavy_tails": NullWorldSpec(numeric=("student_t3", "student_t3", "student_t3", "normal")),
    "discrete": NullWorldSpec(numeric=("poisson", "poisson", "uniform", "normal")),
    "bimodal": NullWorldSpec(numeric=("bimodal", "bimodal", "normal", "uniform")),
    "mixed": NullWorldSpec(),
    "many_environments": NullWorldSpec(n_environments=4),
    "unbalanced_small": NullWorldSpec(n=2100, numeric=("normal", "lognormal", "student_t3")),
    "missing_mcar": NullWorldSpec(missing_rate=0.1),
    "wide": NullWorldSpec(
        numeric=("normal", "lognormal", "student_t3", "poisson", "uniform", "bimodal", "normal")
    ),
}
