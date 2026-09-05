"""AIDP M17 — Multi-Asset & Derivatives Accounting Engine tests.

Deterministic, offline. Covers the instrument model + registry, equity backward
compatibility (byte-identical to M15), futures accounting / margin / daily settlement /
roll, option lifecycle (premium, exercise, assignment, expiry, ITM/OTM), forwards, swaps,
fixed income, pricing/greeks/yield providers, margin & collateral, risk integration,
settlement, reconciliation, serialization/determinism, validation, diagnostics, failure
scenarios and edge cases.
"""

from __future__ import annotations

from datetime import date

import pytest

from mentisrex.research import instruments as ins
from mentisrex.research.instruments import (
    collateral,
    contracts,
    diagnostics,
    swaps,
)
from mentisrex.research.instruments import (
    exercise as ex,
)
from mentisrex.research.instruments import (
    expiry as exp,
)
from mentisrex.research.instruments import (
    fixed_income as fi,
)
from mentisrex.research.instruments import (
    instrument as econ,
)
from mentisrex.research.instruments import (
    margin as mg,
)
from mentisrex.research.instruments import (
    reconciliation as recon,
)
from mentisrex.research.instruments import (
    risk as rk,
)
from mentisrex.research.instruments import (
    serialization as ser,
)
from mentisrex.research.instruments import (
    settlement as stl,
)
from mentisrex.research.instruments import (
    validation as val,
)
from mentisrex.research.instruments import (
    valuation as vln,
)
from mentisrex.research.instruments.models import (
    CashConvention,
    ExerciseStatus,
    Greeks,
    InstrumentType,
    OptionRight,
    SettlementStyle,
)
from mentisrex.research.post_trade import PostTradeEngine
from mentisrex.research.post_trade import fingerprint as pt_fingerprint

D0 = date(2026, 1, 5)
DE = date(2026, 12, 18)
OE = date(2026, 3, 20)


def book(cap=1_000_000.0):
    return ins.InstrumentBook(cap)


def es_future(**kw):
    kw.setdefault("contract_size", 50)
    kw.setdefault("expiry", DE)
    kw.setdefault("initial_margin_rate", 0.05)
    kw.setdefault("maintenance_margin_rate", 0.04)
    return ins.future("ES", **kw)


# ─────────────────────────── instrument model ──────────────────────────────


def test_equity_factory_type():
    assert ins.equity("AAPL").type is InstrumentType.EQUITY


def test_equity_is_not_derivative():
    assert not ins.equity("AAPL").is_derivative


def test_future_is_derivative():
    assert es_future().is_derivative


def test_currency_normalized():
    assert ins.equity("X", currency="usd").currency == "USD"


def test_contract_size_must_be_positive():
    with pytest.raises(ValueError):
        ins.equity("X", contract_size=0)


def test_future_is_margined():
    assert es_future().cash_convention is CashConvention.MARGINED


def test_option_is_principal():
    assert (
        ins.call("C", underlying="U", strike=100, expiry=OE).cash_convention
        is CashConvention.PRINCIPAL
    )


def test_bond_contract_size_face_scaled():
    assert fi.bond("B", face=1000.0).contract_size == 10.0


def test_notional():
    assert es_future().notional(2, 4000.0) == 2 * 4000.0 * 50


def test_option_strike_required_positive():
    with pytest.raises(ValueError):
        ins.call("C", underlying="U", strike=-1, expiry=OE)


def test_call_right():
    assert ins.call("C", underlying="U", strike=1, expiry=OE).right is OptionRight.CALL


def test_put_right():
    assert ins.put("P", underlying="U", strike=1, expiry=OE).right is OptionRight.PUT


# ─────────────────────────── registry ──────────────────────────────────────


def test_registry_register_and_get():
    r = ins.InstrumentRegistry()
    e = r.register(ins.equity("AAPL"))
    assert r.get("AAPL") is e


def test_registry_unknown_raises():
    with pytest.raises(KeyError):
        ins.InstrumentRegistry().get("NOPE")


def test_registry_duplicate_different_raises():
    r = ins.InstrumentRegistry()
    r.register(ins.equity("X"))
    with pytest.raises(ValueError):
        r.register(ins.future("X", expiry=DE))


