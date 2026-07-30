"""Phase-7 risk management: the gate between strategy and execution.

    from aurelius.risk import RiskEngine, OrderContext, RiskDecision

    engine = RiskEngine()                     # default institutional limits
    verdict = engine.evaluate(ctx, state)     # APPROVE / MODIFY / REJECT
    if verdict.decision is RiskDecision.MODIFY:
        order.quantity = verdict.modified_quantity

Capital preservation first: no order reaches execution without a verdict.
"""

from aurelius.risk.engine import OrderContext, RiskEngine
from aurelius.risk.models import (
    RiskDecision,
    RiskLimits,
    RiskReport,
    RiskVerdict,
    StressResult,
)
from aurelius.risk.monitor import PortfolioRiskMonitor
from aurelius.risk.stress import StressTester

__all__ = [
    "OrderContext",
    "PortfolioRiskMonitor",
    "RiskDecision",
    "RiskEngine",
    "RiskLimits",
    "RiskReport",
    "RiskVerdict",
    "StressResult",
    "StressTester",
]


def demo() -> None:
    """One walk through all four subsystems with asserts — the runnable check."""
    from decimal import Decimal

    from aurelius.backtesting.portfolio.state import PortfolioState

    state = PortfolioState(Decimal("1_000_000"))
    engine = RiskEngine()

    # APPROVE: a 5% buy under every cap.
    p = state.position("AAA")
    p.last_price = Decimal("100")
    ctx = OrderContext("AAA", Decimal("100"), Decimal("500"), is_buy=True, adv=Decimal("1_000_000"))
    assert engine.evaluate(ctx, state).decision is RiskDecision.APPROVE

    # MODIFY: order at 25% NAV clamped to the 10% position cap.
    big = OrderContext(
        "AAA", Decimal("100"), Decimal("2500"), is_buy=True, adv=Decimal("10_000_000")
    )
    v = engine.evaluate(big, state)
    assert v.decision is RiskDecision.MODIFY
    assert v.modified_quantity == Decimal("1000")

    # MODIFY: liquidity — 20% of a 3000-share ADV = 600 shares max.
    illiq = OrderContext("BBB", Decimal("50"), Decimal("5000"), is_buy=True, adv=Decimal("3000"))
    state.position("BBB").last_price = Decimal("50")
    assert engine.evaluate(illiq, state).modified_quantity == Decimal("600")

    # REJECT + kill switch: a -4% day trips the daily loss limit.
    loss = OrderContext(
        "AAA",
        Decimal("100"),
        Decimal("10"),
        is_buy=True,
        daily_pnl=Decimal("-40000"),
        sod_equity=Decimal("1_000_000"),
    )
    assert engine.evaluate(loss, state).decision is RiskDecision.REJECT
    assert engine.is_halted
    engine.reset()

    # Monitor: annualized vol of a flat 1%/day series.
    mon = PortfolioRiskMonitor()
    rep = mon.assess(state, [0.01, -0.01, 0.01, -0.01, 0.02, -0.02])
    assert rep.annualized_volatility > 0
    assert rep.value_at_risk >= 0

    # Stress: a -20% crash loses money on a net-long book.
    p.quantity = Decimal("1000")  # 1000 sh AAA @ 100 = 100k long
    st = StressTester()
    crash = st.market_crash(state, shock=-0.20)
    assert crash.pnl < 0
    print("risk demo ok:", crash.detail)


if __name__ == "__main__":
    demo()
