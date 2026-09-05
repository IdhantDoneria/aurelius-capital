"""Drift monitoring (AIDP M12).

Six drift measures between intent (target), internal book, and broker reality:

  weight    — |internal_weight - target_weight| per name, and the max
  position  — gross share mismatch internal vs broker, as a fraction of shares
  cash      — |internal_cash - external_cash| / value
  execution — realized fill price vs intended mark, in bps (from records)
  timing    — days between the intended sync date and the actual one
  cost      — |actual_cost - expected_cost| / expected

Threshold breaches become alerts. Pure function of the passed-in state.
"""

from __future__ import annotations

from dataclasses import dataclass

from mentisrex.research.paper_trading.models import DriftReport


@dataclass(frozen=True)
class DriftThresholds:
    weight: float = 0.02  # 2% absolute weight drift
    position: float = 0.05  # 5% gross share mismatch
    cash: float = 0.01  # 1% of value
    execution_bps: float = 25.0
    timing_days: float = 2.0
    cost_frac: float = 0.50  # 50% over expected


def compute_drift(
    internal,
    external,
    target,
    *,
    when=None,
    timing_gap_days=0.0,
    execution_bps=0.0,
    expected_cost=None,
    actual_cost=None,
    thresholds: DriftThresholds | None = None,
) -> DriftReport:
    t = thresholds or DriftThresholds()
    iw = internal.weights()
    sids = set(iw) | set(target or {})
    weight_drift = {sid: abs(iw.get(sid, 0.0) - (target or {}).get(sid, 0.0)) for sid in sids}
    max_wd = max(weight_drift.values(), default=0.0)

    ep = external.positions
    ih = internal.holdings
    gross_shares = sum(abs(h.shares) for h in ih.values()) or 1.0
    pos_mismatch = sum(
        abs((ih[s].shares if s in ih else 0.0) - (ep[s].quantity if s in ep else 0.0))
        for s in set(ih) | set(ep)
    )
    position_drift = pos_mismatch / gross_shares

    value = max(internal.total_value(), 1.0)
    cash_drift = abs(internal.cash - external.cash) / value

    cost_drift = 0.0
    if expected_cost is not None and actual_cost is not None and expected_cost > 0:
        cost_drift = abs(actual_cost - expected_cost) / expected_cost

    alerts = []
    if max_wd > t.weight:
        alerts.append(f"weight_drift {max_wd:.3f} > {t.weight}")
    if position_drift > t.position:
        alerts.append(f"position_drift {position_drift:.3f} > {t.position}")
    if cash_drift > t.cash:
        alerts.append(f"cash_drift {cash_drift:.3f} > {t.cash}")
    if execution_bps > t.execution_bps:
        alerts.append(f"execution_drift {execution_bps:.1f}bps > {t.execution_bps}")
    if timing_gap_days > t.timing_days:
        alerts.append(f"timing_drift {timing_gap_days:.1f}d > {t.timing_days}")
    if cost_drift > t.cost_frac:
        alerts.append(f"cost_drift {cost_drift:.2f} > {t.cost_frac}")

    return DriftReport(
        as_of=when,
        weight_drift=weight_drift,
        max_weight_drift=max_wd,
        position_drift=position_drift,
        cash_drift=cash_drift,
        execution_drift=execution_bps,
        timing_drift=timing_gap_days,
        cost_drift=cost_drift,
        alerts=alerts,
    )
