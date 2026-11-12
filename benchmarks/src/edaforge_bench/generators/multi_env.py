"""Multi-environment data with planted mechanism shifts (section 16.1).

A linear Gaussian SCM ``X = B X + c_e + eps`` is shared by all environments; in each environment a
chosen set of nodes gets an intercept shift (a mechanism change). Because the model is linear, the
ground truth is exact: environment means are ``(I - B)^-1 c_e``, so the columns whose marginal mean
moves (the shifted nodes and their descendants, unless effects cancel) are known, along with the
standardized size of each shift.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
from numpy.typing import NDArray

from edaforge_bench.generators.scm import random_dag

__all__ = ["MultiEnvData", "MultiEnvSpec", "multi_environment"]

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class MultiEnvSpec:
    n_per_env: int = 1500
    n_nodes: int = 6
    n_environments: int = 2
    expected_degree: float = 1.5
    shift_nodes: tuple[int, ...] = (0,)  # mechanism shifts (in environments 1..k-1)
    shift_size: float = 0.3  # intercept shift in noise-SD units
    environment_column: str = "__source__"


@dataclass(frozen=True)
class MultiEnvData:
    frame: pl.DataFrame
    adjacency: NDArray[np.int64]  # adjacency[i, j] = 1 means i -> j
    weights: FloatArray
    shifted_mechanisms: tuple[str, ...]
    mean_shift: dict[str, float]  # standardized marginal mean shift, env E1 vs E0
    columns: tuple[str, ...]


def multi_environment(spec: MultiEnvSpec, seed: int) -> MultiEnvData:
    rng = np.random.default_rng(seed)
    adjacency = random_dag(spec.n_nodes, spec.expected_degree, rng)
    signs = rng.choice(np.array([-1.0, 1.0]), size=adjacency.shape)
    weights = adjacency * signs * rng.uniform(0.5, 1.5, size=adjacency.shape)
    # Structural equations in matrix form: x = W^T x + c + eps, i.e. x = (I - W^T)^-1 (c + eps).
    inverse = np.linalg.inv(np.eye(spec.n_nodes) - weights.T)
    columns = tuple(f"x{i}" for i in range(spec.n_nodes))
    frames: list[pl.DataFrame] = []
    intercepts: list[FloatArray] = []
    for e in range(spec.n_environments):
        c = np.zeros(spec.n_nodes)
        if e > 0:
            c[list(spec.shift_nodes)] = spec.shift_size
        intercepts.append(c)
        noise = rng.normal(size=(spec.n_per_env, spec.n_nodes))
        x = (noise + c) @ inverse.T
        frame = pl.DataFrame({name: x[:, i] for i, name in enumerate(columns)})
        frames.append(frame.with_columns(pl.lit(f"E{e}").alias(spec.environment_column)))
    covariance = inverse @ inverse.T
    sd = np.sqrt(np.diag(covariance))
    delta = inverse @ (intercepts[min(1, spec.n_environments - 1)] - intercepts[0])
    mean_shift = {name: float(delta[i] / sd[i]) for i, name in enumerate(columns)}
    return MultiEnvData(
        frame=pl.concat(frames),
        adjacency=adjacency,
        weights=weights,
        shifted_mechanisms=tuple(columns[i] for i in spec.shift_nodes),
        mean_shift=mean_shift,
        columns=columns,
    )
