"""Instrument economics — the one place a fill turns into cash (AIDP M17).

Keyed on `CashConvention`, so no asset class re-derives it. `trade_cash` and
`position_value` are pure functions of the instrument + numbers; everything downstream
(book, valuation, margin, settlement) calls through here instead of assuming shares.
"""

from __future__ import annotations

from mentisrex.research.instruments.models import CashConvention, Instrument


def trade_cash(inst: Instrument, quantity: float, price: float, cost: float = 0.0) -> float:
    """Signed cash impact of executing `quantity` at `price` (buy negative, sell positive).

    PRINCIPAL — notional changes hands (equity buy pays, option long pays premium,
                bond buy pays principal). MARGINED — only the explicit `cost` moves now;
                economic P&L arrives later as variation margin. NPV — same, valued by a
                provider; nothing but cost settles at inception.
    """
    if inst.cash_convention is CashConvention.PRINCIPAL:
        return -(quantity * price * inst.contract_size) - cost
    return -cost


def position_value(inst: Instrument, quantity: float, mark: float) -> float:
    """Market value of a signed position at `mark` (per-unit price / NPV per contract)."""
    return quantity * mark * inst.contract_size


def unrealized_pnl(inst: Instrument, quantity: float, avg_price: float, mark: float) -> float:
    return (mark - avg_price) * quantity * inst.contract_size
