"""Deterministic serialization (AIDP M14).

Session → JSON: routing decisions, per-order execution reports (with their audit
trails and fills), fills, metrics, and diagnostics. Sorted keys, stable ordering,
round-trip stable — same style as M11/M12 serialization, so a session is replayable
and hash-comparable.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mentisrex.research.execution.ems import monitoring


def to_dict(session) -> dict:
    from mentisrex.research.execution.ems.diagnostics import diagnostics as _diag

    return {
        "session_id": session.session_id,
        "config": asdict(session.config),
        "routing_decisions": [asdict(d) for d in session.routing_decisions],
        "reports": [_report(r) for r in session.reports()],
        "fills": [_fill(f) for f in session.fills],
        "rejections": [
            {"order_id": o, "security_id": s, "quantity": q, "reason": r}
            for (o, s, q, r) in session.rejections
        ],
        "metrics": asdict(monitoring.metrics(session)),
        "by_algorithm": monitoring.by_algorithm(session),
        "by_broker": monitoring.by_broker(session),
        "diagnostics": _diag(session),
    }


def to_json(session, *, indent: int = 2) -> str:
    return json.dumps(to_dict(session), indent=indent, sort_keys=True, default=str)


def save_json(session, path: str) -> str:
    Path(path).write_text(to_json(session))
    return path


def _report(r) -> dict:
    return {
        "order_id": r.order_id,
        "security_id": r.security_id,
        "requested_quantity": r.requested_quantity,
        "filled_quantity": r.filled_quantity,
        "avg_fill_price": r.avg_fill_price,
        "arrival_price": r.arrival_price,
        "total_cost": r.total_cost,
        "status": r.status.value,
        "slippage_bps": r.slippage_bps,
        "implementation_shortfall_bps": r.implementation_shortfall_bps,
        "fill_rate": r.fill_rate,
        "n_child_orders": r.n_child_orders,
        "n_fills": r.n_fills,
        "events": [_event(e) for e in r.events],
    }


def _event(e) -> dict:
    return {
        "seq": e.seq,
        "order_id": e.order_id,
        "kind": e.kind,
        "status": e.status.value,
        "detail": e.detail,
        "filled_quantity": e.filled_quantity,
        "when": e.when.isoformat() if e.when else None,
    }


def _fill(f) -> dict:
    return {
        "fill_id": f.fill_id,
        "order_id": f.order_id,
        "child_order_id": f.child_order_id,
        "security_id": f.security_id,
        "quantity": f.quantity,
        "price": f.price,
        "cost": f.cost,
        "when": f.when.isoformat() if f.when else None,
    }
