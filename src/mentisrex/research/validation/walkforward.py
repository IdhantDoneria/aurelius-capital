"""Walk-forward / out-of-sample robustness over time (AIDP M9).

Splits the realized return series into contiguous temporal segments and measures
metric consistency across them — never mixing future into past. True re-fitting
walk-forward needs the M8 executor (an evaluator); this module evaluates a
fixed track record's OOS stability and exposes the interface for re-fitting.
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.validation.significance import sharpe


def _consistency(seg_stats: list[float]) -> dict:
    a = np.asarray(seg_stats, dtype=float)
    if a.size == 0:
        return {"folds": 0, "mean": 0.0, "std": 0.0, "min": 0.0, "share_positive": 0.0}
    return {"folds": int(a.size), "mean": float(a.mean()), "std": float(a.std(ddof=0)),
            "min": float(a.min()), "max": float(a.max()),
            "share_positive": float((a > 0).mean()), "per_fold": [float(x) for x in a]}


def rolling_windows(returns, *, n_folds: int = 5, stat_fn=sharpe) -> dict:
    r = np.asarray(returns, dtype=float)
    if r.size < n_folds * 3:
        return {"type": "rolling", **_consistency([])}
    bounds = np.linspace(0, r.size, n_folds + 1, dtype=int)
    segs = [stat_fn(r[bounds[i]:bounds[i + 1]]) for i in range(n_folds) if bounds[i + 1] > bounds[i]]
    return {"type": "rolling", **_consistency(segs)}


def expanding_windows(returns, *, n_folds: int = 5, stat_fn=sharpe) -> dict:
    r = np.asarray(returns, dtype=float)
    if r.size < n_folds * 3:
        return {"type": "expanding", **_consistency([])}
    bounds = np.linspace(0, r.size, n_folds + 1, dtype=int)[1:]
    segs = [stat_fn(r[:b]) for b in bounds if b >= 3]
    return {"type": "expanding", **_consistency(segs)}


def leave_one_out(returns, timestamps, *, by: str = "year", stat_fn=sharpe) -> dict:
    """Leave-one-period-out: recompute the statistic with each calendar period (year
    by default) removed. Large swings ⇒ a single period drives the result."""
    r = np.asarray(returns, dtype=float)
    if timestamps is None or len(timestamps) != r.size or r.size < 6:
        return {"type": f"leave_one_{by}_out", "insufficient_data": True, **_consistency([])}
    keys = np.array([getattr(t, by) for t in timestamps])
    segs = [stat_fn(r[keys != k]) for k in sorted(set(keys.tolist()))]
    full = stat_fn(r)
    out = {"type": f"leave_one_{by}_out", "full": float(full), **_consistency(segs)}
    out["max_swing"] = float(max(abs(s - full) for s in segs)) if segs else 0.0
    return out
