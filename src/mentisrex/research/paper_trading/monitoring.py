"""Monitoring aggregation (AIDP M12).

Rolls the per-tick reconciliation + drift history of a session into one
`MonitoringReport`: reconciliation rate, worst weight drift, total cost, and the
collected alerts. Read-only over the session's recorded history.
"""

from __future__ import annotations

from mentisrex.research.paper_trading.models import MonitoringReport


def monitoring_report(session) -> MonitoringReport:
    syncs = session.sync_events
    n = len(syncs)
    n_ok = sum(1 for s in syncs if s.reconciled)
    max_wd = max((d.max_weight_drift for d in session.drifts), default=0.0)
    alerts = [f"{d.as_of}: {a}" for d in session.drifts for a in d.alerts]
    breaks = [f"{r.as_of}: {r.categories}" for r in session.reconciliations if not r.ok]
    consistency_ok = (n_ok == n) and session.book.state.ledger.reconciles()
    return MonitoringReport(
        n_syncs=n, n_reconciled=n_ok, reconciliation_rate=(n_ok / n if n else 1.0),
        max_weight_drift=max_wd, total_cost=session.total_cost,
        total_alerts=len(alerts), consistency_ok=consistency_ok,
        alerts=alerts + breaks)
