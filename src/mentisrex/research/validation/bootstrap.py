"""Bootstrap resampling of a return series (AIDP M9).

Four schemes: IID, moving-block, circular-block, and stationary (Politis & Romano
1994, geometric block lengths). Block methods preserve short-horizon
autocorrelation that IID destroys — important for Sharpe-ratio inference on serially
correlated returns. Deterministic given a seed.

Reference: Politis & Romano (1994) "The Stationary Bootstrap", JASA.
"""

from __future__ import annotations

import numpy as np

METHODS = ("iid", "moving_block", "circular_block", "stationary")


def _resample(r: np.ndarray, method: str, block: int, rng: np.random.Generator) -> np.ndarray:
    n = r.size
    if method == "iid":
        return rng.choice(r, size=n, replace=True)
    if method == "moving_block":
        nblocks = -(-n // block)
        starts = rng.integers(0, max(n - block + 1, 1), size=nblocks)
        out = np.concatenate([r[s : s + block] for s in starts])
        return out[:n]
    if method == "circular_block":
        nblocks = -(-n // block)
        starts = rng.integers(0, n, size=nblocks)
        out = np.concatenate([np.take(r, range(s, s + block), mode="wrap") for s in starts])
        return out[:n]
    if method == "stationary":
        out = np.empty(n)
        i = 0
        idx = int(rng.integers(0, n))
        p = 1.0 / block
        while i < n:
            out[i] = r[idx % n]
            i += 1
            if rng.random() < p:
                idx = int(rng.integers(0, n))
            else:
                idx += 1
        return out
    raise ValueError(f"unknown bootstrap method: {method}")


def bootstrap_distribution(
    returns,
    stat_fn,
    *,
    n_samples: int = 1000,
    method: str = "stationary",
    block: int = 20,
    seed: int = 0,
) -> np.ndarray:
    """Bootstrap sampling distribution of `stat_fn` over resampled returns."""
    r = np.asarray(returns, dtype=float)
    if r.size < 3:
        return np.array([])
    rng = np.random.default_rng(seed)
    return np.array([stat_fn(_resample(r, method, block, rng)) for _ in range(n_samples)])


def bootstrap_ci(
    returns,
    stat_fn,
    *,
    n_samples: int = 1000,
    method: str = "stationary",
    block: int = 20,
    alpha: float = 0.05,
    seed: int = 0,
) -> dict:
    """Percentile bootstrap point estimate + (1-alpha) CI + p(stat<=0)."""
    dist = bootstrap_distribution(
        returns, stat_fn, n_samples=n_samples, method=method, block=block, seed=seed
    )
    if dist.size == 0:
        return {
            "method": method,
            "estimate": float("nan"),
            "ci_low": float("nan"),
            "ci_high": float("nan"),
            "prob_le_zero": float("nan"),
            "n_samples": 0,
        }
    return {
        "method": method,
        "estimate": float(np.median(dist)),
        "ci_low": float(np.percentile(dist, 100 * alpha / 2)),
        "ci_high": float(np.percentile(dist, 100 * (1 - alpha / 2))),
        "prob_le_zero": float((dist <= 0).mean()),
        "n_samples": int(dist.size),
        "distribution": dist,
    }
