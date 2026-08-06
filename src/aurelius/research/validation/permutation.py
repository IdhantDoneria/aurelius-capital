"""Permutation / randomization tests (AIDP Phase 9).

Empirical p-values against a null of no genuine timing skill. Three nulls:
  - return: shuffle the return series (destroys ordering/autocorrelation).
  - sign:   randomize the sign (destroys directional edge, keeps magnitudes).
  - signal: shuffle a supplied signal against returns (destroys signal→return link).

The p-value is the share of permutations whose statistic ≥ the observed one
(one-sided, "as good or better by chance"). Deterministic given a seed.
"""

from __future__ import annotations

import numpy as np

KINDS = ("return", "sign", "signal")


def permutation_test(returns, stat_fn, *, kind: str = "return", n_samples: int = 1000,
                     signal=None, seed: int = 0) -> dict:
    r = np.asarray(returns, dtype=float)
    if r.size < 3:
        return {"kind": kind, "observed": float("nan"), "p_value": float("nan"), "n_samples": 0}
    rng = np.random.default_rng(seed)
    observed = float(stat_fn(r))

    if kind == "signal":
        if signal is None:
            raise ValueError("signal permutation requires a signal array")
        s = np.asarray(signal, dtype=float)
        base = r / np.where(s == 0, 1, np.sign(s))  # underlying magnitude
        null = np.array([stat_fn(base * np.sign(rng.permutation(s))) for _ in range(n_samples)])
    elif kind == "sign":
        null = np.array([stat_fn(r * rng.choice([-1.0, 1.0], size=r.size)) for _ in range(n_samples)])
    else:  # return
        null = np.array([stat_fn(rng.permutation(r)) for _ in range(n_samples)])

    p = float((np.sum(null >= observed) + 1) / (n_samples + 1))  # add-one (never 0)
    return {"kind": kind, "observed": observed, "p_value": p,
            "null_mean": float(null.mean()), "n_samples": int(null.size), "distribution": null}
