"""Tax framework (AIDP M15) — interfaces only, no country-specific logic.

Tax-lot tracking (FIFO), holding-period classification, and realized capital-gain
computation, plus a `JurisdictionRule` interface for country rules. No rates, no
brackets, no wash-sale or country specifics — those are jurisdiction plug-ins. Lots
are built from the trade event stream, so they are replayable and point-in-time safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TaxLot:
    security_id: str
    shares: float
    cost_basis: float
    opened: date | None


@dataclass(frozen=True)
class RealizedGain:
    security_id: str
    shares: float
    proceeds: float
    cost: float
    gain: float
    holding_days: int | None
    category: str  # from the jurisdiction rule


class JurisdictionRule:
    """Interface for country/holding-period classification. Default splits at 365 days;
    concrete jurisdictions override `classify` (and, in a real system, rates)."""

    long_term_days = 365

    def classify(self, holding_days: int | None) -> str:
        if holding_days is None:
            return "unknown"
        return "long_term" if holding_days >= self.long_term_days else "short_term"


class TaxLotBook:
    """FIFO tax-lot tracker. `buy` opens a lot; `sell` closes lots oldest-first and
    returns the realized gains with holding-period category."""

    def __init__(self, rule: JurisdictionRule | None = None) -> None:
        self.rule = rule or JurisdictionRule()
        self.lots: dict = {}  # security_id -> list[TaxLot] (FIFO)
        self.realized: list = []  # list[RealizedGain]

    def apply_trade(
        self, security_id: str, quantity: float, price: float, *, when: date | None = None
    ) -> list:
        return (
            self.buy(security_id, quantity, price, when=when)
            if quantity > 0
            else self.sell(security_id, -quantity, price, when=when)
        )

    def buy(
        self, security_id: str, shares: float, price: float, *, when: date | None = None
    ) -> list:
        self.lots.setdefault(security_id, []).append(TaxLot(security_id, shares, price, when))
        return []

    def sell(
        self, security_id: str, shares: float, price: float, *, when: date | None = None
    ) -> list:
        remaining = shares
        gains: list = []
        lots = self.lots.get(security_id, [])
        while remaining > 1e-12 and lots:
            lot = lots[0]
            take = min(lot.shares, remaining)
            proceeds = take * price
            cost = take * lot.cost_basis
            days = (when - lot.opened).days if (when and lot.opened) else None
            g = RealizedGain(
                security_id, take, proceeds, cost, proceeds - cost, days, self.rule.classify(days)
            )
            gains.append(g)
            self.realized.append(g)
            remaining -= take
            if take >= lot.shares - 1e-12:
                lots.pop(0)
            else:
                lots[0] = TaxLot(security_id, lot.shares - take, lot.cost_basis, lot.opened)
        return gains

    def open_lots(self, security_id: str | None = None) -> list:
        if security_id is not None:
            return list(self.lots.get(security_id, []))
        return [lot for lots in self.lots.values() for lot in lots]

    def realized_summary(self) -> dict:
        out: dict = {}
        for g in self.realized:
            out[g.category] = out.get(g.category, 0.0) + g.gain
        return out


def build_from_engine(engine, rule: JurisdictionRule | None = None) -> TaxLotBook:
    """Replay an engine's trade events into a tax-lot book (FIFO)."""
    book = TaxLotBook(rule)
    from mentisrex.research.post_trade.models import TradeEvent

    for e in sorted(engine.log.of_type(TradeEvent), key=lambda x: x.seq):
        book.apply_trade(e.security_id, e.quantity, e.price, when=e.trade_date)
    return book