def test_registry_duplicate_same_ok():
    r = ins.InstrumentRegistry()
    r.register(ins.equity("X"))
    r.register(ins.equity("X"))
    assert len(r) == 1


def test_registry_of_type():
    r = ins.InstrumentRegistry()
    r.register(ins.equity("A"))
    r.register(es_future())
    assert [i.instrument_id for i in r.of_type(InstrumentType.FUTURE)] == ["ES"]


def test_registry_sorted_all():
    r = ins.InstrumentRegistry()
    r.register(ins.equity("Z"))
    r.register(ins.equity("A"))
    assert [i.instrument_id for i in r.all()] == ["A", "Z"]


def test_registry_contains():
    r = ins.InstrumentRegistry()
    r.register(ins.equity("A"))
    assert "A" in r


# ─────────────────── equity backward compatibility ─────────────────────────


def test_equity_cash_matches_manual():
    b = book()
    b.book_trade(ins.equity("AAPL"), 100, 150.0)
    assert b.cash == 1_000_000.0 - 15_000.0


def test_equity_delegates_to_m15_identically():
    # a bare PostTradeEngine and an InstrumentBook must agree on cash + positions
    eng = PostTradeEngine(1_000_000.0, session_id="x")
    eng.book_fill(security_id="AAPL", quantity=100, price=150.0, trade_date=D0)
    eng.book_fill(security_id="MSFT", quantity=50, price=300.0, trade_date=D0)
    b = ins.InstrumentBook(engine=PostTradeEngine(1_000_000.0, session_id="x"))
    b.book_trade(ins.equity("AAPL"), 100, 150.0, trade_date=D0)
    b.book_trade(ins.equity("MSFT"), 50, 300.0, trade_date=D0)
    assert b.cash == eng.accounting.cash
    assert pt_fingerprint(b.engine) == pt_fingerprint(eng)


def test_equity_position_in_m11_state_not_overlay():
    b = book()
    b.book_trade(ins.equity("AAPL"), 100, 150.0)
    assert "AAPL" in b.engine.accounting.state.holdings
    assert b.snapshot("AAPL") is None  # equities are not in the derivative overlay


def test_equity_mark_updates_m11_unrealized():
    b = book()
    b.book_trade(ins.equity("AAPL"), 100, 150.0)
    b.mark({"AAPL": 160.0})
    assert b.unrealized_pnl() == pytest.approx(1000.0)


def test_equity_realized_pnl():
    b = book()
    b.book_trade(ins.equity("AAPL"), 100, 150.0)
    b.book_trade(ins.equity("AAPL"), -100, 160.0)
    assert b.realized_pnl() == pytest.approx(1000.0)


def test_equity_only_book_is_valid():
    b = book()
    b.book_trade(ins.equity("AAPL"), 10, 100.0)
    assert val.is_valid(b)


# ─────────────────────────── futures ───────────────────────────────────────


def test_future_no_cash_at_trade_except_margin():
    b = book()
    b.book_trade(es_future(), 2, 4000.0)
    # only initial margin leaves cash: 2*4000*50*0.05 = 20000
    assert b.cash == 1_000_000.0 - 20_000.0


def test_future_initial_margin_posted():
    b = book()
    b.book_trade(es_future(), 2, 4000.0)
    assert b.margin_posted["ES"] == pytest.approx(20_000.0)


def test_future_variation_margin_cash():
    b = book()
    b.book_trade(es_future(), 2, 4000.0)
    c0 = b.cash
    vm = b.mark({"ES": 4010.0})
    assert vm["ES"] == pytest.approx(1000.0)
    # +1000 variation, margin re-posts up by 50 -> net +950
    assert b.cash == pytest.approx(c0 + 1000.0 - 50.0)


def test_future_daily_settlement_zero_unrealized():
    b = book()
    b.book_trade(es_future(), 2, 4000.0)
    b.mark({"ES": 4010.0})
    assert b.unrealized_pnl() == pytest.approx(0.0)
    assert b.realized_pnl() == pytest.approx(1000.0)


def test_future_short_variation_margin():
    b = book()
    b.book_trade(es_future(), -2, 4000.0)
    b.mark({"ES": 4010.0})
    assert b.realized_pnl() == pytest.approx(-1000.0)


