"""Fast paths: each must give the result of the direct computation it replaces."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from edaforge.discovery.charts import _binned_counts, _vega_bins
from edaforge.discovery.relationships import _batch_cliffs_delta, _cliffs_delta, _order_codes
from edaforge.discovery.stats import _basis_q, spline_r2_draw
from edaforge.rigor.bootstrap import bootstrap_interval
from edaforge.server.routes_runs import _PayloadCache


def test_permutation_draws_match_the_argsort_inverses() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=400)
    y = x**2 + rng.normal(size=400)
    qx, qy = _basis_q(x), _basis_q(y)
    yc, xc = y - y.mean(), x - x.mean()
    perm = np.random.default_rng(9).permuted(np.tile(np.arange(x.size), (300, 1)), axis=1)
    inv = np.argsort(perm, axis=1)
    direct = np.maximum(
        np.sum((yc[perm] @ qx) ** 2, axis=1) / float(yc @ yc),
        np.sum((xc[inv] @ qy) ** 2, axis=1) / float(xc @ xc),
    )
    assert np.array_equal(spline_r2_draw(x, y)(np.random.default_rng(9), 300), direct)


def _rank_sum_batch(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cliff's delta per row from pooled rank sums: the computation the counting replaces."""
    na, nb = a.shape[1], b.shape[1]
    ranks = stats.rankdata(np.concatenate([a, b], axis=1), axis=1)
    u = ranks[:, na:].sum(axis=1) - nb * (nb + 1) / 2
    return 2.0 * u / (na * nb) - 1.0


@pytest.mark.parametrize("decimals", [None, 1, 0])
def test_cliffs_delta_bootstrap_on_order_codes_is_unchanged(decimals: int | None) -> None:
    rng = np.random.default_rng(4)
    a, b = rng.normal(size=300), rng.normal(0.3, 1.0, size=200)
    if decimals is not None:  # ties
        a, b = a.round(decimals), b.round(decimals)
    direct = bootstrap_interval(
        [a, b],
        _cliffs_delta,
        np.random.default_rng(8),
        n_resamples=500,
        method="percentile",
        batch_statistic=_rank_sum_batch,
    )
    codes_a, codes_b, k = _order_codes(a, b)
    fast = bootstrap_interval(
        [codes_a, codes_b],
        _cliffs_delta,
        np.random.default_rng(8),
        n_resamples=500,
        method="percentile",
        batch_statistic=_batch_cliffs_delta(k),
    )
    assert fast == direct


def test_order_codes_keep_nan_failing_as_values_do() -> None:
    codes_a, codes_b, k = _order_codes(np.array([1.0, np.nan, 3.0, 2.0]), np.array([2.0, 5.0]))
    with pytest.raises(ValueError, match="non-finite"):
        bootstrap_interval(
            [codes_a, codes_b],
            _cliffs_delta,
            np.random.default_rng(1),
            n_resamples=50,
            method="percentile",
            batch_statistic=_batch_cliffs_delta(k),
        )


@pytest.mark.parametrize(
    ("lo", "hi", "maxbins", "expected"),
    [  # what vega 6 computes: vega-statistics bin, then the Bin transform's stop
        (0.0, 40.0, 40, (0.0, 40.0, 1.0)),
        (-162.16, 4592.61, 30, (-200.0, 4600.0, 200.0)),
        (0.9, 15.2, 30, (0.5, 15.5, 0.5)),
        (5.0, 5.0, 40, (5.0, 5.4, 0.2)),
    ],
)
def test_bins_are_the_ones_vega_computes(
    lo: float, hi: float, maxbins: int, expected: tuple[float, float, float]
) -> None:
    assert _vega_bins(lo, hi, maxbins) == expected


def _sorted_trend(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    xs = np.sort(rng.normal(50.0, 15.0, 250_000))  # more rows than the browser used to be sent
    ys = 0.8 * xs + rng.normal(0.0, 10.0, xs.size)
    ys[::1000] = np.nan
    return xs, ys, (40, 30)


def _rounding_edge(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    # An extent where (stop - step - start) / step rounds to just below a whole number, so
    # clamping values to stop - step (as Vega does) would move the top bin into the one below.
    lo, hi = -0.034711853392699485, -0.03316333346623189
    xs = np.concatenate([[lo, hi], rng.uniform(lo, hi, 5000)])
    return xs, rng.normal(size=xs.size), (20, 30)


@pytest.mark.parametrize("data", [_sorted_trend, _rounding_edge])
def test_heatmap_cells_count_every_row_in_its_cell(data) -> None:
    xs, ys, maxbins = data(np.random.default_rng(6))
    cells, bins = _binned_counts(xs, ys, maxbins)
    edges = [b[0] + b[2] * np.arange(round((b[1] - b[0]) / b[2]) + 1) for b in bins]
    finite = np.isfinite(ys)
    direct, _, _ = np.histogram2d(xs[finite], ys[finite], bins=edges)
    expected = {
        (float(edges[0][i]), float(edges[1][j])): int(n)
        for (i, j), n in np.ndenumerate(direct)
        if n
    }
    assert {(c["x"], c["y"]): c["rows"] for c in cells} == expected
    assert sum(c["rows"] for c in cells) == int(finite.sum())


def test_payload_cache_reuses_an_unchanged_feed_and_rereads_a_changed_one(tmp_path: Path) -> None:
    feed = tmp_path / "feed.json"
    feed.write_text(json.dumps({"feed": [1]}), "utf-8")
    cache = _PayloadCache()
    first = cache.get(feed)
    assert cache.get(feed) is first
    feed.write_text(json.dumps({"feed": [1, 2]}), "utf-8")
    assert cache.get(feed) == {"feed": [1, 2]}


def test_payload_cache_keeps_only_recent_and_small_enough_feeds(tmp_path: Path) -> None:
    paths = []
    for i in range(3):
        path = tmp_path / f"feed{i}.json"
        path.write_text(json.dumps({"i": i}), "utf-8")
        paths.append(path)
    cache = _PayloadCache(max_entries=2)
    first = cache.get(paths[0])
    cache.get(paths[1])
    cache.get(paths[2])
    assert cache.get(paths[0]) is not first  # evicted, so read again
    tiny = _PayloadCache(max_bytes=4)
    assert tiny.get(paths[0]) is not tiny.get(paths[0])  # larger than the budget: never kept
