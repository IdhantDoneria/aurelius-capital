"""FX diagnostics & fingerprint (AIDP M16).

Compact scalar summary + a stable content hash — the determinism anchor. Combines each
per-currency book's M15 fingerprint with the FX overlay (conversions, realized FX P&L,
base value) so two identical multi-currency runs produce the same fingerprint.
"""

from __future__ import annotations

import hashlib

from aurelius.research.fx.valuation import valuation
from aurelius.research.post_trade.diagnostics import fingerprint as _pt_fingerprint


def diagnostics(engine, *, as_of=None) -> dict:
    val = valuation(engine, as_of=as_of)
    return {
        "n_currencies": len(engine.currencies()),
        "n_conversions": len(engine.conversions),
        "n_hedges": len(engine.hedges),
        "total_base_value": round(val.total_base, 6),
        "cash_base": round(val.cash_base, 6),
        "positions_base": round(val.positions_base, 6),
        "realized_fx_pnl": round(engine.realized_fx_pnl, 6),
        "per_book_fingerprint": {c: _pt_fingerprint(e) for c, e in sorted(engine.books.items())},
    }


def fingerprint(engine) -> str:
    d = diagnostics(engine)
    scalar = "|".join(f"{k}={d[k]}" for k in sorted(d) if k != "per_book_fingerprint")
    books = "|".join(f"{c}={h}" for c, h in sorted(d["per_book_fingerprint"].items()))
    conv = ",".join(f"{c.conversion_id}:{c.from_currency}{c.to_currency}:{round(c.rate, 8)}"
                    for c in engine.conversions)
    payload = f"{scalar}||{books}||conv={conv}"
    return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()
