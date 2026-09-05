"""Deterministic serialization (AIDP M16).

MultiCurrencyBook → JSON: base currency, per-currency book summaries, the full FX
conversion audit, hedges, realized FX P&L, and the base valuation / cash. Sorted keys,
stable ordering, currency-complete: every conversion round-trips exactly (see
`conversion_from_dict`). Reuses the M15 `_clean` recursive normalizer.
"""

from __future__ import annotations

import json
from pathlib import Path

from mentisrex.research.fx.conversion import conversion_to_dict
from mentisrex.research.fx.diagnostics import diagnostics as _diagnostics
from mentisrex.research.fx.diagnostics import fingerprint as _fingerprint
from mentisrex.research.fx.multi_currency_cash import multi_currency_cash
from mentisrex.research.fx.valuation import valuation
from mentisrex.research.post_trade.serialization import _clean


def to_dict(book, *, as_of=None) -> dict:
    return {
        "session_id": book.session_id,
        "base_currency": book.base_currency,
        "provider": getattr(book.provider, "source", "provider"),
        "currencies": book.currencies(),
        "realized_fx_pnl": round(book.realized_fx_pnl, 6),
        "conversions": [conversion_to_dict(c) for c in book.conversions],
        "hedges": [_clean(h) for h in book.hedges],
        "books": {
            c: {
                "n_events": len(e.log),
                "cash": e.accounting.cash,
                "value": e.accounting.value(),
                "n_positions": len(e.accounting.state.holdings),
            }
            for c, e in sorted(book.books.items())
        },
        "value": _clean(valuation(book, as_of=as_of)),
        "cash": _clean(multi_currency_cash(book, as_of=as_of)),
        "diagnostics": _diagnostics(book, as_of=as_of),
        "fingerprint": _fingerprint(book),
    }


def to_json(book, *, indent: int = 2, as_of=None) -> str:
    return json.dumps(to_dict(book, as_of=as_of), indent=indent, sort_keys=True, default=str)


def save_json(book, path: str, *, as_of=None) -> str:
    Path(path).write_text(to_json(book, as_of=as_of))
    return path