def test_future_multiplier_applied():
    b = book()
    b.book_trade(ins.future("BIG", contract_size=1000, expiry=DE), 1, 10.0)
    b.mark({"BIG": 11.0})
    assert b.realized_pnl() == pytest.approx(1000.0)


def test_future_close_flat_position():
    b = book()
    f = es_future()
    b.book_trade(f, 2, 4000.0)
    b.mark({"ES": 4010.0})
    b.close(f, 4010.0)
    assert b.snapshot("ES").quantity == 0
    assert "ES" not in b.margin_posted


def test_future_roll_pair():
    front = ins.future("ESH", contract_size=50, expiry=date(2026, 3, 20))
    back = ins.future("ESM", contract_size=50, expiry=date(2026, 6, 19))
    close_f, open_b = ins.roll(front, back, 2, front_price=4000.0, back_price=4010.0)
    assert close_f["quantity"] == -2
    assert open_b["quantity"] == 2


def test_future_margin_requirement_calc():
    req = mg.requirement(es_future(), 2, 4000.0)
    assert req.initial == pytest.approx(20_000.0)
    assert req.maintenance == pytest.approx(16_000.0)


# ─────────────────────────── options ───────────────────────────────────────


def test_option_premium_paid_long():
    b = book()
    b.book_trade(ins.call("C", underlying="U", strike=150, expiry=OE), 1, 5.0)
    assert b.cash == 1_000_000.0 - 500.0  # 1 * 5 * 100


def test_option_premium_received_short():
    b = book()
    b.book_trade(ins.call("C", underlying="U", strike=150, expiry=OE), -1, 5.0)
    assert b.cash == 1_000_000.0 + 500.0


def test_option_intrinsic_call():
    from mentisrex.research.instruments.options import intrinsic_value

    c = ins.call("C", underlying="U", strike=150, expiry=OE)
    assert intrinsic_value(c, 170.0) == 20.0
    assert intrinsic_value(c, 140.0) == 0.0


def test_option_intrinsic_put():
    from mentisrex.research.instruments.options import intrinsic_value

    p = ins.put("P", underlying="U", strike=150, expiry=OE)
    assert intrinsic_value(p, 130.0) == 20.0
    assert intrinsic_value(p, 170.0) == 0.0


def test_option_exercise_itm_long():
    b = book()
    c = ins.call("C", underlying="U", strike=150, expiry=OE)
    b.book_trade(c, 1, 5.0)
    r = ex.exercise(b, c, 170.0)
    assert r.status is ExerciseStatus.EXERCISED
    assert r.cash == pytest.approx(2000.0)
    assert b.realized_pnl() == pytest.approx(1500.0)  # (20-5)*100


def test_option_assignment_itm_short():
    b = book()
    c = ins.call("C", underlying="U", strike=150, expiry=OE)
    b.book_trade(c, -1, 5.0)
    r = ex.exercise(b, c, 170.0)
    assert r.status is ExerciseStatus.ASSIGNED
    assert b.realized_pnl() == pytest.approx(-1500.0)


def test_option_expire_otm_worthless():
    b = book()
    c = ins.call("C", underlying="U", strike=150, expiry=OE)
    b.book_trade(c, 1, 5.0)
    r = ex.exercise(b, c, 140.0)
    assert r.status is ExerciseStatus.EXPIRED
    assert b.realized_pnl() == pytest.approx(-500.0)  # lost the premium
    assert "C" in b._closed


def test_option_closed_cannot_trade():
    b = book()
    c = ins.call("C", underlying="U", strike=150, expiry=OE)
    b.book_trade(c, 1, 5.0)
    ex.exercise(b, c, 170.0)
    with pytest.raises(ValueError):
        b.book_trade(c, 1, 5.0)


def test_option_physical_settlement_hands_off_underlying():
    b = book()
    c = ins.option(
        "C",
        underlying="AAPL",
        strike=150,
        expiry=OE,
        right="call",
        settlement_style=SettlementStyle.PHYSICAL,
    )
    b.book_trade(c, 1, 5.0)
    r = ex.exercise(b, c, 170.0)
    assert r.underlying_fill["security_id"] == "AAPL"
    assert r.underlying_fill["quantity"] == 100


def test_exercise_non_option_raises():
    b = book()
    with pytest.raises(ValueError):
        ex.exercise(b, es_future(), 4000.0)


