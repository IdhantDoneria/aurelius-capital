"""Transaction cost models.

Every real trade has at least three cost components:
1. Commission: the explicit fee paid to the broker/exchange.
2. Bid-ask spread: the implicit cost of immediacy — you buy at ask, sell at bid.
3. Market impact: your order moves the price against you.

A strategy that is profitable ignoring these costs but unprofitable with them
is NOT a viable strategy. These models must be calibrated to realistic values.

Defaults are conservative institutional estimates for US equities (2024):
  Commission: 1 basis point (~$0.001/share for institutional broker)
  Spread: 5 basis points round-trip; 2.5bps each side (liquid large-caps)
  Slippage: 10bps at 100% ADV participation via square-root impact model

The square-root model (Almgren-Chriss, 2001) is the industry standard:
  impact_bps = k x sqrt(order_size / ADV)
where k is the impact coefficient (10bps at 100% participation by default).

For orders with unknown ADV, we use a fixed 5bps slippage as fallback.
"""

import math
from decimal import Decimal


class CommissionModel:
    """Flat percentage of notional. Configurable."""

    def __init__(self, rate: Decimal = Decimal("0.0010")) -> None:
        self._rate = rate

    def compute(self, notional: Decimal) -> Decimal:
        return (notional * self._rate).quantize(Decimal("0.01"))


class SpreadModel:
    """Bid-ask spread cost. Buy pays ask (above mid), sell receives bid (below mid).

    The spread is expressed in basis points (1 bp = 0.0001).
    half_spread_bps: e.g., 5bps means buy at mid + 0.025%, sell at mid - 0.025%.

    We approximate mid ≈ open (at fill time). This is conservative.
    """

    def __init__(self, half_spread_bps: Decimal = Decimal("5")) -> None:
        self._half_spread = half_spread_bps / Decimal("10000")

    def adjusted_price(self, raw_price: Decimal, is_buy: bool) -> Decimal:
        """Return the all-in price after spread cost."""
        if is_buy:
            return raw_price * (1 + self._half_spread)
        return raw_price * (1 - self._half_spread)


class SlippageModel:
    """Square-root market impact model (Almgren-Chriss, 2001).

    impact_bps = k x sqrt(participation_rate)
    where participation_rate = order_shares / avg_daily_volume

    For large orders (>20% ADV), impact grows significantly. This is intentional:
    it penalizes strategies that require size disproportionate to liquidity.

    If ADV is unknown (volume=0 in bar), uses fixed fallback_bps.
    """

    def __init__(
        self,
        impact_coefficient_bps: Decimal = Decimal("10"),
        fallback_bps: Decimal = Decimal("5"),
    ) -> None:
        self._k = impact_coefficient_bps / Decimal("10000")
        self._fallback = fallback_bps / Decimal("10000")

    def compute_impact(
        self,
        order_shares: Decimal,
        avg_daily_volume: Decimal,
        price: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Return (slippage_bps, slippage_price_adjustment).

        slippage_price_adjustment: add to buy price, subtract from sell price.
        """
        if avg_daily_volume <= 0:
            impact_fraction = self._fallback
        else:
            participation = float(order_shares / avg_daily_volume)
            impact_fraction = self._k * Decimal(str(math.sqrt(participation)))

        return impact_fraction, price * impact_fraction
