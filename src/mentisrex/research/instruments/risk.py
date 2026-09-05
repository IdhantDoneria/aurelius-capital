"""Risk integration (AIDP M17).

Feeds instrument sensitivities INTO M13 — it does not re-implement VaR, covariance, or
limits. Aggregates the book's positions into the exposures M13 consumes: notional, delta,
gamma, vega, duration, margin, leverage. Greeks come from an injected `GreeksProvider`
(never hard-coded), so an equity-only book reports pure notional/delta and everything else
zero — identical risk to pre-M17.
"""

from __future__ import annotations

from dataclasses import dataclass

from mentisrex.research.instruments.models import Greeks, InstrumentType


@dataclass(frozen=True)
class InstrumentRiskReport:
    notional: float = 0.0
    delta: float = 0.0  # $ delta (position delta * contract * mark scaling folded in)
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    rho: float = 0.0
    duration: float = 0.0  # $ duration for fixed income
    margin: float = 0.0
    equity_value: float = 0.0  # cash + collateral backing the book

    @property
    def leverage(self) -> float:
        return self.notional / self.equity_value if self.equity_value > 0 else 0.0


def exposures(
    book, marks: dict, *, greeks_provider=None, market: dict | None = None, yield_provider=None
) -> InstrumentRiskReport:
    """Aggregate book-wide sensitivities. `market` maps instrument_id -> pricing inputs
    (spot/vol/rate/t) for the Greeks/yield providers; `marks` are per-unit marks."""
    market = market or {}
    notional = delta = gamma = vega = theta = rho = duration = margin = 0.0

    # equities in the reused M11 state: linear, delta == market value, no greeks
    state = book.engine.accounting.state
    for _sid, h in state.holdings.items():
        notional += abs(h.market_value)
        delta += h.market_value

    for iid, pos in book.positions.items():
        if pos.quantity == 0:
            continue
        inst = book.registry.get(iid)
        mark = marks.get(iid, pos.last_mark)
        cs, qty = inst.contract_size, pos.quantity
        notional += abs(qty) * mark * cs
        margin += pos.margin
        if inst.type is InstrumentType.OPTION and greeks_provider is not None:
            g: Greeks = greeks_provider.greeks(inst, market.get(iid, {}))
            scale = qty * cs
            delta += g.delta * scale * mark  # $ delta
            gamma += g.gamma * scale
            vega += g.vega * scale
            theta += g.theta * scale
            rho += g.rho * scale
        elif inst.type is InstrumentType.BOND and yield_provider is not None:
            duration += yield_provider.duration(inst, mark) * abs(qty) * mark * cs
            delta += qty * mark * cs
        else:  # future/forward/swap: linear delta
            delta += qty * mark * cs

    equity_value = book.cash + sum(c.value for c in book.collateral.values())
    return InstrumentRiskReport(
        notional, delta, gamma, vega, theta, rho, duration, margin, equity_value
    )


def to_m13_inputs(report: InstrumentRiskReport) -> dict:
    """Shape the report as the sensitivity dict the M13 risk engine reads."""
    return {
        "gross_notional": report.notional,
        "net_delta": report.delta,
        "gamma": report.gamma,
        "vega": report.vega,
        "duration": report.duration,
        "margin": report.margin,
        "leverage": report.leverage,
    }
