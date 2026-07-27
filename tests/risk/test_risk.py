"""Phase-7 risk tests: every rule gates, approve/modify/reject/shutdown, stress."""

from __future__ import annotations

from decimal import Decimal

from aurelius.backtesting.portfolio.state import PortfolioState
from aurelius.risk import (
    OrderContext,
    PortfolioRiskMonitor,
    RiskDecision,
    RiskEngine,
    RiskLimits,
    StressTester,
)


def _state(cash="1000000") -> PortfolioState:
    return PortfolioState(Decimal(cash))


def _priced(state, sym, price, qty=Decimal("0")):
    """Prime a position at (price, qty) and debit cash for its cost, so NAV is real."""
    price = Decimal(str(price))
    p = state.position(sym)
    p.last_price = price
    p.quantity = qty
    p.avg_cost = price
    state.debit(qty * price)
    return p


# ── approve / modify / reject ─────────────────────────────────────────────────


def test_small_order_approved():
    s = _state()
    _priced(s, "AAA", 100)
    ctx = OrderContext("AAA", Decimal("100"), Decimal("500"), is_buy=True)
    assert RiskEngine().evaluate(ctx, s).decision is RiskDecision.APPROVE


def test_position_size_modifies_down():
    s = _state()
    _priced(s, "AAA", 100)
    # 2500 sh * 100 = 250k = 25% NAV; cap 10% -> 1000 sh.
    ctx = OrderContext("AAA", Decimal("100"), Decimal("2500"), is_buy=True)
    v = RiskEngine().evaluate(ctx, s)
    assert v.decision is RiskDecision.MODIFY
    assert v.modified_quantity == Decimal("1000")


def test_liquidity_cap_modifies_down():
    s = _state()
    _priced(s, "AAA", 10)
    # 20% of 3000 ADV = 600 shares max.
    ctx = OrderContext("AAA", Decimal("10"), Decimal("5000"), is_buy=True, adv=Decimal("3000"))
    v = RiskEngine().evaluate(ctx, s)
    assert v.decision is RiskDecision.MODIFY
    assert v.modified_quantity == Decimal("600")


def test_stop_loss_budget_modifies_down():
    s = _state()
    _priced(s, "AAA", 100)
    # loss-to-stop = 10/sh; budget 2% NAV = 20k -> max 2000 sh, but 10% pos cap = 1000 wins.
    ctx = OrderContext(
        "AAA", Decimal("100"), Decimal("5000"), is_buy=True, stop_price=Decimal("90")
    )
    v = RiskEngine().evaluate(ctx, s)
    assert v.decision is RiskDecision.MODIFY
    assert v.modified_quantity == Decimal("1000")


def test_tightest_cap_wins():
    s = _state()
    _priced(s, "AAA", 100)
    # position cap 1000, liquidity cap 20%*4000=800 -> 800 binds.
    ctx = OrderContext("AAA", Decimal("100"), Decimal("5000"), is_buy=True, adv=Decimal("4000"))
    v = RiskEngine().evaluate(ctx, s)
    assert v.modified_quantity == Decimal("800")


def test_reducing_trade_bypasses_size_caps():
    s = _state()
    _priced(s, "AAA", 100, qty=Decimal("2000"))  # already oversized long
    ctx = OrderContext("AAA", Decimal("100"), Decimal("2000"), is_buy=False)
    assert RiskEngine().evaluate(ctx, s).decision is RiskDecision.APPROVE


# ── concentration = per-name size cap (clamps to 10% NAV) ─────────────────────


def test_name_concentration_clamped_to_cap():
    s = _state()
    _priced(s, "AAA", 100, qty=Decimal("900"))  # 90k existing = 9% NAV
    # add 200 more -> 110k = 11% NAV; cap 10% -> only 100 more shares allowed.
    ctx = OrderContext("AAA", Decimal("100"), Decimal("200"), is_buy=True)
    v = RiskEngine().evaluate(ctx, s)
    assert v.decision is RiskDecision.MODIFY
    assert v.modified_quantity == Decimal("100")  # 10% NAV cap - existing 9% -> 100 sh


# ── daily loss + emergency shutdown ───────────────────────────────────────────


