"""Diagnostics & fingerprint (AIDP M17).

A compact health summary of an InstrumentBook plus a stable content hash. The fingerprint
is order-independent over positions and derived only from settled facts, so replaying the
same events reproduces it exactly — the determinism check the tests lean on.
"""

from __future__ import annotations

import hashlib


def diagnostics(book) -> dict:
    positions = book.open_positions()
    by_type = {}
    for p in positions:
        t = book.registry.get(p.instrument_id).type.value
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "n_instruments": len(book.registry),
        "n_open_positions": len(positions),
        "positions_by_type": dict(sorted(by_type.items())),
        "cash": round(book.cash, 6),
        "total_margin": round(sum(book.margin_posted.values()), 6),
        "realized_pnl": round(book.realized_pnl(), 6),
        "unrealized_pnl": round(book.unrealized_pnl(), 6),
        "n_events": len(book.events),
        "n_closed": len(book._closed),
    }


def fingerprint(book) -> str:
    parts = [book.session_id, f"{book.cash:.6f}", f"{book.realized_pnl():.6f}"]
    for p in book.open_positions():
        parts.append(f"{p.instrument_id}|{p.quantity:.6f}|{p.avg_price:.6f}|{p.realized_pnl:.6f}")
    for iid in sorted(book.margin_posted):
        parts.append(f"M:{iid}|{book.margin_posted[iid]:.6f}")
    return hashlib.blake2b("\n".join(parts).encode(), digest_size=16).hexdigest()
