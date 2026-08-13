"""Diagnostics & fingerprint (AIDP M14).

A compact scalar summary of a session and a stable content hash. The fingerprint is
the determinism anchor: two runs of the same inputs must produce the same hash.
Mirrors M12/M13 `diagnostics` + `fingerprint`.
"""

from __future__ import annotations

import hashlib

from mentisrex.research.execution.ems import monitoring


def diagnostics(session) -> dict:
    m = monitoring.metrics(session)
    reports = session.reports()
    return {
        "n_orders": m.n_orders,
        "n_filled": m.n_filled,
        "n_partial": m.n_partial,
        "n_rejected": m.n_rejected,
        "n_cancelled": m.n_cancelled,
        "n_child_orders": m.n_child_orders,
        "n_fills": m.n_fills,
        "fill_rate": round(m.fill_rate, 10),
        "total_filled_notional": round(m.total_filled_notional, 6),
        "total_requested_notional": round(m.total_requested_notional, 6),
        "total_cost": round(m.total_cost, 10),
        "total_cost_bps": round(m.total_cost_bps, 10),
        "avg_slippage_bps": round(m.avg_slippage_bps, 10),
        "avg_implementation_shortfall_bps": round(m.avg_implementation_shortfall_bps, 10),
        "n_events": sum(len(r.events) for r in reports),
        "n_alerts": len(m.alerts),
    }


def fingerprint(session) -> str:
    d = diagnostics(session)
    payload = "|".join(f"{k}={d[k]}" for k in sorted(d))
    return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()
