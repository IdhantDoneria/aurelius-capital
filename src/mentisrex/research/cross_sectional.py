"""Cross-sectional neutralization + signal redundancy detection (M32).

Operates on a single cross-section: a vector of signal values across securities
at one date. Pure/deterministic, numpy only. Missing values (NaN) are handled
pairwise-complete — never imputed, never look-ahead.

Two concerns, one module because redundancy detection reuses neutralization:
  1. Neutralization (§XI): rank / percentile / z-score, and residualization of a
     signal against sector dummies and/or continuous covariates (beta, vol) so a
     factor's edge is measured net of known exposures.
  2. Redundancy (§XII): is a "new" signal a disguised version of one we already
     have? Two tests — raw correlation, and IC-collapse after residualizing the
     new signal on the existing one.
"""

from __future__ import annotations

import numpy as np

# ── ranking / standardization ────────────────────────────────────────────────


def _finite_mask(*arrays) -> np.ndarray:
    m = np.ones(np.asarray(arrays[0]).shape, dtype=bool)
    for a in arrays:
        m &= np.isfinite(np.asarray(a, dtype=float))
    return m


def rankdata(x) -> np.ndarray:
    """Average-rank of finite entries (1..k); NaN stays NaN. Deterministic on ties."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    m = np.isfinite(x)
    v = x[m]
    if v.size == 0:
        return out
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(v.size, dtype=float)
    sv = v[order]
    i = 0
    while i < sv.size:
        j = i
        while j + 1 < sv.size and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0  # average rank, 1-based
        i = j + 1
    out[m] = ranks
    return out


def percentile_rank(x) -> np.ndarray:
    """Cross-sectional percentile in [0,1] (average-rank based). NaN preserved."""
    r = rankdata(x)
    m = np.isfinite(r)
    k = m.sum()
    if k <= 1:
        out = np.full(r.shape, np.nan)
        if k == 1:
            out[m] = 0.5  # singleton cross-section: median rank by convention
        return out
    out = np.full(r.shape, np.nan)
    out[m] = (r[m] - 1.0) / (k - 1.0)
    return out


def zscore(x) -> np.ndarray:
    """Cross-sectional z-score over finite entries (ddof=0). NaN preserved."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    m = np.isfinite(x)
    v = x[m]
    if v.size < 2:
        return out
    sd = v.std(ddof=0)
    out[m] = (v - v.mean()) / sd if sd > 0 else 0.0
    return out


# ── residualization / neutralization ─────────────────────────────────────────


def _design(n, groups, covariates) -> np.ndarray:
    """Design matrix: intercept + one-hot group dummies (drop first) + covariates."""
    cols = [np.ones(n)]
    if groups is not None:
        g = np.asarray(groups)
        levels = list(dict.fromkeys(g.tolist()))[1:]  # drop first => baseline
        for lv in levels:
            cols.append((g == lv).astype(float))
    if covariates is not None:
        cov = np.asarray(covariates, dtype=float)
        if cov.ndim == 1:
            cov = cov[:, None]
        cols.extend(cov[:, j] for j in range(cov.shape[1]))
    return np.column_stack(cols)


def neutralize(x, *, groups=None, covariates=None) -> np.ndarray:
    """OLS residual of x on group dummies and/or continuous covariates.

    groups: categorical labels (sector) → sector-neutral. covariates: continuous
    exposures (beta, vol) → beta/vol-neutral. With neither, returns x demeaned.
    Residual is the part of the signal orthogonal to the known exposures. Rows
    with any NaN (in x, groups, or covariates) are excluded and returned NaN.
    """
    x = np.asarray(x, dtype=float)
    mask = np.isfinite(x)
    if covariates is not None:
        cov = np.asarray(covariates, dtype=float)
        mask &= _finite_mask(*(cov.T if cov.ndim == 2 else (cov,)))
    if groups is not None:
        g = np.asarray(groups)
        mask &= np.array([lv is not None and lv == lv for lv in g])  # drop None/NaN
    out = np.full(x.shape, np.nan)
    idx = np.flatnonzero(mask)
    if idx.size < 2:
        return out
    xi = x[idx]
    D = _design(
        idx.size,
        None if groups is None else np.asarray(groups)[idx],
        None if covariates is None else np.asarray(covariates, dtype=float)[idx],
    )
    beta, *_ = np.linalg.lstsq(D, xi, rcond=None)
    out[idx] = xi - D @ beta
    return out


