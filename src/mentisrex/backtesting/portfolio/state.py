"""PortfolioState — the complete, current state of the portfolio.

Mutable: updated in-place after every fill and mark-to-market.
Strategy reads this through StrategyContext (read-only view).

Leverage definitions:
  gross_leverage = sum(abs(market_value)) / total_value
  net_leverage   = sum(market_value) / total_value

For long-only strategies, gross = net. For long-short, they diverge.
"""

from decimal import Decimal

from mentisrex.backtesting.portfolio.position import Position


class PortfolioState:
    def __init__(self, initial_cash: Decimal) -> None:
        self._cash = initial_cash
        self._initial_capital = initial_cash
        self._positions: dict[str, Position] = {}
        self._peak_value: Decimal = initial_cash

    # ── cash ────────────────────────────────────────────────────────────────

    @property
    def cash(self) -> Decimal:
        return self._cash

    def debit(self, amount: Decimal) -> None:
        self._cash -= amount

    def credit(self, amount: Decimal) -> None:
        self._cash += amount

    # ── positions ────────────────────────────────────────────────────────────

    def position(self, symbol: str) -> Position:
        if symbol not in self._positions:
            self._positions[symbol] = Position(symbol=symbol)
        return self._positions[symbol]

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    @property
    def open_positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._positions.items() if not p.is_flat}

    # ── aggregate metrics ────────────────────────────────────────────────────

    @property
    def total_market_value(self) -> Decimal:
        return sum(p.market_value for p in self._positions.values())

    @property
    def total_value(self) -> Decimal:
        return self._cash + self.total_market_value

    @property
    def unrealized_pnl(self) -> Decimal:
        return sum(p.unrealized_pnl for p in self._positions.values())

    @property
    def realized_pnl(self) -> Decimal:
        return sum(p.realized_pnl for p in self._positions.values())

    @property
    def total_pnl(self) -> Decimal:
        return self.total_value - self._initial_capital

    @property
    def gross_exposure(self) -> Decimal:
        return sum(abs(p.market_value) for p in self._positions.values())

    @property
    def net_exposure(self) -> Decimal:
        return sum(p.market_value for p in self._positions.values())

    @property
    def gross_leverage(self) -> Decimal:
        nav = self.total_value
        if nav <= 0:
            return Decimal("0")
        return self.gross_exposure / nav

    @property
    def net_leverage(self) -> Decimal:
        nav = self.total_value
        if nav <= 0:
            return Decimal("0")
        return self.net_exposure / nav

    @property
    def drawdown(self) -> Decimal:
        """Current drawdown from peak NAV. 0.0 = at peak, -0.20 = 20% below peak."""
        current = self.total_value
        if current > self._peak_value:
            self._peak_value = current
        if self._peak_value <= 0:
            return Decimal("0")
        return (current - self._peak_value) / self._peak_value

    def update_peak(self) -> None:
        """Call after each bar to track high-water mark."""
        current = self.total_value
        if current > self._peak_value:
            self._peak_value = current

    def last_price(self, symbol: str) -> Decimal:
        pos = self._positions.get(symbol)
        return pos.last_price if pos else Decimal("0")

    def snapshot(self) -> dict:
        """Lightweight snapshot for equity curve recording."""
        return {
            "cash": self._cash,
            "total_value": self.total_value,
            "gross_leverage": self.gross_leverage,
            "net_leverage": self.net_leverage,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "drawdown": self.drawdown,
        }
