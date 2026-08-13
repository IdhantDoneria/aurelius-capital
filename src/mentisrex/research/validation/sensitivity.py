"""Parameter / feature / data sensitivity (AIDP M9).

Parameter-perturbation and feature-removal require *re-running* the strategy, so
they take an injected `evaluator(overrides) -> return_series` (the M8 executor,
wrapped). When no evaluator is supplied they report `insufficient_data` rather than
faking a result. Missing-data stress operates on the realized series directly.
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.validation.significance import sharpe


def parameter_perturbation(evaluator, param: str, values: list, *, stat_fn=sharpe) -> dict:
    """Re-evaluate the strategy across neighbouring values of one parameter."""
    if evaluator is None:
        return {"param": param, "insufficient_data": True, "reason": "no evaluator injected"}
    stats = {}
    for v in values:
        rs = evaluator({param: v})
        stats[v] = float(stat_fn(rs)) if rs is not None and len(rs) >= 3 else None
    vals = [s for s in stats.values() if s is not None]
    dispersion = float(np.std(vals)) if len(vals) >= 2 else 0.0
    return {"param": param, "values": {str(k): v for k, v in stats.items()},
            "dispersion": dispersion, "mean": float(np.mean(vals)) if vals else 0.0}


def feature_removal(evaluator, features: list[str], *, stat_fn=sharpe, baseline=None) -> dict:
    """Drop each feature in turn; a big drop ⇒ single-feature dependence."""
    if evaluator is None:
        return {"insufficient_data": True, "reason": "no evaluator injected"}
    base = baseline
    if base is None:
        rs = evaluator({})
        base = float(stat_fn(rs)) if rs is not None else 0.0
    impact = {}
    for f in features:
        rs = evaluator({"drop_feature": f})
        impact[f] = base - (float(stat_fn(rs)) if rs is not None and len(rs) >= 3 else 0.0)
    return {"baseline": base, "impact": impact,
            "max_impact": max(impact.values()) if impact else 0.0}


def missing_data_stress(returns, *, drop_fractions=(0.05, 0.10, 0.20), stat_fn=sharpe,
                        seed: int = 0) -> dict:
    """Randomly drop a fraction of observations and re-measure. Operates on the
    realized series — no evaluator needed."""
    r = np.asarray(returns, dtype=float)
    if r.size < 10:
        return {"insufficient_data": True}
    rng = np.random.default_rng(seed)
    base = float(stat_fn(r))
    out = {}
    for frac in drop_fractions:
        keep = rng.random(r.size) >= frac
        out[str(frac)] = float(stat_fn(r[keep])) if keep.sum() >= 3 else None
    degr = [base - v for v in out.values() if v is not None]
    return {"baseline": base, "stressed": out, "max_degradation": max(degr) if degr else 0.0}