# ─────────────────────────── expiry ────────────────────────────────────────


def test_expiry_future_settles_and_closes():
    b = book()
    f = es_future()
    b.book_trade(f, 2, 4000.0)
    exp.expire(b, f, 4020.0)
    assert b.snapshot("ES").quantity == 0
    assert "ES" in b._closed
    assert b.realized_pnl() == pytest.approx(2000.0)


def test_expiry_option_delegates_to_exercise():
    b = book()
    c = ins.call("C", underlying="U", strike=150, expiry=OE)
    b.book_trade(c, 1, 5.0)
    r = exp.expire(b, c, 170.0)
    assert r.status is ExerciseStatus.EXERCISED


def test_expiring_on_lists_matured():
    b = book()
    b.book_trade(ins.future("ES", contract_size=50, expiry=date(2026, 3, 20)), 1, 4000.0)
    assert "ES" in exp.expiring_on(b, date(2026, 3, 20))
    assert exp.expiring_on(b, date(2026, 1, 1)) == []


def test_is_expired_helper():
    assert contracts.is_expired(es_future(), date(2027, 1, 1))
    assert not contracts.is_expired(es_future(), D0)


def test_days_to_expiry():
    assert contracts.days_to_expiry(ins.future("ES", expiry=date(2026, 1, 15)), D0) == 10


# ─────────────────────────── forwards ──────────────────────────────────────


def test_forward_no_cash_at_trade():
    b = book()
    fwd = ins.forward("FWD", contract_size=1000, settlement_date=DE, forward_price=1.10)
    b.book_trade(fwd, 1, 1.10)
    assert b.cash == 1_000_000.0


def test_forward_mtm():
    b = book()
    fwd = ins.forward("FWD", contract_size=1000, settlement_date=DE)
    b.book_trade(fwd, 1, 1.10)
    b.mark({"FWD": 1.12})
    assert b.realized_pnl() == pytest.approx(1000 * 0.02)


def test_fx_forward_metadata():
    fwd = ins.fx_forward(
        "EURUSD", base="EUR", quote="USD", notional=1_000_000, forward_rate=1.10, settlement_date=DE
    )
    assert fwd.metadata["pair"] == "EUR/USD"
    assert fwd.currency == "USD"


# ─────────────────────────── swaps ─────────────────────────────────────────


def test_irs_construction():
    s = ins.interest_rate_swap("IRS", notional=10_000_000, fixed_rate=0.03)
    assert s.type is InstrumentType.SWAP
    assert len(s.metadata["legs"]) == 2


def test_swap_npv_convention():
    s = ins.interest_rate_swap("IRS", notional=1_000_000, fixed_rate=0.03)
    assert s.cash_convention is CashConvention.NPV


def test_swap_no_cash_at_trade():
    b = book()
    s = ins.interest_rate_swap("IRS", notional=1_000_000, fixed_rate=0.03)
    b.book_trade(s, 1, 0.0)
    assert b.cash == 1_000_000.0


def test_swap_cash_flows_via_provider():
    s = ins.interest_rate_swap("IRS", notional=1_000_000, fixed_rate=0.03)

    class P:
        def cash_flows(self, inst):
            return [swaps.CashFlow(DE, 5000.0, "USD", "float")]

    assert swaps.cash_flows(s, P())[0].amount == 5000.0


def test_swap_leg_pay_receive():
    s = ins.interest_rate_swap("IRS", notional=1_000_000, fixed_rate=0.03, pay_fixed=True)
    fixed = next(l for l in s.metadata["legs"] if l["kind"] == "fixed")
    assert fixed["pay"] is True


# ─────────────────────────── fixed income ──────────────────────────────────


def test_bond_principal_cash():
    b = book()
    bd = fi.bond("UST", face=1000.0, coupon=0.04, maturity=DE)
    b.book_trade(bd, 10, 99.0)  # 10 bonds, price 99 per 100, cs=10 -> 10*99*10=9900
    assert b.cash == pytest.approx(1_000_000.0 - 9900.0)


def test_bond_coupon_schedule_semiannual():
    bd = fi.bond("UST", coupon=0.04, maturity=date(2027, 1, 5), frequency=2)
    sched = fi.coupon_schedule(bd, issue=date(2026, 1, 5))
    assert sched[-1] == date(2027, 1, 5)
    assert len(sched) == 2


