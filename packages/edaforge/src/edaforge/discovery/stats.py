"""Statistical building blocks shared by the discovery analyzers.

Only established methods, each named where it is used:

* restricted (natural) cubic splines with Harrell's knot placement, fitted by least squares;
* the spline R² dependence statistic, calibrated by permutation (Besag-Clifford via the ledger);
* Fisher-z intervals for Pearson and partial correlations, Bonett-Wright (2000) intervals for
  Spearman correlations;
* two one-sided tests (TOST) for "the association is smaller than a threshold" (equivalence);
* heteroscedasticity-robust (HC3) least squares;
* the CUSUM test for a change in mean, calibrated by a sieve (autoregressive) bootstrap under
  the null of no change (Bühlmann, 1997; Kirch, 2007), because asymptotic HAC versions are
  badly sized for the short, autocorrelated series typical of business data.

Nothing here touches the ledger: analyzers obtain every reported p-value through ``ctx.ledger``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import stats

FloatArray = NDArray[np.float64]

__all__ = [
    "FloatArray",
    "bonett_wright_ci",
    "change_point",
    "cusum_null_draw",
    "fisher_ci",
    "fixed_break_draw",
    "fixed_break_stat",
    "hc3_ols",
    "partial_rank_corr",
    "rank",
    "rcs_basis",
    "spearman",
    "spline_fit",
    "spline_r2_draw",
    "spline_r2_pair",
    "tost_corr",
]

_HARRELL = {3: (0.10, 0.5, 0.90), 4: (0.05, 0.35, 0.65, 0.95), 5: (0.05, 0.275, 0.5, 0.725, 0.95)}


def rank(x: FloatArray) -> FloatArray:
    return np.asarray(stats.rankdata(x), dtype=np.float64)


def rcs_basis(x: FloatArray, knots: FloatArray) -> FloatArray:
    """Restricted cubic spline basis (without intercept): x and K-2 non-linear terms."""
    k = knots.size
    scale = (knots[-1] - knots[0]) ** 2 or 1.0
    cols = [x]
    tk, tk1 = knots[-1], knots[-2]
    for j in range(k - 2):
        tj = knots[j]
        term = (
            np.clip(x - tj, 0, None) ** 3
            - np.clip(x - tk1, 0, None) ** 3 * (tk - tj) / (tk - tk1)
            + np.clip(x - tk, 0, None) ** 3 * (tk1 - tj) / (tk - tk1)
        )
        cols.append(term / scale)
    return np.column_stack(cols)


def knots_for(x: FloatArray, n_knots: int = 5) -> FloatArray | None:
    """Harrell's quantile knots; fewer knots when x has few distinct values.

    None if fewer than 3 knots are possible.
    """
    distinct = np.unique(x)
    for k in range(min(n_knots, 5), 2, -1):
        knots = np.unique(np.quantile(x, _HARRELL[k]))
        if knots.size == k and distinct.size >= 2 * k:
            return knots
    return None


def _orthonormal(basis: FloatArray) -> FloatArray:
    centered = basis - basis.mean(axis=0)
    q, r = np.linalg.qr(centered)
    keep = np.abs(np.diag(r)) > 1e-10 * max(1.0, float(np.abs(r).max()))
    return np.asarray(q[:, keep], dtype=np.float64)


def _basis_q(x: FloatArray) -> FloatArray:
    knots = knots_for(x)
    if knots is None:
        return _orthonormal(x[:, None])  # too few distinct values for curvature: linear only
    return _orthonormal(rcs_basis(x, knots))


def spline_r2_pair(x: FloatArray, y: FloatArray) -> tuple[float, float, float]:
    """(max, R²(y | spline x), R²(x | spline y)) — the symmetric dependence statistic."""
    qx, qy = _basis_q(x), _basis_q(y)
    yc, xc = y - y.mean(), x - x.mean()
    syy, sxx = float(yc @ yc), float(xc @ xc)
    if syy == 0 or sxx == 0:
        return 0.0, 0.0, 0.0
    a = float(np.sum((qx.T @ yc) ** 2) / syy)
    b = float(np.sum((qy.T @ xc) ** 2) / sxx)
    return max(a, b), a, b


def spline_r2_draw(
    x: FloatArray, y: FloatArray
) -> Callable[[np.random.Generator, int], FloatArray]:
    """Batch null draws of :func:`spline_r2_pair` under independence (permute y against x)."""
    qx, qy = _basis_q(x), _basis_q(y)
    yc, xc = y - y.mean(), x - x.mean()
    syy, sxx = float(yc @ yc), float(xc @ xc)
    n = x.size
    rows = max(1, 1_500_000 // max(n, 1))
    base = np.arange(n)

    def draw(rng: np.random.Generator, size: int) -> FloatArray:
        out = np.empty(size, dtype=np.float64)
        done = 0
        while done < size:
            m = min(rows, size - done)
            perm = rng.permuted(np.tile(base, (m, 1)), axis=1)
            # Inverse permutations by scatter: the same arrays as argsort(perm), in O(n) per row.
            inv = np.empty_like(perm)
            for row, p in zip(inv, perm, strict=True):
                row[p] = base
            a = np.sum((yc[perm] @ qx) ** 2, axis=1) / syy
            b = np.sum((xc[inv] @ qy) ** 2, axis=1) / sxx
            out[done : done + m] = np.maximum(a, b)
            done += m
        return out

    return draw


def spline_fit(x: FloatArray, y: FloatArray, grid: FloatArray) -> dict[str, Any]:
    """Least-squares spline of y on x: fitted curve on ``grid``, 95% band, linear and spline R²."""
    knots = knots_for(x)
    n = x.size
    if knots is None:
        design = np.column_stack([np.ones(n), x])
        gdesign = np.column_stack([np.ones(grid.size), grid])
    else:
        design = np.column_stack([np.ones(n), rcs_basis(x, knots)])
        gdesign = np.column_stack([np.ones(grid.size), rcs_basis(grid, knots)])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ beta
    resid = y - fitted
    p = design.shape[1]
    sigma2 = float(resid @ resid) / max(n - p, 1)
    xtx_inv = np.linalg.pinv(design.T @ design)
    se = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", gdesign, xtx_inv, gdesign) * sigma2, 0))
    curve = gdesign @ beta
    yc = y - y.mean()
    sst = float(yc @ yc) or 1.0
    lin = np.column_stack([np.ones(n), x])
    lb, *_ = np.linalg.lstsq(lin, y, rcond=None)
    lres = y - lin @ lb
    r2_spline = 1 - float(resid @ resid) / sst
    r2_linear = 1 - float(lres @ lres) / sst
    df_extra = p - 2
    if df_extra > 0 and n - p > 0:
        f = ((float(lres @ lres) - float(resid @ resid)) / df_extra) / sigma2 if sigma2 > 0 else 0.0
        p_nonlin = float(stats.f.sf(max(f, 0.0), df_extra, n - p))
    else:
        f, p_nonlin = 0.0, 1.0
    return {
        "curve": curve,
        "low": curve - 1.96 * se,
        "high": curve + 1.96 * se,
        "r2_spline": r2_spline,
        "r2_linear": r2_linear,
        "f_nonlinear": float(f),
        "df_nonlinear": (df_extra, n - p),
        "p_nonlinear": p_nonlin,
        "knots": [] if knots is None else [float(k) for k in knots],
        "slope_linear": float(lb[1]),
    }


def fisher_ci(r: float, n: int, k: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Fisher-z interval for a (partial) Pearson correlation with ``k`` controlled variables."""
    if n - 3 - k <= 0 or not math.isfinite(r):
        return -1.0, 1.0
    z = math.atanh(max(min(r, 0.999999), -0.999999))
    half = float(stats.norm.ppf(0.5 + level / 2)) / math.sqrt(n - 3 - k)
    return math.tanh(z - half), math.tanh(z + half)


