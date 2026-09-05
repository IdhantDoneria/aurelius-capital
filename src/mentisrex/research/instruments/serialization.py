"""Deterministic serialization (AIDP M17).

InstrumentBook -> JSON: registry, open positions, margin/collateral, the instrument event
log, cash and P&L, plus a fingerprint. Sorted keys, stable ordering, rounded money — two
identical books serialize byte-identically (the determinism guarantee). Reuses the M15
`_clean` normalizer.
"""

from __future__ import annotations

import json

from mentisrex.research.instruments.diagnostics import diagnostics as _diag
from mentisrex.research.instruments.diagnostics import fingerprint as _fp
from mentisrex.research.post_trade.serialization import _clean


def instrument_to_dict(inst) -> dict:
    return {
        "instrument_id": inst.instrument_id,
        "type": inst.type.value,
        "currency": inst.currency,
        "exchange": inst.exchange,
        "contract_size": inst.contract_size,
        "expiry": inst.expiry.isoformat() if inst.expiry else None,
        "cash_convention": inst.cash_convention.value,
        "settlement_style": inst.settlement_style.value,
        "underlying": inst.underlying,
        "strike": inst.strike,
        "right": inst.right.value if inst.right else None,
        "initial_margin_rate": inst.initial_margin_rate,
        "maintenance_margin_rate": inst.maintenance_margin_rate,
    }


def to_dict(book) -> dict:
    return {
        "session_id": book.session_id,
        "cash": round(book.cash, 6),
        "realized_pnl": round(book.realized_pnl(), 6),
        "unrealized_pnl": round(book.unrealized_pnl(), 6),
        "instruments": [instrument_to_dict(i) for i in book.registry.all()],
        "positions": [_clean(p) for p in book.open_positions()],
        "margin_posted": {k: round(v, 6) for k, v in sorted(book.margin_posted.items())},
        "collateral": {k: _clean(v) for k, v in sorted(book.collateral.items())},
        "n_events": len(book.events),
        "events": [_clean(e) for e in book.events.events],
        "diagnostics": _diag(book),
        "fingerprint": _fp(book),
    }


def to_json(book, *, indent: int = 2) -> str:
    return json.dumps(to_dict(book), indent=indent, sort_keys=True, default=str)


def save_json(book, path: str) -> None:
    from pathlib import Path

    Path(path).write_text(to_json(book))
