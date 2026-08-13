"""Multi-currency cash view (AIDP M16).

Currencies are never collapsed into one number internally — each per-currency book keeps
its own settlement-aware `CashLedger` (M15). This module reads those ledgers into a
per-currency `CurrencyBalance` set and, only for reporting, a base-translated total.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.fx.models import CurrencyBalance, MultiCurrencyCash


def currency_balances(book) -> dict:
    out: dict = {}
    for ccy, eng in book.books.items():
        cl = eng.cash_ledger
        out[ccy] = CurrencyBalance(
            currency=ccy, economic=cl.economic_balance(), settled=cl.settled_balance(),
            pending_in=cl.pending_inflows(), pending_out=cl.pending_outflows())
    return out


def multi_currency_cash(book, *, as_of: date | None = None) -> MultiCurrencyCash:
    bals = currency_balances(book)
    te = sum(b.economic * book.base_rate(c, as_of) for c, b in bals.items())
    ts = sum(b.settled * book.base_rate(c, as_of) for c, b in bals.items())
    return MultiCurrencyCash(base_currency=book.base_currency, balances=bals, as_of=as_of,
                             total_base_economic=te, total_base_settled=ts)
