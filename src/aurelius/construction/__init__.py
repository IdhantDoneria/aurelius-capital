"""Phase-8 portfolio construction: many weak signals -> one robust book.

    from aurelius.construction import PortfolioBuilder, Method, RawSignal, SignalSource

    builder = PortfolioBuilder(method=Method.RISK_PARITY)
    tp = builder.build(signals, returns, prices, state, sector_map)
    # tp.orders are risk-screened OrderEvents ready for execution.

The objective is combination, not a single edge: aggregate -> size -> optimize
-> exposure overlay -> risk screen -> orders.
"""

from aurelius.construction.aggregation import RawSignal, SignalAggregator, SignalSource
from aurelius.construction.builder import Method, PortfolioBuilder, TargetPortfolio
from aurelius.construction.exposure import ExposureLimits, apply_limits
from aurelius.construction.optimize import (
    condition_number,
    constrained_min_variance,
    max_sharpe,
    min_variance,
    sample_covariance,
)
from aurelius.construction.sizing import equal_weight, risk_parity, volatility_target

__all__ = [
    "ExposureLimits",
    "Method",
    "PortfolioBuilder",
    "RawSignal",
    "SignalAggregator",
    "SignalSource",
    "TargetPortfolio",
    "apply_limits",
    "condition_number",
    "constrained_min_variance",
    "demo",
    "equal_weight",
    "max_sharpe",
    "min_variance",
    "risk_parity",
    "sample_covariance",
    "volatility_target",
]


def demo() -> TargetPortfolio:
    """Combine four sources over three names, build a risk-parity book, screen it."""
    import random
    from decimal import Decimal

    from aurelius.backtesting.portfolio.state import PortfolioState

    rnd = random.Random(7)
    universe = ["AAA", "BBB", "CCC"]
    # Synthetic weakly-correlated daily returns per name.
    returns = {s: [rnd.gauss(0.0004, 0.012) for _ in range(252)] for s in universe}
    prices = {s: Decimal("100") for s in universe}
    sectors = {"AAA": "TECH", "BBB": "TECH", "CCC": "FIN"}

    signals = [
        RawSignal("AAA", SignalSource.MOMENTUM, 1.2),
        RawSignal("BBB", SignalSource.MOMENTUM, -0.4),
        RawSignal("CCC", SignalSource.MOMENTUM, 0.1),
        RawSignal("AAA", SignalSource.MEAN_REVERSION, -0.3),
        RawSignal("BBB", SignalSource.MEAN_REVERSION, 0.9),
        RawSignal("CCC", SignalSource.MEAN_REVERSION, 0.2),
        RawSignal("AAA", SignalSource.ML, 0.5),
        RawSignal("BBB", SignalSource.ML, 0.2),
        RawSignal("CCC", SignalSource.ML, 0.8),
    ]

    state = PortfolioState(Decimal("1_000_000"))
    for s in universe:
        state.position(s).last_price = Decimal("100")

    builder = PortfolioBuilder(method=Method.RISK_PARITY)
    tp = builder.build(signals, returns, prices, state, sector_map=sectors)

    # Risk parity => roughly-equal risk => weights should be positive and sum ~1 gross.
    gross = sum(abs(w) for w in tp.weights.values())
    assert 0 < gross <= 1.0 + 1e-6
    assert tp.orders, "expected at least one screened order"
    print("construction demo ok:",
          {s: round(w, 3) for s, w in tp.weights.items()},
          f"orders={len(tp.orders)}")
    return tp


if __name__ == "__main__":
    demo()
