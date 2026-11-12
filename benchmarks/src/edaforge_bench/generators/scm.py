"""Structural causal models with a known graph (section 16.1).

Linear or nonlinear mechanisms; Gaussian, uniform, Laplace or mixed noise; latent confounders
(nodes generated and then hidden); selection on a common effect; binarized nodes for mixed types;
and a varsortability-controlled variant in which each node is standardized as it is generated, so
that marginal variance no longer increases along the causal order (Reisach, Seiler & Weichwald,
2021). The returned :func:`~edaforge_bench.metrics.varsortability` shows how much order information
the variances leak.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import polars as pl
from numpy.typing import NDArray

__all__ = ["SCMData", "SCMSpec", "random_dag", "structural_causal_model"]

FloatArray = NDArray[np.float64]
IntMatrix = NDArray[np.int64]


def random_dag(n_nodes: int, expected_degree: float, rng: np.random.Generator) -> IntMatrix:
    """Erdos-Renyi DAG: edges i -> j only for i < j in a random causal order."""
    if n_nodes < 2:
        return np.zeros((n_nodes, n_nodes), dtype=np.int64)
    p_edge = min(1.0, expected_degree / (n_nodes - 1))
    upper = np.triu(rng.random((n_nodes, n_nodes)) < p_edge, k=1).astype(np.int64)
    order = rng.permutation(n_nodes)
    adjacency = np.zeros_like(upper)
    adjacency[np.ix_(order, order)] = upper
    return adjacency


@dataclass(frozen=True)
class SCMSpec:
    n: int = 2000
    n_nodes: int = 8
    expected_degree: float = 2.0
    mechanism: Literal["linear", "nonlinear"] = "linear"
    noise: Literal["gaussian", "uniform", "laplace", "mixed"] = "gaussian"
    weight_low: float = 0.5
    weight_high: float = 2.0
    standardize: bool = False  # varsortability control
    n_latent: int = 0  # number of nodes hidden from the output (latent confounders)
    selection_on: int | None = None  # keep rows where this node is above its median
    n_binary: int = 0  # number of observed nodes binarized at their median (mixed types)


@dataclass(frozen=True)
class SCMData:
    frame: pl.DataFrame
    adjacency: IntMatrix  # over all nodes, observed and latent; adjacency[i, j] = 1: i -> j
    order: tuple[int, ...]
    names: tuple[str, ...]
    latent: tuple[str, ...]
    binary: tuple[str, ...]
    selected_rows: int


def _noise(kind: str, rng: np.random.Generator, n: int) -> FloatArray:
    if kind == "uniform":
        return rng.uniform(-np.sqrt(3.0), np.sqrt(3.0), size=n)
    if kind == "laplace":
        return rng.laplace(scale=1.0 / np.sqrt(2.0), size=n)
    if kind == "mixed":
        return _noise(str(rng.choice(np.array(["gaussian", "uniform", "laplace"]))), rng, n)
    return rng.normal(size=n)


def _nonlinear(z: FloatArray, kind: int) -> FloatArray:
    if kind == 0:
        return np.tanh(z)
    if kind == 1:
        return np.sin(z)
    return z**2 / (1.0 + np.abs(z))


def _topological_order(adjacency: IntMatrix) -> list[int]:
    indegree = adjacency.sum(axis=0).astype(np.int64)
    ready = sorted(int(i) for i in np.nonzero(indegree == 0)[0])
    order: list[int] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for child in np.nonzero(adjacency[node])[0]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(int(child))
        ready.sort()
    return order


def structural_causal_model(spec: SCMSpec, seed: int) -> SCMData:
    rng = np.random.default_rng(seed)
    adjacency = random_dag(spec.n_nodes, spec.expected_degree, rng)
    signs = rng.choice(np.array([-1.0, 1.0]), size=adjacency.shape)
    weights = adjacency * signs * rng.uniform(spec.weight_low, spec.weight_high, adjacency.shape)
    kinds = rng.integers(0, 3, size=adjacency.shape)
    order = _topological_order(adjacency)
    values = np.zeros((spec.n, spec.n_nodes))
    for node in order:
        total = _noise(spec.noise, rng, spec.n)
        for parent in np.nonzero(adjacency[:, node])[0]:
            contribution = values[:, parent] * weights[parent, node]
            if spec.mechanism == "nonlinear":
                contribution = _nonlinear(contribution, int(kinds[parent, node]))
            total = total + contribution
        if spec.standardize:
            sd = total.std()
            total = (total - total.mean()) / (sd if sd > 0 else 1.0)
        values[:, node] = total
    names = tuple(f"v{i}" for i in range(spec.n_nodes))
    latent_draw = rng.choice(spec.n_nodes, size=spec.n_latent, replace=False)
    latent_idx = sorted(int(i) for i in latent_draw)
    keep = np.ones(spec.n, dtype=np.bool_)
    if spec.selection_on is not None:
        node = values[:, spec.selection_on]
        keep = node > np.median(node)
    observed = [i for i in range(spec.n_nodes) if i not in latent_idx]
    n_binary = min(spec.n_binary, len(observed))
    binary_idx = sorted(int(i) for i in rng.choice(observed, size=n_binary, replace=False))
    columns: dict[str, FloatArray | NDArray[np.int64]] = {}
    for i in observed:
        column = values[keep, i]
        if i in binary_idx:
            columns[names[i]] = (column > np.median(column)).astype(np.int64)
        else:
            columns[names[i]] = column
    return SCMData(
        frame=pl.DataFrame(columns),
        adjacency=adjacency,
        order=tuple(order),
        names=names,
        latent=tuple(names[i] for i in latent_idx),
        binary=tuple(names[i] for i in binary_idx),
        selected_rows=int(keep.sum()),
    )
