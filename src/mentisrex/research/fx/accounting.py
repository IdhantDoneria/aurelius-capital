"""Currency-aware accounting views (AIDP M16).

An explicit currency-aware *adapter* over the reused per-currency M11 books — it does
not duplicate M11 position accounting. It reads M11's local quantity / cost basis /
realized / unrealized P&L and translates to the base currency at an explicit as-of rate,
and rolls up base realized P&L plus the book's FX realized result.
"""

from __future__ import annotations

from datetime import date


def position_accounting(book, security_id: str, *, as_of: date | None = None) -> dict | None:
    ccy = book.security_currency.get(security_id)
    if ccy is None:
        return None
    rate = book.base_rate(ccy, as_of)
    h = book.books[ccy].accounting.state.holdings.get(security_id)
    if h is None:
        return {"security_id": security_id, "currency": ccy, "shares": 0.0,
                "local_cost_basis": 0.0, "local_price": 0.0, "local_realized_pnl": 0.0,
                "local_unrealized_pnl": 0.0, "base_cost_basis": 0.0, "base_market_value": 0.0,
                "base_unrealized_pnl": 0.0, "fx_rate_to_base": rate}
    return {
        "security_id": security_id, "currency": ccy, "shares": h.shares,
        "local_cost_basis": h.cost_basis, "local_price": h.price,
        "local_realized_pnl": h.realized_pnl, "local_unrealized_pnl": h.unrealized_pnl,
        "base_cost_basis": h.cost_basis * rate, "base_market_value": h.market_value * rate,
        "base_unrealized_pnl": h.unrealized_pnl * rate, "fx_rate_to_base": rate}


def base_realized_pnl(book, *, as_of: date | None = None) -> float:
    """Σ per-currency local realized P&L translated to base + FX realized on conversions."""
    total = sum(eng.accounting.realized_pnl() * book.base_rate(ccy, as_of)
                for ccy, eng in book.books.items())
    return total + book.realized_fx_pnl


def base_unrealized_pnl(book, *, as_of: date | None = None) -> float:
    return sum(eng.accounting.unrealized_pnl() * book.base_rate(ccy, as_of)
               for ccy, eng in book.books.items())
