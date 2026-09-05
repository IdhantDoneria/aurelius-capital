"""Collateral tracking (AIDP M17).

Cash and security collateral with per-asset haircuts, currency-tagged. Post-haircut value
feeds the margin engine (is posted collateral enough to cover maintenance?). FX impact is
via M16: a collateral balance in a non-base currency converts through the injected FX
provider.
"""

from __future__ import annotations

from mentisrex.research.instruments.models import CollateralBalance


def post(
    cash: float = 0.0, securities: float = 0.0, *, haircut: float = 0.0, currency: str = "USD"
) -> CollateralBalance:
    if not 0.0 <= haircut < 1.0:
        raise ValueError(f"haircut must be in [0,1), got {haircut}")
    return CollateralBalance(cash=cash, securities=securities, haircut=haircut, currency=currency)


def covers(balance: CollateralBalance, requirement: float) -> bool:
    return balance.value + 1e-9 >= requirement


def base_value(balance: CollateralBalance, base_currency: str, fx_provider=None) -> float:
    """Post-haircut collateral value in `base_currency` (M16 conversion when needed)."""
    if balance.currency == base_currency:
        return balance.value
    if fx_provider is None:
        raise ValueError(
            f"need fx_provider to value {balance.currency} collateral in {base_currency}"
        )
    return balance.value * fx_provider.rate(balance.currency, base_currency)