def test_bond_coupon_cash_flows():
    bd = fi.bond("UST", face=1000.0, coupon=0.04, maturity=date(2027, 1, 5), frequency=2)
    cfs = fi.coupon_cash_flows(bd, issue=date(2026, 1, 5), quantity=10)
    assert cfs[0][1] == pytest.approx(0.04 / 2 * 1000.0 * 10)


def test_bond_ytm_via_provider():
    bd = fi.bond("UST", coupon=0.04)
    assert fi.yield_to_maturity(bd, 100.0, ins.MockYieldProvider()) == pytest.approx(0.04)


def test_bond_duration_via_provider():
    bd = fi.bond("UST", face=1000.0)
    assert fi.duration(bd, 100.0, ins.MockYieldProvider()) == pytest.approx(10.0)


# ─────────────────── pricing / greeks / valuation ──────────────────────────


def test_black_scholes_call_positive():
    p = ins.BlackScholesPricer()
    c = ins.call("C", underlying="U", strike=100, expiry=OE)
    px = p.price(c, {"spot": 100.0, "vol": 0.2, "rate": 0.01, "t": 0.25})
    assert px > 0


def test_black_scholes_put_call_parity():
    p = ins.BlackScholesPricer()
    m = {"spot": 100.0, "vol": 0.2, "rate": 0.05, "t": 1.0}
    c = ins.call("C", underlying="U", strike=100, expiry=OE)
    pu = ins.put("P", underlying="U", strike=100, expiry=OE)
    import math

    lhs = p.price(c, m) - p.price(pu, m)
    rhs = m["spot"] - 100 * math.exp(-m["rate"] * m["t"])
    assert lhs == pytest.approx(rhs, abs=1e-6)


def test_black_scholes_expired_intrinsic():
    p = ins.BlackScholesPricer()
    c = ins.call("C", underlying="U", strike=100, expiry=OE)
    assert p.price(c, {"spot": 120.0, "vol": 0.2, "t": 0.0}) == pytest.approx(20.0)


def test_greeks_call_delta_range():
    p = ins.BlackScholesPricer()
    c = ins.call("C", underlying="U", strike=100, expiry=OE)
    g = p.greeks(c, {"spot": 100.0, "vol": 0.2, "rate": 0.01, "t": 0.25})
    assert 0.0 < g.delta < 1.0
    assert g.gamma > 0
    assert g.vega > 0


def test_greeks_put_delta_negative():
    p = ins.BlackScholesPricer()
    pu = ins.put("P", underlying="U", strike=100, expiry=OE)
    g = p.greeks(pu, {"spot": 100.0, "vol": 0.2, "rate": 0.01, "t": 0.25})
    assert -1.0 < g.delta < 0.0


def test_greeks_add_and_scale():
    g = Greeks(delta=0.5, gamma=0.1)
    assert (g + g).delta == 1.0
    assert g.scale(2).gamma == pytest.approx(0.2)


def test_mock_pricer_option_intrinsic():
    p = ins.DeterministicMockPricer()
    c = ins.call("C", underlying="U", strike=100, expiry=OE)
    assert p.price(c, {"spot": 120.0}) == 20.0


def test_mock_pricer_linear_mark():
    p = ins.DeterministicMockPricer()
    assert p.price(ins.equity("X"), {"mark": 42.0}) == 42.0


def test_value_position_market_value():
    r = vln.value_position(es_future(), 2, 4000.0, {"mark": 4010.0}, ins.DeterministicMockPricer())
    assert r.market_value == pytest.approx(2 * 4010.0 * 50)


def test_value_position_fx_conversion():
    class FX:
        def rate(self, a, b, **k):
            return 1.10

    e = ins.equity("EU", currency="EUR")
    r = vln.value_position(
        e,
        100,
        90.0,
        {"mark": 90.0},
        ins.DeterministicMockPricer(),
        base_currency="USD",
        fx_provider=FX(),
    )
    assert r.base_market_value == pytest.approx(100 * 90.0 * 1.10)


def test_value_position_fx_missing_provider_raises():
    e = ins.equity("EU", currency="EUR")
    with pytest.raises(ValueError):
        vln.value_position(
            e, 1, 1.0, {"mark": 1.0}, ins.DeterministicMockPricer(), base_currency="USD"
        )


