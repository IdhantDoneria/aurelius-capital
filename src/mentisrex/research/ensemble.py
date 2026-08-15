"""Signal ensembling (M37, §XX).

Combines the independent, non-redundant edges from the factor library (M35) into
one composite return stream. The goal is not maximum historical Sharpe — it is a
more robust portfolio of *independent* sources of edge, so the diagnostics here
(correlation, diversification ratio, effective number of bets) matter as much as
the combined Sharpe.

Combination methods:
  equal        1/K weights — no estimation, hardest to overfit.
  inverse_var  weight ∝ 1/variance — down-weights noisy factors.
  ic_weight    weight ∝ max(IC, 0) — lean on stronger predictors (needs ic_map).

Pure/deterministic, numpy only. Series are aligned on their overlapping prefix.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mentisrex.research.validation.hac import hac_significance
from mentisrex.research.validation.significance import sharpe


def _align(series_map: dict) -> tuple[list[str], np.ndarray]:
    """Names + (K, T) matrix aligned on the shortest series."""
    names = list(series_map)
    if not names:
        return [], np.empty((0, 0))
    T = min(len(series_map[n]) for n in names)
    M = np.array([series_map[n][:T] for n in names], dtype=float)
    return names, M


def correlation_matrix(series_map: dict) -> tuple[list[str], np.ndarray]:
    names, M = _align(series_map)
    if len(names) < 2 or M.shape[1] < 2:
        return names, np.eye(len(names))
    return names, np.corrcoef(M)


def diversification_ratio(weights: np.ndarray, M: np.ndarray) -> float:
    """Weighted average stdev / portfolio stdev. 1.0 = no benefit; higher = more
    diversification from combining imperfectly-correlated factors."""
    vols = M.std(axis=1, ddof=0)
    port = (weights @ M).std(ddof=0)
    if port <= 0:
        return float("nan")
    return float((weights @ vols) / port)


def effective_bets(M: np.ndarray) -> float:
    """Effective number of independent bets = exp(entropy of the correlation
    eigenvalue spectrum). K uncorrelated factors → K; fully redundant (rank-1)
    factors → 1. Meucci-style PCA diversification measure over the factor set."""
    K = M.shape[0]
    if K <= 1:
        return float(K)
    if M.shape[1] < 2:
        return float("nan")
    corr = np.corrcoef(M)
    lam = np.linalg.eigvalsh(corr)
    lam = np.clip(lam, 0.0, None)
    total = lam.sum()
    if total <= 0:
        return float("nan")
    p = np.clip(lam / total, 1e-12, 1.0)
    return float(np.exp(-(p * np.log(p)).sum()))


@dataclass
class Ensemble:
    names: list
    weights: dict
    combined_series: list
    sharpe: float
    t_stat: float                # HAC (M31)
    p_value: float
    diversification_ratio: float
    effective_bets: float
    avg_correlation: float

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def combine(series_map: dict, *, method: str = "equal", ic_map: dict | None = None,
            periods_per_year: int = 12) -> Ensemble:
    names, M = _align(series_map)
    if len(names) == 0:
        raise ValueError("no factors to combine")
    K = len(names)

    if method == "equal":
        w = np.ones(K) / K
    elif method == "inverse_var":
        v = M.var(axis=1, ddof=0)
        inv = np.where(v > 0, 1.0 / v, 0.0)
        w = inv / inv.sum() if inv.sum() > 0 else np.ones(K) / K
    elif method == "ic_weight":
        if ic_map is None:
            raise ValueError("ic_weight requires ic_map")
        ic = np.array([max(ic_map.get(n, 0.0), 0.0) for n in names])
        w = ic / ic.sum() if ic.sum() > 0 else np.ones(K) / K
    else:
        raise ValueError(f"unknown method {method!r}")

    combined = w @ M
    h = hac_significance(combined)
    _, corr = correlation_matrix(series_map)
    off = corr[np.triu_indices(K, k=1)] if K > 1 else np.array([])
    return Ensemble(
        names=names,
        weights=dict(zip(names, (float(x) for x in w), strict=True)),
        combined_series=[float(x) for x in combined],
        sharpe=sharpe(combined, periods=periods_per_year) if combined.size >= 2 else float("nan"),
        t_stat=h["hac_t_stat"], p_value=h["hac_p_value"],
        diversification_ratio=diversification_ratio(w, M),
        effective_bets=effective_bets(M),
        avg_correlation=float(off.mean()) if off.size else float("nan"),
    )