def bonett_wright_ci(rho: float, n: int, k: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Bonett & Wright (2000) interval for a Spearman correlation: se = sqrt((1 + ρ²/2)/(n − 3))."""
    if n - 3 - k <= 0 or not math.isfinite(rho):
        return -1.0, 1.0
    z = math.atanh(max(min(rho, 0.999999), -0.999999))
    half = float(stats.norm.ppf(0.5 + level / 2)) * math.sqrt((1 + rho * rho / 2) / (n - 3 - k))
    return math.tanh(z - half), math.tanh(z + half)


def spearman(x: FloatArray, y: FloatArray) -> tuple[float, float]:
    """Spearman ρ and its two-sided p-value (t approximation, n − 2 df)."""
    n = x.size
    if n < 4:
        return 0.0, 1.0
    rho = float(np.corrcoef(rank(x), rank(y))[0, 1])
    if not math.isfinite(rho):
        return 0.0, 1.0
    if abs(rho) >= 1.0:
        return rho, 0.0
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    return rho, float(2 * stats.t.sf(abs(t), n - 2))


def _residualize(v: FloatArray, controls: FloatArray) -> FloatArray:
    design = np.column_stack([np.ones(v.size), controls])
    beta, *_ = np.linalg.lstsq(design, v, rcond=None)
    return v - design @ beta


def partial_rank_corr(x: FloatArray, y: FloatArray, controls: FloatArray) -> tuple[float, int]:
    """Partial Spearman correlation of x and y given ``controls`` (columns already encoded).

    Ranks of x and y are residualized on the controls (numeric controls by their ranks,
    categorical controls by dummy columns); returns (ρ, number of control columns).
    """
    rx, ry = _residualize(rank(x), controls), _residualize(rank(y), controls)
    sx, sy = float(np.sqrt(rx @ rx)), float(np.sqrt(ry @ ry))
    if sx == 0 or sy == 0:
        return 0.0, controls.shape[1]
    return float(rx @ ry / (sx * sy)), controls.shape[1]


def corr_t_pvalue(r: float, n: int, k: int = 0) -> float:
    df = n - 2 - k
    if df <= 0:
        return 1.0
    if abs(r) >= 1:
        return 0.0
    t = r * math.sqrt(df / (1 - r * r))
    return float(2 * stats.t.sf(abs(t), df))


def tost_corr(r: float, n: int, delta: float, k: int = 0, spearman_se: bool = True) -> float:
    """TOST p-value for H0: |ρ| ≥ δ against H1: |ρ| < δ (Fisher z; Bonett-Wright scale)."""
    if n - 3 - k <= 0:
        return 1.0
    z = math.atanh(max(min(r, 0.999999), -0.999999))
    zd = math.atanh(delta)
    se = (math.sqrt((1 + r * r / 2) / (n - 3 - k))) if spearman_se else 1 / math.sqrt(n - 3 - k)
    p_upper = float(stats.norm.cdf((z - zd) / se))  # evidence that ρ < δ
    p_lower = float(stats.norm.sf((z + zd) / se))  # evidence that ρ > −δ
    return max(p_upper, p_lower)


def hc3_ols(design: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray]:
    """OLS coefficients and HC3 (MacKinnon & White, 1985) standard errors."""
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ beta
    xtx_inv = np.linalg.pinv(design.T @ design)
    leverage = np.einsum("ij,jk,ik->i", design, xtx_inv, design)
    weight = (resid / np.clip(1 - leverage, 1e-8, None)) ** 2
    meat = (design * weight[:, None]).T @ design
    cov = xtx_inv @ meat @ xtx_inv
    return np.asarray(beta, dtype=np.float64), np.sqrt(np.clip(np.diag(cov), 0, None))


def _fit_ar(e: FloatArray, pmax: int = 4) -> tuple[FloatArray, FloatArray]:
    """AR(p) by least squares with p ≤ ``pmax`` chosen by AIC; shrunk to stationarity."""
    t = e.size
    pmax = max(0, min(pmax, t // 10))
    best: tuple[float, FloatArray, FloatArray] | None = None
    for p in range(pmax + 1):
        if p == 0:
            coef = np.zeros(0)
            resid = e[pmax:]
        else:
            design = np.column_stack([e[pmax - k : t - k] for k in range(1, p + 1)])
            target = e[pmax:]
            coef, *_ = np.linalg.lstsq(design, target, rcond=None)
            resid = target - design @ coef
        sse = float(resid @ resid)
        aic = resid.size * math.log(max(sse, 1e-300) / resid.size) + 2 * p
        if best is None or aic < best[0]:
            best = (aic, np.asarray(coef, dtype=np.float64), resid - resid.mean())
    if best is None:  # unreachable: range(pmax + 1) always has the order 0
        msg = "no autoregressive order could be fitted"
        raise ValueError(msg)
    coef = best[1]
    while coef.size and float(np.max(np.abs(np.roots(np.r_[1.0, -coef])))) >= 0.98:
        coef = coef * 0.95
    return coef, best[2]


def _simulate_ar(
    coef: FloatArray, resid: FloatArray, rng: np.random.Generator, size: int, t: int
) -> FloatArray:
    burn = 50
    shocks = rng.choice(resid, size=(size, t + burn))
    out = np.zeros((size, t + burn))
    for i in range(t + burn):
        acc = shocks[:, i].copy()
        for j, c in enumerate(coef):
            if i - j - 1 >= 0:
                acc += c * out[:, i - j - 1]
        out[:, i] = acc
    return out[:, burn:]


def _cusum_stat(series: FloatArray, min_segment: int) -> FloatArray:
    """max_k |S_k| / (sd √T) for each row of a (B, T) array."""
    t = series.shape[1]
    centered = series - series.mean(axis=1, keepdims=True)
    partial = np.cumsum(centered, axis=1)[:, :-1]
    sd = series.std(axis=1, ddof=1)
    window = np.abs(partial[:, min_segment - 1 : t - min_segment])
    return np.asarray(
        window.max(axis=1) / np.where(sd > 0, sd, 1.0) / math.sqrt(t), dtype=np.float64
    )


def change_point(y: FloatArray, min_segment: int = 5) -> dict[str, float | int]:
    """The CUSUM statistic, the most likely change location and the before/after means."""
    t = y.size
    stat = float(_cusum_stat(y[None, :], min_segment)[0])
    partial = np.cumsum(y - y.mean())[:-1]
    ks = np.arange(1, t)
    valid = (ks >= min_segment) & (ks <= t - min_segment)
    k_star = int(ks[valid][np.argmax(np.abs(partial[valid]))])
    before, after = y[:k_star], y[k_star:]
    resid = np.concatenate([before - before.mean(), after - after.mean()])
    tt = np.arange(t, dtype=np.float64)
    design = np.column_stack([np.ones(t), tt])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    return {
        "statistic": stat,
        "index": k_star,
        "mean_before": float(before.mean()),
        "mean_after": float(after.mean()),
        "diff": float(after.mean() - before.mean()),
        "sse_step": float(resid @ resid),
        "sse_trend": float(np.sum((y - design @ beta) ** 2)),
    }


def cusum_null_draw(
    y: FloatArray, min_segment: int = 5
) -> Callable[[np.random.Generator, int], FloatArray]:
    """Sieve-bootstrap null of the CUSUM statistic: AR(p ≤ 4, AIC) fitted to the demeaned series.

    Fitting the autoregression to residuals under the null (no change) keeps the test's size
    close to nominal for autocorrelated series in small samples (checked by simulation for
    AR(1) coefficients 0 to 0.8 and 52 to 120 periods; see docs/adr/0012).
    """
    coef, resid = _fit_ar(y - y.mean())
    t = y.size

    def draw(rng: np.random.Generator, size: int) -> FloatArray:
        return _cusum_stat(_simulate_ar(coef, resid, rng, size, t), min_segment)

    return draw


def fixed_break_draw(y: FloatArray, k: int) -> Callable[[np.random.Generator, int], FloatArray]:
    """Sieve-bootstrap null of |mean(after k) − mean(before k)| / sd for a pre-specified break."""
    coef, resid = _fit_ar(y - y.mean())
    t = y.size

    def draw(rng: np.random.Generator, size: int) -> FloatArray:
        sims = _simulate_ar(coef, resid, rng, size, t)
        sd = sims.std(axis=1, ddof=1)
        diff = np.abs(sims[:, k:].mean(axis=1) - sims[:, :k].mean(axis=1))
        return np.asarray(diff / np.where(sd > 0, sd, 1.0), dtype=np.float64)

    return draw


def fixed_break_stat(y: FloatArray, k: int) -> float:
    sd = float(y.std(ddof=1)) or 1.0
    return abs(float(y[k:].mean() - y[:k].mean())) / sd


def step_diff_interval(
    y: FloatArray, k: int, rng: np.random.Generator, level: float = 0.95, n_boot: int = 999
) -> tuple[float, float]:
    """Percentile interval for the after − before difference: step fit + AR-bootstrap errors."""
    before, after = y[:k], y[k:]
    fitted = np.concatenate([np.full(k, before.mean()), np.full(y.size - k, after.mean())])
    coef, resid = _fit_ar(y - fitted)
    sims = _simulate_ar(coef, resid, rng, n_boot, y.size) + fitted
    diffs = sims[:, k:].mean(axis=1) - sims[:, :k].mean(axis=1)
    lo, hi = np.quantile(diffs, [(1 - level) / 2, (1 + level) / 2])
    return float(lo), float(hi)