def test_econ_trade_cash_principal():
    assert econ.trade_cash(ins.equity("X"), 100, 10.0, 5.0) == -(100 * 10.0) - 5.0


def test_econ_trade_cash_margined():
    assert econ.trade_cash(es_future(), 2, 4000.0, 7.0) == -7.0


# ─────────────────────────── margin / collateral ───────────────────────────


def test_margin_call_breached():
    call = mg.check_call(es_future(), 2, 4000.0, posted=10_000.0)
    assert call.breached
    assert call.shortfall == pytest.approx(6000.0)


def test_margin_call_covered():
    call = mg.check_call(es_future(), 2, 4000.0, posted=20_000.0)
    assert not call.breached


def test_liquidation_warning():
    call = mg.check_call(es_future(), 2, 4000.0, posted=0.0)
    assert mg.liquidation_warning(call, buffer=1000.0)


def test_collateral_haircut_value():
    c = collateral.post(cash=100.0, securities=200.0, haircut=0.10)
    assert c.value == pytest.approx(100.0 + 200.0 * 0.9)


def test_collateral_covers():
    c = collateral.post(cash=1000.0)
    assert collateral.covers(c, 1000.0)
    assert not collateral.covers(c, 1000.01)


def test_collateral_bad_haircut():
    with pytest.raises(ValueError):
        collateral.post(securities=100.0, haircut=1.0)


def test_collateral_base_value_fx():
    class FX:
        def rate(self, a, b, **k):
            return 1.25

    c = collateral.post(cash=100.0, currency="GBP")
    assert collateral.base_value(c, "USD", FX()) == pytest.approx(125.0)


def test_collateral_base_value_same_ccy():
    c = collateral.post(cash=100.0, currency="USD")
    assert collateral.base_value(c, "USD") == 100.0


# ─────────────────────────── risk integration ──────────────────────────────


def test_risk_equity_only_pure_delta():
    b = book()
    b.book_trade(ins.equity("AAPL"), 100, 150.0)
    b.mark({"AAPL": 150.0})
    rep = rk.exposures(b, {"AAPL": 150.0})
    assert rep.delta == pytest.approx(15_000.0)
    assert rep.gamma == 0.0
    assert rep.vega == 0.0


def test_risk_future_notional_and_margin():
    b = book()
    b.book_trade(es_future(), 2, 4000.0)
    rep = rk.exposures(b, {"ES": 4000.0})
    assert rep.notional == pytest.approx(2 * 4000.0 * 50)
    assert rep.margin == pytest.approx(20_000.0)


def test_risk_option_greeks_from_provider():
    b = book()
    c = ins.call("C", underlying="U", strike=100, expiry=OE)
    b.book_trade(c, 10, 5.0)
    rep = rk.exposures(
        b,
        {"C": 5.0},
        greeks_provider=ins.BlackScholesPricer(),
        market={"C": {"spot": 100.0, "vol": 0.2, "rate": 0.01, "t": 0.25}},
    )
    assert rep.gamma > 0
    assert rep.vega > 0


def test_risk_leverage():
    b = book(100_000.0)
    b.book_trade(es_future(), 2, 4000.0)
    rep = rk.exposures(b, {"ES": 4000.0})
    assert rep.leverage > 1.0


def test_risk_to_m13_inputs_keys():
    b = book()
    b.book_trade(es_future(), 1, 4000.0)
    d = rk.to_m13_inputs(rk.exposures(b, {"ES": 4000.0}))
    assert {"gross_notional", "net_delta", "margin", "leverage"} <= set(d)


def test_risk_bond_duration_exposure():
    b = book()
    bd = fi.bond("UST", face=1000.0, coupon=0.04, maturity=DE)
    b.book_trade(bd, 10, 100.0)
    b.mark({"UST": 100.0})
    rep = rk.exposures(b, {"UST": 100.0}, yield_provider=ins.MockYieldProvider())
    assert rep.duration > 0


# ─────────────────────────── settlement ────────────────────────────────────


def test_settlement_option_cash():
    b = book()
    c = ins.call("C", underlying="U", strike=150, expiry=OE)
    b.book_trade(c, 1, 5.0)
    r = stl.settle_expiry(b, c, 170.0)
    assert r.cash == pytest.approx(2000.0)


