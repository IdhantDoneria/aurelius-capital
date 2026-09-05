"""Multi-currency valuation (AIDP M16).

Values each per-currency book in its own (local) numeraire from the reused M11 book,
then translates to the base currency at an explicit as-of FX rate. Every valuation names
its valuation date, price marks (optional), and rate source — no implicit conversion.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.fx.models import CurrencyValuation, MultiCurrencyPortfolioValue


def valuation(
    book, *, as_of: date | None = None, prices: dict | None = None
) -> MultiCurrencyPortfolioValue:
    if prices:
        book.mark(prices)
    src = getattr(book.provider, "source", "provider")
    by: dict = {}
    total_base = cash_base = pos_base = 0.0
    for ccy in book.currencies():
        eng = book.books[ccy]
        cash_local = eng.accounting.cash
        pos_local = eng.accounting.state.positions_value()
        total_local = cash_local + pos_local
        rate = book.base_rate(ccy, as_of)
        tb = total_local * rate
        by[ccy] = CurrencyValuation(
            currency=ccy,
            cash_local=cash_local,
            positions_local=pos_local,
            total_local=total_local,
            fx_rate_to_base=rate,
            total_base=tb,
            as_of=as_of,
            rate_source=src,
        )
        total_base += tb
        cash_base += cash_local * rate
        pos_base += pos_local * rate
    return MultiCurrencyPortfolioValue(
        base_currency=book.base_currency,
        as_of=as_of,
        by_currency=by,
        total_base=total_base,
        cash_base=cash_base,
        positions_base=pos_base,
    )


def base_value(book, *, as_of: date | None = None, prices: dict | None = None) -> float:
    return valuation(book, as_of=as_of, prices=prices).total_base
