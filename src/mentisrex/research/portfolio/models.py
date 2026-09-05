"""Portfolio data models (AIDP M10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class PortfolioPosition:
    security_id: str
    weight: float  # final target weight (fraction of capital)
    shares: float = 0.0
    price: float | None = None
    market_value: float = 0.0
    target_weight: float = 0.0  # optimizer output before rounding to shares
    current_weight: float = 0.0  # weight held before this rebalance

    def to_dict(self) -> dict:
        return {
            "security_id": self.security_id,
            "weight": self.weight,
            "shares": self.shares,
            "price": self.price,
            "market_value": self.market_value,
            "target_weight": self.target_weight,
            "current_weight": self.current_weight,
        }


@dataclass
class Portfolio:
    date: date | None
    positions: list[PortfolioPosition]
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    turnover: float = 0.0
    cash: float = 0.0
    expected_return: float = 0.0
    expected_risk: float = 0.0
    metadata: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)

    @property
    def weights(self) -> dict[str, float]:
        return {p.security_id: p.weight for p in self.positions}

    @property
    def n_positions(self) -> int:
        return sum(1 for p in self.positions if abs(p.weight) > 1e-12)

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat() if self.date else None,
            "positions": [p.to_dict() for p in self.positions],
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "turnover": self.turnover,
            "cash": self.cash,
            "expected_return": self.expected_return,
            "expected_risk": self.expected_risk,
            "metadata": self.metadata,
            "diagnostics": self.diagnostics,
        }
