"""Parameter stability surfaces (AIDP M9).

Scan a parameter grid and score how *flat* the performance surface is: a broad
plateau (neighbouring parameter values perform similarly) is far more trustworthy
than an isolated peak, which usually signals overfitting to one lucky setting.
Requires an injected evaluator; otherwise reports insufficient_data.
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.validation.significance import sharpe


def stability_curve(
    evaluator, param: str, values: list, *, stat_fn=sharpe, plateau_frac: float = 0.8
) -> dict:
    """1-D stability. plateau_score = share of grid points within `plateau_frac` of
    the peak — high when the good region is wide, low for a lone spike."""
    if evaluator is None:
        return {"param": param, "insufficient_data": True, "reason": "no evaluator injected"}
    metrics = []
    for v in values:
        rs = evaluator({param: v})
        metrics.append(float(stat_fn(rs)) if rs is not None and len(rs) >= 3 else float("nan"))
    arr = np.array(metrics, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0 or finite.max() <= 0:
        return {
            "param": param,
            "values": list(map(str, values)),
            "metrics": metrics,
            "plateau_score": 0.0,
            "peak": 0.0,
        }
    peak = float(finite.max())
    plateau = float((finite >= plateau_frac * peak).mean())
    return {
        "param": param,
        "values": list(map(str, values)),
        "metrics": metrics,
        "peak": peak,
        "plateau_score": plateau,
        "argmax": str(values[int(np.nanargmax(arr))]),
    }


def stability_surface(
    evaluator, param_x: str, xs: list, param_y: str, ys: list, *, stat_fn=sharpe
) -> dict:
    """2-D surface over two parameters (data for a heatmap)."""
    if evaluator is None:
        return {"insufficient_data": True, "reason": "no evaluator injected"}
    grid = []
    for y in ys:
        row = []
        for x in xs:
            rs = evaluator({param_x: x, param_y: y})
            row.append(float(stat_fn(rs)) if rs is not None and len(rs) >= 3 else float("nan"))
        grid.append(row)
    return {
        "param_x": param_x,
        "param_y": param_y,
        "xs": list(map(str, xs)),
        "ys": list(map(str, ys)),
        "surface": grid,
    }
