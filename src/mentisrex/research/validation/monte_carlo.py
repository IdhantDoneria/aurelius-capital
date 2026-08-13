"""Monte Carlo perturbation of a realized track record (AIDP M9).

Stress the result by injecting the frictions and uncertainties a live deployment
would face — return noise, per-period slippage, trade reordering, execution delay —
and report the confidence band of the resulting metric. Deterministic given a seed.
"""

from __future__ import annotations

import numpy as np

PERTURBATIONS = ("noise", "slippage", "trade_order", "execution_delay")


def _perturb(r: np.ndarray, kinds, noise_sd: float, slippage_bps: float,
             max_delay: int, rng: np.random.Generator) -> np.ndarray:
    out = r.copy()
    if "noise" in kinds:
        out = out + rng.normal(0.0, noise_sd, size=out.size)
    if "slippage" in kinds:
        # random per-period cost drag, in return space
        out = out - np.abs(rng.normal(0.0, slippage_bps / 1e4, size=out.size))
    if "trade_order" in kinds:  # reorder blocks (path dependence stress)
        rng.shuffle(out)
    if "execution_delay" in kinds and max_delay > 0:
        shift = int(rng.integers(0, max_delay + 1))
        out = np.roll(out, shift)
    return out


def monte_carlo(returns, stat_fn, *, n_samples: int = 1000,
                kinds=("noise", "slippage"), noise_sd: float | None = None,
                slippage_bps: float = 5.0, max_delay: int = 2, seed: int = 0) -> dict:
    """Distribution of `stat_fn` under repeated perturbation. `noise_sd` defaults to
    10% of the return series' own std."""
    r = np.asarray(returns, dtype=float)
    if r.size < 3:
        return {"estimate": float("nan"), "band_low": float("nan"),
                "band_high": float("nan"), "prob_le_zero": float("nan"), "n_samples": 0}
    if noise_sd is None:
        noise_sd = 0.1 * float(r.std(ddof=1))
    rng = np.random.default_rng(seed)
    dist = np.array([stat_fn(_perturb(r, kinds, noise_sd, slippage_bps, max_delay, rng))
                     for _ in range(n_samples)])
    return {
        "estimate": float(np.median(dist)),
        "band_low": float(np.percentile(dist, 5)),
        "band_high": float(np.percentile(dist, 95)),
        "prob_le_zero": float((dist <= 0).mean()),
        "n_samples": int(dist.size),
        "kinds": list(kinds),
        "distribution": dist,
    }
