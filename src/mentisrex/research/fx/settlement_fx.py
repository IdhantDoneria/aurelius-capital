"""Cross-currency settlement (AIDP M16).

Extends M15 settlement to the multi-currency world without changing it: each
per-currency book settles its own obligations in its own currency (T+N calendar reused).
This module aggregates settlement obligations by currency and funds a cross-currency
obligation by converting from a funding currency before the settlement date. Failed FX
funding (no rate available) surfaces as an exception the caller turns into a failed
settlement.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.fx.currency import validate_code
from mentisrex.research.fx.models import SettlementCurrencyReport


def settlement_by_currency(book, *, as_of: date | None = None) -> SettlementCurrencyReport:
    by: dict = {}
    total_pending_base = 0.0
    for ccy, eng in book.books.items():
        rep = eng.settlement.report(as_of)
        by[ccy] = {
            "pending": rep.n_pending,
            "completed": rep.n_completed,
            "failed": rep.n_failed,
            "pending_cash": rep.pending_cash,
            "exposure": rep.settlement_exposure,
        }
        total_pending_base += abs(rep.pending_cash) * book.base_rate(ccy, as_of)
    return SettlementCurrencyReport(
        base_currency=book.base_currency, by_currency=by, total_pending_base=total_pending_base
    )


def obligations_by_currency(book) -> dict:
    """Net cash owed(−)/due(+) per (currency, settle_date) from pending instructions."""
    out: dict = {}
    for ccy, eng in book.books.items():
        for inst in eng.settlement.pending():
            out[(ccy, inst.settle_date)] = out.get((ccy, inst.settle_date), 0.0) + inst.cash_amount
    return out


def fund_settlement(
    book, currency: str, trade_id: str, from_currency: str, *, when: date | None = None
):
    """Convert exactly the pending outflow obligation for `trade_id` (settling in
    `currency`) out of `from_currency`. Raises if the rate is unavailable → caller fails
    the settlement (failed FX funding)."""
    currency = validate_code(currency)
    eng = book.books[currency]
    inst = eng.settlement.instructions.get(f"S-{trade_id}")
    if inst is None:
        raise ValueError(f"no settlement instruction for trade {trade_id} in {currency}")
    if inst.cash_amount >= 0:
        return None  # net inflow — nothing to fund
    return book.convert(
        needed_to=abs(inst.cash_amount),
        from_currency=from_currency,
        to_currency=currency,
        when=when,
        reason="settlement_funding",
    )