def test_settlement_future_flat():
    b = book()
    f = es_future()
    b.book_trade(f, 1, 4000.0)
    stl.settle_expiry(b, f, 4010.0)
    assert b.snapshot("ES").quantity == 0


def test_settlement_cash_book_advances_m15():
    b = book()
    b.book_trade(ins.equity("AAPL"), 100, 150.0, trade_date=D0)
    settled = stl.settle_cash_book(b, date(2026, 1, 10))
    assert isinstance(settled, list)


# ─────────────────────────── reconciliation ────────────────────────────────


def test_recon_clean():
    b = book()
    b.book_trade(es_future(), 2, 4000.0)
    b.mark({"ES": 4000.0})
    rep = recon.reconcile_positions(b, {"ES": {"quantity": 2.0}})
    assert rep.clean


def test_recon_wrong_quantity():
    b = book()
    b.book_trade(es_future(), 2, 4000.0)
    rep = recon.reconcile_positions(b, {"ES": {"quantity": 3.0}})
    assert rep.of_kind("wrong_quantity")


def test_recon_missing_contract_external():
    b = book()
    rep = recon.reconcile_positions(b, {"ES": {"quantity": 1.0}})
    assert rep.of_kind("missing_contract")


def test_recon_missing_contract_internal():
    b = book()
    b.book_trade(es_future(), 1, 4000.0)
    b.mark({"ES": 4000.0})
    rep = recon.reconcile_positions(b, {})
    assert rep.of_kind("missing_contract")


def test_recon_wrong_margin():
    b = book()
    b.book_trade(es_future(), 2, 4000.0)
    b.mark({"ES": 4000.0})
    rep = recon.reconcile_positions(b, {"ES": {"quantity": 2.0, "margin": 1.0}})
    assert rep.of_kind("wrong_margin")


def test_recon_wrong_valuation():
    b = book()
    b.book_trade(es_future(), 2, 4000.0)
    b.mark({"ES": 4000.0})
    rep = recon.reconcile_positions(b, {"ES": {"quantity": 2.0, "valuation": 999.0}})
    assert rep.of_kind("wrong_valuation")


def test_recon_missing_exercise():
    b = book()
    c = ins.call("C", underlying="U", strike=150, expiry=OE)
    b.book_trade(c, 1, 5.0)
    rep = recon.reconcile_settlement(b, settled_ids=set(), expected_closed={"C"})
    assert rep.of_kind("missing_exercise")


# ─────────────────── serialization / determinism ───────────────────────────


def build_full():
    b = book()
    b.book_trade(ins.equity("AAPL"), 100, 150.0, trade_date=D0)
    b.book_trade(es_future(), 2, 4000.0, trade_date=D0)
    b.mark({"ES": 4010.0, "AAPL": 160.0}, when=D0)
    b.book_trade(ins.call("C", underlying="AAPL", strike=150, expiry=OE), 1, 5.0, trade_date=D0)
    return b


def test_serialization_roundtrip_keys():
    d = ser.to_dict(build_full())
    assert {"cash", "positions", "instruments", "events", "fingerprint"} <= set(d)


def test_serialization_deterministic():
    assert ser.to_json(build_full()) == ser.to_json(build_full())


def test_fingerprint_stable():
    assert diagnostics.fingerprint(build_full()) == diagnostics.fingerprint(build_full())


def test_fingerprint_changes_with_position():
    b1, b2 = build_full(), build_full()
    b2.book_trade(es_future(), 1, 4010.0)
    assert diagnostics.fingerprint(b1) != diagnostics.fingerprint(b2)


def test_serialization_save(tmp_path):
    p = tmp_path / "book.json"
    ser.save_json(build_full(), str(p))
    assert p.exists()
    assert p.read_text().startswith("{")


def test_diagnostics_counts():
    d = diagnostics.diagnostics(build_full())
    assert d["n_open_positions"] >= 1
    assert d["positions_by_type"]


# ─────────────────────────── validation ────────────────────────────────────


def test_validate_option_missing_strike():
    from mentisrex.research.instruments.models import Instrument

    # model allows an under-specified option; the validator is what flags it
    bad = Instrument("C", InstrumentType.OPTION, expiry=None, underlying=None, strike=None)
    problems = val.validate_instrument(bad)
    assert any("strike" in p for p in problems)
    assert any("expiry" in p for p in problems)
    assert any("underlying" in p for p in problems)