def test_daily_loss_trips_kill_switch():
    s = _state()
    _priced(s, "AAA", 100)
    eng = RiskEngine()
    ctx = OrderContext(
        "AAA",
        Decimal("100"),
        Decimal("10"),
        is_buy=True,
        daily_pnl=Decimal("-40000"),
        sod_equity=Decimal("1000000"),
    )
    assert eng.evaluate(ctx, s).decision is RiskDecision.REJECT
    assert eng.is_halted
    # everything rejected while halted
    clean = OrderContext("AAA", Decimal("100"), Decimal("1"), is_buy=True)
    assert eng.evaluate(clean, s).decision is RiskDecision.REJECT
    eng.reset()
    assert not eng.is_halted
    assert eng.evaluate(clean, s).decision is RiskDecision.APPROVE


def test_drawdown_halt():
    s = PortfolioState(Decimal("1000000"))
    # force a peak then a 25% drop
    s._peak_value = Decimal("1000000")
    s.debit(Decimal("250000"))  # NAV now 750k -> -25% dd
    _priced(s, "AAA", 100)
    eng = RiskEngine()
    ctx = OrderContext("AAA", Decimal("100"), Decimal("1"), is_buy=True)
    assert eng.evaluate(ctx, s).decision is RiskDecision.REJECT
    assert eng.is_halted


# ── monitoring ────────────────────────────────────────────────────────────────


def test_monitor_volatility_and_var():
    s = _state()
    _priced(s, "AAA", 100, qty=Decimal("1000"))
    rep = PortfolioRiskMonitor().assess(s, [0.01, -0.01, 0.02, -0.02, 0.015, -0.015])
    assert rep.annualized_volatility > 0
    assert rep.value_at_risk > 0


def test_monitor_sector_and_hhi_breach():
    s = _state()
    _priced(s, "AAA", 100, qty=Decimal("1000"))  # single name -> HHI 1.0
    lim = RiskLimits(max_sector_pct=Decimal("0.30"))
    rep = PortfolioRiskMonitor(lim).assess(s, [0.01, -0.01, 0.01], sector_map={"AAA": "TECH"})
    assert rep.sector_exposure["TECH"] == 1.0
    assert rep.herfindahl == 1.0
    assert any("HHI" in b for b in rep.breaches)
    assert any("TECH" in b for b in rep.breaches)


def test_monitor_correlation_and_beta():
    s = _state()
    _priced(s, "AAA", 100, qty=Decimal("500"))
    _priced(s, "BBB", 100, qty=Decimal("500"))
    rets = {"AAA": [0.01, 0.02, -0.01, 0.03], "BBB": [0.01, 0.02, -0.01, 0.03]}
    rep = PortfolioRiskMonitor().assess(
        s, [0.01, -0.01, 0.01], symbol_returns=rets, betas={"AAA": 1.2, "BBB": 0.8}
    )
    assert abs(rep.avg_pairwise_correlation - 1.0) < 1e-9  # identical series
    assert abs(rep.portfolio_beta - 1.0) < 1e-9  # equal-weight (1.2+0.8)/2


# ── stress testing ────────────────────────────────────────────────────────────


def test_stress_market_crash():
    s = _state()
    _priced(s, "AAA", 100, qty=Decimal("5000"))  # 500k long
    r = StressTester().market_crash(s, shock=-0.20)
    assert r.pnl == -100000.0  # 20% of 500k
    assert r.scenario.startswith("market_crash")


def test_stress_vol_spike_var_scales():
    s = _state()
    _priced(s, "AAA", 100, qty=Decimal("1000"))
    r = StressTester().volatility_spike(s, daily_vol=0.01, k=3.0)
    # VaR = 1.6449 * 0.03 * NAV
    assert abs(r.stressed_var - 1.6449 * 0.03 * float(s.total_value)) < 1.0


def test_stress_liquidity_horizon():
    s = _state()
    _priced(s, "AAA", 100, qty=Decimal("12000"))
    # cap = 20% * 30% * 10000 = 600/day -> 20 days.
    r = StressTester().liquidity_reduction(s, adv={"AAA": Decimal("10000")}, f=0.30)
    assert abs(r.liquidation_days - 20.0) < 1e-9


def test_demo_self_check():
    from aurelius.risk import demo

    demo()