# ── information coefficient / correlation ─────────────────────────────────────


def pearson(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    m = _finite_mask(a, b)
    if m.sum() < 2:
        return float("nan")
    av, bv = a[m], b[m]
    sa, sb = av.std(ddof=0), bv.std(ddof=0)
    if sa == 0 or sb == 0:
        return 0.0
    return float(((av - av.mean()) * (bv - bv.mean())).mean() / (sa * sb))


def spearman(a, b) -> float:
    """Rank correlation — the standard cross-sectional IC estimator."""
    return pearson(rankdata(a), rankdata(b))


def information_coefficient(signal, fwd_returns, *, method: str = "spearman") -> float:
    return spearman(signal, fwd_returns) if method == "spearman" else pearson(signal, fwd_returns)


def quantile_spread(signal, fwd_returns, *, q: int = 5) -> dict:
    """Sort into q buckets by signal; report per-bucket mean fwd return, top-minus-
    bottom long-short spread, and monotonicity of the bucket means."""
    signal = np.asarray(signal, dtype=float)
    fwd = np.asarray(fwd_returns, dtype=float)
    m = _finite_mask(signal, fwd)
    s, f = signal[m], fwd[m]
    if s.size < q:
        return {"buckets": [], "long_short": float("nan"), "monotonic": False}
    pr = percentile_rank(s)
    # bucket 0..q-1; clip the top edge (pr==1.0) into the last bucket
    b = np.minimum((pr * q).astype(int), q - 1)
    means = [float(f[b == i].mean()) if np.any(b == i) else float("nan") for i in range(q)]
    valid = [x for x in means if x == x]
    ls = means[-1] - means[0] if means[0] == means[0] and means[-1] == means[-1] else float("nan")
    diffs = np.diff([x for x in means if x == x])
    monotonic = bool(len(valid) >= 2 and (np.all(diffs >= 0) or np.all(diffs <= 0)))
    return {"buckets": means, "long_short": float(ls), "monotonic": monotonic}


# ── signal redundancy ─────────────────────────────────────────────────────────


def is_disguised(
    new_signal,
    existing_signal,
    fwd_returns,
    *,
    corr_threshold: float = 0.7,
    ic_retention_floor: float = 0.3,
) -> dict:
    """Is `new_signal` a disguised version of `existing_signal`?

    Two independent tests, disguised if EITHER fires:
      - raw |Spearman corr| with the existing signal >= corr_threshold, OR
      - residualizing new on existing destroys its edge: the residual IC retains
        less than `ic_retention_floor` of the raw IC (magnitude).
    """
    corr = spearman(new_signal, existing_signal)
    raw_ic = information_coefficient(new_signal, fwd_returns)
    resid = neutralize(new_signal, covariates=np.asarray(existing_signal, dtype=float))
    resid_ic = information_coefficient(resid, fwd_returns)
    retention = (abs(resid_ic) / abs(raw_ic)) if raw_ic and abs(raw_ic) > 1e-12 else float("nan")
    by_corr = abs(corr) >= corr_threshold if corr == corr else False
    by_ic = retention == retention and retention < ic_retention_floor
    return {
        "correlation": float(corr),
        "raw_ic": float(raw_ic),
        "residual_ic": float(resid_ic),
        "ic_retention": float(retention) if retention == retention else float("nan"),
        "disguised": bool(by_corr or by_ic),
        "reason": ("high_correlation" if by_corr else "ic_collapse" if by_ic else "independent"),
    }


def redundancy_report(
    new_signal, existing: dict, fwd_returns=None, *, corr_threshold: float = 0.7
) -> dict:
    """Screen a new signal against a library of existing signals (name -> vector).

    Flags any existing signal it duplicates. When `fwd_returns` is given, uses the
    full is_disguised test (corr + IC-collapse); otherwise correlation only.
    """
    hits = []
    for name, vec in existing.items():
        if fwd_returns is not None:
            d = is_disguised(new_signal, vec, fwd_returns, corr_threshold=corr_threshold)
            if d["disguised"]:
                hits.append({"signal": name, **d})
        else:
            c = spearman(new_signal, vec)
            if c == c and abs(c) >= corr_threshold:
                hits.append(
                    {
                        "signal": name,
                        "correlation": float(c),
                        "disguised": True,
                        "reason": "high_correlation",
                    }
                )
    return {"redundant": bool(hits), "matches": hits, "n_compared": len(existing)}