def test_validate_book_clean():
    assert val.is_valid(build_full())


def test_validate_future_margin_ordering():
    f = ins.future("F", expiry=DE, initial_margin_rate=0.01, maintenance_margin_rate=0.05)
    assert any("maintenance" in p for p in val.validate_instrument(f))


# ─────────────────────────── failure / edge cases ──────────────────────────


def test_zero_quantity_rejected():
    b = book()
    with pytest.raises(ValueError):
        b.book_trade(ins.equity("X"), 0, 100.0)


def test_trade_unregistered_auto_registers():
    b = book()
    b.book_trade(es_future(), 1, 4000.0)
    assert b.registry.has("ES")


def test_mark_unknown_instrument_ignored():
    b = book()
    b.book_trade(es_future(), 1, 4000.0)
    b.mark({"UNKNOWN": 1.0})  # no crash, no effect
    assert b.snapshot("ES").quantity == 1


def test_close_flat_noop():
    b = book()
    f = es_future()
    b.book_trade(f, 1, 4000.0)
    b.mark({"ES": 4000.0})
    b.close(f, 4000.0)
    b.close(f, 4000.0)  # already flat
    assert b.snapshot("ES").quantity == 0


def test_position_flip_through_zero():
    from mentisrex.research.instruments.positions import DerivativePosition

    p = DerivativePosition(es_future())
    p.apply(2, 4000.0)
    p.apply(-3, 4010.0)  # close 2, open -1
    assert p.quantity == -1
    assert p.avg_price == pytest.approx(4010.0)
    assert p.realized_pnl == pytest.approx((4010.0 - 4000.0) * 2 * 50)


def test_option_otm_put_expires():
    b = book()
    p = ins.put("P", underlying="U", strike=100, expiry=OE)
    b.book_trade(p, 1, 3.0)
    r = ex.exercise(b, p, 120.0)
    assert r.status is ExerciseStatus.EXPIRED


def test_determinism_across_two_books_full():
    assert ser.to_json(build_full()) == ser.to_json(build_full())


def test_open_positions_excludes_flat():
    b = book()
    f = es_future()
    b.book_trade(f, 1, 4000.0)
    b.mark({"ES": 4000.0})
    b.close(f, 4000.0)
    assert all(p.instrument_id != "ES" for p in b.open_positions())


def test_events_appended():
    b = build_full()
    assert len(b.events) > 0


def test_creation_event_emitted():
    from mentisrex.research.instruments.models import InstrumentEventType

    b = book()
    b.register(es_future())
    assert b.events.of_type(type(b.events.events[0]))
    assert any(e.type is InstrumentEventType.CREATION for e in b.events.events)


def test_forward_negative_mtm():
    b = book()
    fwd = ins.forward("FWD", contract_size=1000, settlement_date=DE)
    b.book_trade(fwd, 1, 1.10)
    b.mark({"FWD": 1.08})
    assert b.realized_pnl() == pytest.approx(1000 * -0.02)


def test_bond_quarterly_schedule():
    bd = fi.bond("UST", coupon=0.04, maturity=date(2027, 1, 5), frequency=4)
    sched = fi.coupon_schedule(bd, issue=date(2026, 1, 5))
    assert len(sched) == 4


def test_collateral_lifts_risk_equity_value():
    b = book(100_000.0)
    b.book_trade(es_future(), 2, 4000.0)
    base = rk.exposures(b, {"ES": 4000.0}).equity_value
    b.collateral["ES"] = collateral.post(cash=50_000.0)
    lifted = rk.exposures(b, {"ES": 4000.0}).equity_value
    assert lifted == pytest.approx(base + 50_000.0)


def test_mock_greeks_itm_call_delta_one():
    g = ins.DeterministicMockPricer().greeks(
        ins.call("C", underlying="U", strike=100, expiry=OE), {"spot": 120.0}
    )
    assert g.delta == 1.0


def test_swap_npv_trade_records_position():
    b = book()
    s = ins.interest_rate_swap("IRS", notional=1_000_000, fixed_rate=0.03)
    b.book_trade(s, 1, 0.0)
    assert b.snapshot("IRS") is not None
