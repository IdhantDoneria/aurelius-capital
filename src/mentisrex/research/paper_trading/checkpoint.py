"""Checkpoint persistence for PaperTradingLoop (AIDP M23).

JSON-based, no external DB. Sufficient to restore:
  - loop cycle sequence counter and seen-snapshot set
  - per-strategy runtime state (last eval date, fingerprints, counters)
  - per-strategy portfolio state (cash, holdings, realized P&L)
  - per-strategy broker state (internal book, order sequence counter)
  - per-strategy session state (_seq, _last_date, total_cost, applied fill IDs)
  - cycle records

Restart guarantee: after loading a checkpoint, continuing processing from the
next unseen snapshot produces the same final state as uninterrupted operation.

No secrets or credentials are saved. Only numerical/structural state.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from mentisrex.research.simulation.models import Holding
from mentisrex.research.simulation.state import PortfolioState

# ── serialization helpers ─────────────────────────────────────────────────────


def _ser_portfolio(state: PortfolioState) -> dict:
    return {
        "initial_capital": state.ledger.initial,
        "cash": state.ledger.cash,
        "realized_pnl_total": state.realized_pnl_total,
        "holdings": {
            sid: {
                "shares": h.shares,
                "cost_basis": h.cost_basis,
                "price": h.price,
                "realized_pnl": h.realized_pnl,
                "opened_at": h.opened_at.isoformat() if h.opened_at else None,
            }
            for sid, h in state.holdings.items()
        },
    }


def _deser_portfolio(d: dict) -> PortfolioState:
    state = PortfolioState(d["initial_capital"])
    # Restore cash directly: post one synthetic entry so ledger.reconciles() passes.
    state.ledger.cash = state.ledger.initial  # reset (PortfolioState sets this in __post_init__)
    target_cash = d["cash"]
    if abs(target_cash - state.ledger.initial) > 1e-12:
        state.ledger.entries = [
            {
                "date": None,
                "kind": "checkpoint_restore",
                "amount": target_cash - state.ledger.initial,
                "security_id": None,
            }
        ]
        state.ledger.cash = target_cash
    state.realized_pnl_total = d.get("realized_pnl_total", 0.0)
    for sid, h in d.get("holdings", {}).items():
        oa = h.get("opened_at")
        state.holdings[sid] = Holding(
            security_id=sid,
            shares=h["shares"],
            cost_basis=h["cost_basis"],
            price=h["price"],
            realized_pnl=h.get("realized_pnl", 0.0),
            opened_at=date.fromisoformat(oa) if oa else None,
        )
    return state


def _ser_broker(broker) -> dict:
    book = getattr(broker, "_book", None)
    return {
        "seq": getattr(broker, "_seq", 0),
        "name": getattr(broker, "name", "mock"),
        "portfolio": _ser_portfolio(book) if book is not None else {},
    }


def _deser_broker_into(broker, d: dict) -> None:
    """Restore broker internal state in-place."""
    broker._seq = d.get("seq", 0)
    portfolio_data = d.get("portfolio")
    if portfolio_data and hasattr(broker, "_book"):
        restored = _deser_portfolio(portfolio_data)
        broker._book.ledger = restored.ledger
        broker._book.holdings = restored.holdings
        broker._book.realized_pnl_total = restored.realized_pnl_total
    # Clear any pending fill queue (should be empty at checkpoint time)
    if hasattr(broker, "_fill_queue"):
        broker._fill_queue = []


# ── cycle records ─────────────────────────────────────────────────────────────


def _ser_cycle_records(records: list) -> list:
    return [r.to_dict() for r in records]


def _deser_cycle_records(data: list) -> list:
    from mentisrex.research.paper_trading.cycle import CycleRecord

    return [CycleRecord.from_dict(d) for d in data]


# ── sync events ───────────────────────────────────────────────────────────────


def _ser_sync_events(events: list) -> list:
    return [
        {
            "seq": e.seq,
            "date": e.date.isoformat() if e.date else None,
            "n_orders": e.n_orders,
            "n_fills": e.n_fills,
            "reconciled": e.reconciled,
            "n_drift_alerts": e.n_drift_alerts,
            "note": e.note,
        }
        for e in events
    ]


def _deser_sync_events(data: list) -> list:
    from mentisrex.research.paper_trading.models import SyncEvent

    events = []
    for d in data:
        dt = d.get("date")
        events.append(
            SyncEvent(
                seq=d["seq"],
                date=date.fromisoformat(dt) if dt else None,
                n_orders=d["n_orders"],
                n_fills=d["n_fills"],
                reconciled=d["reconciled"],
                n_drift_alerts=d["n_drift_alerts"],
                note=d.get("note", ""),
            )
        )
    return events


# ── public API ────────────────────────────────────────────────────────────────


def _checkpoint_dict(loop) -> dict:
    """Produce a serializable dict from all loop state."""
    return {
        "cycle_seq": loop._cycle_seq,
        "seen_snapshots": sorted(loop._seen),
        "strategy_states": {sid: rs.to_dict() for sid, rs in loop._runtime_states.items()},
        "portfolio_states": {
            sid: _ser_portfolio(sess.book.state) for sid, sess in loop._sessions.items()
        },
        "broker_states": {sid: _ser_broker(sess.broker) for sid, sess in loop._sessions.items()},
        "session_seqs": {sid: sess._seq for sid, sess in loop._sessions.items()},
        "session_last_dates": {
            sid: sess._last_date.isoformat() if sess._last_date else None
            for sid, sess in loop._sessions.items()
        },
        "session_total_costs": {sid: sess.total_cost for sid, sess in loop._sessions.items()},
        "session_sync_events": {
            sid: _ser_sync_events(sess.sync_events) for sid, sess in loop._sessions.items()
        },
        "book_applied_fill_ids": {
            sid: sorted(sess.book._applied_fill_ids) for sid, sess in loop._sessions.items()
        },
        "session_applied_fill_ids": {
            sid: list(sess._applied_fill_ids) for sid, sess in loop._sessions.items()
        },
        "session_broker_fill_ids": {
            sid: list(sess._broker_fill_ids) for sid, sess in loop._sessions.items()
        },
        "cycle_records": _ser_cycle_records(loop._cycle_records),
    }


def _restore_checkpoint(loop, data: dict) -> None:
    """Restore loop state in-place from a checkpoint dict."""
    from mentisrex.research.paper_trading.runtime_state import StrategyRuntimeState

    loop._cycle_seq = data.get("cycle_seq", 0)
    loop._seen = set(data.get("seen_snapshots", []))
    loop._cycle_records = _deser_cycle_records(data.get("cycle_records", []))

    for sid, rs_dict in data.get("strategy_states", {}).items():
        if sid in loop._runtime_states:
            restored = StrategyRuntimeState.from_dict(rs_dict)
            rs = loop._runtime_states[sid]
            rs.last_eval_date = restored.last_eval_date
            rs.last_snapshot_fingerprint = restored.last_snapshot_fingerprint
            rs.last_evaluation_id = restored.last_evaluation_id
            rs.last_evaluation_fingerprint = restored.last_evaluation_fingerprint
            rs.evaluation_count = restored.evaluation_count
            rs.error_count = restored.error_count
            rs.last_error = restored.last_error
            rs.status = restored.status

    for sid, port_data in data.get("portfolio_states", {}).items():
        if sid in loop._sessions:
            sess = loop._sessions[sid]
            restored = _deser_portfolio(port_data)
            sess.book.state.ledger = restored.ledger
            sess.book.state.holdings = restored.holdings
            sess.book.state.realized_pnl_total = restored.realized_pnl_total

    for sid, broker_data in data.get("broker_states", {}).items():
        if sid in loop._sessions:
            _deser_broker_into(loop._sessions[sid].broker, broker_data)

    session_seqs = data.get("session_seqs", {})
    session_last_dates = data.get("session_last_dates", {})
    session_total_costs = data.get("session_total_costs", {})
    session_sync_events = data.get("session_sync_events", {})
    book_applied = data.get("book_applied_fill_ids", {})
    sess_applied = data.get("session_applied_fill_ids", {})
    sess_broker_fills = data.get("session_broker_fill_ids", {})

    for sid, sess in loop._sessions.items():
        if sid in session_seqs:
            sess._seq = session_seqs[sid]
        if sid in session_last_dates:
            ld = session_last_dates[sid]
            sess._last_date = date.fromisoformat(ld) if ld else None
        if sid in session_total_costs:
            sess.total_cost = session_total_costs[sid]
        if sid in session_sync_events:
            sess.sync_events = _deser_sync_events(session_sync_events[sid])
        if sid in book_applied:
            sess.book._applied_fill_ids = set(book_applied[sid])
        if sid in sess_applied:
            sess._applied_fill_ids = list(sess_applied[sid])
        if sid in sess_broker_fills:
            sess._broker_fill_ids = list(sess_broker_fills[sid])


def save_checkpoint(path: str, loop) -> None:
    """Save full loop checkpoint to a JSON file."""
    data = _checkpoint_dict(loop)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, default=str))


def load_checkpoint(path: str) -> dict:
    """Load checkpoint dict from a JSON file. Raises FileNotFoundError if missing."""
    return json.loads(Path(path).read_text())
