"""Drawdown risk (AIDP M13).

Reuses the M11 `drawdown()` (max/avg/recovery/underwater) and adds current
drawdown, a rolling-window max drawdown, and a halt rule. `should_halt` is the
deployable drawdown-limit check used by the pre-trade gate and monitoring.
"""

from __future__ import annotations

import numpy as np

from aurelius.research.risk.models import DrawdownReport
from aurelius.research.simulation.performance import drawdown as _m11_drawdown


def drawdown_report(values, *, window: int = 63, halt_threshold: float = -0.25) -> DrawdownReport:
    v = np.asarray(values, dtype=float)
    m11 = _m11_drawdown(v)
    if v.size == 0:
        return DrawdownReport(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False)
    peak = np.maximum.accumulate(v)
    current = float((v[-1] - peak[-1]) / peak[-1]) if peak[-1] > 0 else 0.0
    seg = v[-window:]
    rp = np.maximum.accumulate(seg)
    rolling = float(((seg - rp) / rp).min()) if seg.size else 0.0
    return DrawdownReport(
        max_drawdown=m11.max_drawdown, avg_drawdown=m11.avg_drawdown,
        current_drawdown=current, max_recovery_days=m11.max_recovery_days,
        time_underwater_frac=m11.time_underwater_frac, rolling_max_drawdown=rolling,
        halt_triggered=bool(current <= halt_threshold or m11.max_drawdown <= halt_threshold))


def should_halt(values, *, halt_threshold: float = -0.25) -> bool:
    return drawdown_report(values, halt_threshold=halt_threshold).halt_triggered
