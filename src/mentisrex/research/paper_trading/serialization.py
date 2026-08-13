"""Deterministic serialization (AIDP M12).

Session → JSON: sync events, per-tick reconciliation summaries, drift, the equity
curve, execution records, and diagnostics. Sorted keys, stable ordering, round-trip
stable. Same style as M11 serialization.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mentisrex.research.paper_trading.diagnostics import diagnostics as _diagnostics
from mentisrex.research.paper_trading.monitoring import monitoring_report as _monitoring_report


def to_dict(session) -> dict:
    return {
        "config": {"initial_capital": session.config.initial_capital,
                   "sizing": asdict(session.config.sizing)},
        "sync_events": [asdict(s) | {"date": _d(s.date)} for s in session.sync_events],
        "equity_curve": [asdict(e) | {"date": _d(e.date)} for e in session.equity_curve],
        "reconciliations": [_rec(r) for r in session.reconciliations],
        "drifts": [_drift(d) for d in session.drifts],
        "execution_records": [asdict(r) | {"when": _d(r.when), "status": r.status.value}
                              for r in session.records],
        "monitoring": asdict(_monitoring_report(session)),
        "diagnostics": _diagnostics(session),
    }


def to_json(session, *, indent: int = 2) -> str:
    return json.dumps(to_dict(session), indent=indent, sort_keys=True, default=str)


def save_json(session, path: str) -> str:
    Path(path).write_text(to_json(session))
    return path


def _d(d):
    return d.isoformat() if d else None


def _rec(r) -> dict:
    return {"as_of": _d(r.as_of), "ok": r.ok, "cash_diff": r.cash_diff,
            "n_internal_positions": r.n_internal_positions,
            "n_external_positions": r.n_external_positions, "categories": r.categories,
            "differences": [asdict(x) for x in r.differences]}


def _drift(d) -> dict:
    return {"as_of": _d(d.as_of), "max_weight_drift": d.max_weight_drift,
            "position_drift": d.position_drift, "cash_drift": d.cash_drift,
            "execution_drift": d.execution_drift, "timing_drift": d.timing_drift,
            "cost_drift": d.cost_drift, "alerts": d.alerts}
