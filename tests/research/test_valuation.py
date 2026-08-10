"""AIDP M18 — Institutional Valuation & Market-Data Infrastructure tests.

Deterministic, offline. Covers market-data snapshots + PIT validation, day-count/compounding,
interpolation, yield curves + discounting + forward curves, curve building, volatility
surfaces, Black-Scholes, Black-76, Greeks (analytic vs finite-difference), American binomial,
futures fair value, bonds, swaps, FX forwards, cross-currency swaps, portfolio valuation,
model governance, M13/M16/M17 integration, serialization, determinism, arbitrage diagnostics,
property/invariant tests and edge cases.
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pytest

from aurelius.research import fx as m16fx
from aurelius.research import instruments as ins
from aurelius.research import valuation as val
from aurelius.research.valuation import (
    american,
    bonds,
    cross_currency as xccy,
    curves,
    daycount as dc,
    diagnostics as diag,
    fx as vfx,
    futures as vfut,
    greeks as gk,
    interpolation as interp,
    pricing,
    reconciliation as recon,
    serialization as ser,
    snapshot as snap_mod,
    swaps as vsw,
    validation as vld,
    volatility as vol,
)

AS_OF = date(2026, 1, 5)


def flat_zc(rate=0.03, cid="USD", currency="USD"):
    return val.ZeroCurve(cid, AS_OF, (0.25, 1.0, 2.0, 5.0, 10.0, 30.0), (rate,) * 6, currency=currency)


def make_snap(**kw):
    kw.setdefault("spots", {"AAPL": 150.0})
    kw.setdefault("rates", {"USD": flat_zc()})
    kw.setdefault("vol_surfaces", {"AAPL": val.flat_surface("AAPL", AS_OF, 0.25)})
    kw.setdefault("dividend_yields", {"AAPL": 0.0})
    return val.build_snapshot(AS_OF, **kw)


def call_opt(strike=150.0, expiry=date(2027, 1, 5)):
    return ins.call("AAPL-C", underlying="AAPL", strike=strike, expiry=expiry)


# ─────────────────────────── day count / compounding ───────────────────────

def test_act365():
    assert dc.year_fraction(date(2026, 1, 1), date(2027, 1, 1), dc.DayCount.ACT_365) == pytest.approx(365 / 365)


def test_act360():
    assert dc.year_fraction(date(2026, 1, 1), date(2026, 1, 31), dc.DayCount.ACT_360) == pytest.approx(30 / 360)


def test_thirty360():
    assert dc.year_fraction(date(2026, 1, 15), date(2026, 7, 15), dc.DayCount.THIRTY_360) == pytest.approx(0.5)


def test_year_fraction_reversed_raises():
    with pytest.raises(ValueError):
        dc.year_fraction(date(2026, 2, 1), date(2026, 1, 1))


def test_df_continuous_roundtrip():
    df = dc.discount_factor(0.05, 2.0, dc.Compounding.CONTINUOUS)
    assert dc.zero_from_df(df, 2.0, dc.Compounding.CONTINUOUS) == pytest.approx(0.05)


def test_df_semiannual_roundtrip():
    df = dc.discount_factor(0.04, 3.0, dc.Compounding.SEMIANNUAL)
    assert dc.zero_from_df(df, 3.0, dc.Compounding.SEMIANNUAL) == pytest.approx(0.04)


def test_df_simple_roundtrip():
    df = dc.discount_factor(0.03, 1.5, dc.Compounding.SIMPLE)
    assert dc.zero_from_df(df, 1.5, dc.Compounding.SIMPLE) == pytest.approx(0.03)


def test_df_annual_roundtrip():
    df = dc.discount_factor(0.06, 4.0, dc.Compounding.ANNUAL)
    assert dc.zero_from_df(df, 4.0, dc.Compounding.ANNUAL) == pytest.approx(0.06)


def test_df_at_zero_is_one():
    assert dc.discount_factor(0.05, 0.0) == 1.0


def test_zero_from_df_bad_df():
    with pytest.raises(ValueError):
        dc.zero_from_df(-0.1, 1.0)


# ─────────────────────────── interpolation ─────────────────────────────────

def test_linear_midpoint():
    assert interp.linear([0, 1], [0, 10], 0.5) == pytest.approx(5.0)


def test_linear_on_knot():
    assert interp.linear([0, 1, 2], [1, 2, 3], 1.0) == 2.0


def test_linear_flat_extrap():
    assert interp.linear([1, 2], [10, 20], 3.0, extrap=interp.Extrapolation.FLAT) == 20.0


def test_linear_linear_extrap():
    assert interp.linear([1, 2], [10, 20], 3.0, extrap=interp.Extrapolation.LINEAR) == pytest.approx(30.0)


def test_linear_error_extrap():
    with pytest.raises(ValueError):
        interp.linear([1, 2], [10, 20], 3.0, extrap=interp.Extrapolation.ERROR)


def test_linear_single_point():
    assert interp.linear([1], [5], 99) == 5


def test_log_linear_positive():
    assert interp.log_linear([0, 1], [1.0, 0.9], 0.5) == pytest.approx(math.sqrt(0.9))


def test_log_linear_rejects_nonpositive():
    with pytest.raises(ValueError):
        interp.log_linear([0, 1], [1.0, -0.1], 0.5)


def test_bilinear():
    grid = [[1.0, 2.0], [3.0, 4.0]]
    assert interp.bilinear([0, 1], [0, 1], grid, 0.5, 0.5) == pytest.approx(2.5)


# ─────────────────────────── curves ────────────────────────────────────────

def test_zero_curve_flat_rate():
    assert flat_zc(0.03).zero_rate(3.0) == pytest.approx(0.03)


def test_zero_curve_discount_positive():
    assert 0 < flat_zc(0.03).discount(5.0) < 1


def test_zero_curve_df_at_zero():
    assert flat_zc().discount(0.0) == 1.0


def test_zero_curve_forward_rate():
    zc = flat_zc(0.03)
    assert zc.forward_rate(1.0, 2.0) == pytest.approx(0.03, abs=1e-3)


def test_zero_curve_tenors_must_increase():
    with pytest.raises(ValueError):
        val.ZeroCurve("X", AS_OF, (2.0, 1.0), (0.03, 0.03))


def test_zero_curve_validate_clean():
    assert flat_zc().validate() == []


def test_discount_curve_from_zero():
    dcv = flat_zc(0.03).as_discount_curve()
    assert dcv.discount(2.0) == pytest.approx(flat_zc(0.03).discount(2.0), rel=1e-6)


def test_discount_curve_zero_rate_inverse():
    dcv = flat_zc(0.04).as_discount_curve()
    assert dcv.zero_rate(5.0) == pytest.approx(0.04, abs=1e-6)


def test_discount_curve_rejects_negative_df():
    with pytest.raises(ValueError):
        val.DiscountCurve("X", AS_OF, (1.0,), (-0.5,))


def test_discount_curve_monotone_validate():
    dcv = val.DiscountCurve("X", AS_OF, (1.0, 2.0), (0.9, 0.95))   # rising DF => neg fwd
    assert dcv.validate()


def test_forward_curve_interp():
    fc = val.ForwardCurve("F", AS_OF, (1.0, 2.0), (100.0, 110.0))
    assert fc.forward(1.5) == pytest.approx(105.0)


def test_flat_curve_helper():
    assert val.flat_curve("USD", AS_OF, 0.05).zero_rate(10.0) == pytest.approx(0.05)


def test_discount_to_date():
    zc = flat_zc(0.03)
    assert zc.discount_to(date(2027, 1, 5)) == pytest.approx(zc.discount(1.0), abs=1e-3)


# ─────────────────────────── curve builder ─────────────────────────────────

def test_curve_builder_zero():
    cb = val.CurveBuilder()
    curve, report = cb.build_zero("USD", AS_OF, [(1.0, 0.03), (5.0, 0.035)])
    assert report.ok
    assert curve.zero_rate(1.0) == pytest.approx(0.03)


def test_curve_builder_report_diagnostics():
    _, report = val.CurveBuilder().build_zero("USD", AS_OF, [(0.5, 0.02), (2.0, 0.03)])
    assert report.diagnostics.n_instruments == 2
    assert report.diagnostics.converged


# ─────────────────────────── volatility ────────────────────────────────────

def test_flat_surface_constant():
    s = val.flat_surface("X", AS_OF, 0.2)
    assert s.vol(100.0, 1.0) == pytest.approx(0.2)


def test_surface_grid_interp():
    s = val.VolatilitySurface("X", AS_OF, (90.0, 110.0), (0.5, 1.0),
                              ((0.2, 0.22), (0.24, 0.26)))
    assert s.vol(100.0, 0.75) == pytest.approx(0.23, abs=1e-9)


def test_surface_rejects_nonpositive_interp():
    s = val.VolatilitySurface("X", AS_OF, (90.0, 110.0), (0.5, 1.0),
                              ((0.2, 0.2), (0.2, 0.2)))
    assert s.vol(100, 0.75) > 0


def test_surface_validate_negative():
    s = val.VolatilitySurface("X", AS_OF, (90.0, 110.0), (0.5, 1.0),
                              ((0.2, -0.1), (0.2, 0.2)))
    assert s.validate()


def test_surface_staleness():
    s = val.flat_surface("X", date(2026, 1, 1), 0.2)
    assert s.is_stale(date(2026, 2, 1), 10)
    assert not s.is_stale(date(2026, 1, 5), 10)


def test_constant_vol_provider():
    assert vol.ConstantVolProvider(0.3).implied_vol("X", 100, 1.0) == 0.3


def test_surface_vol_provider():
    p = vol.SurfaceVolProvider({"AAPL": val.flat_surface("AAPL", AS_OF, 0.25)})
    assert p.implied_vol("AAPL", 150, 1.0) == pytest.approx(0.25)


def test_surface_vol_provider_missing():
    with pytest.raises(KeyError):
        vol.SurfaceVolProvider({}).implied_vol("X", 1, 1)


# ─────────────────────────── Black-Scholes ─────────────────────────────────

def test_bs_call_positive():
    assert pricing.black_scholes_price(True, 100, 100, 0.05, 0.0, 0.2, 1.0) > 0


def test_bs_put_call_parity():
    c = pricing.black_scholes_price(True, 100, 90, 0.05, 0.02, 0.2, 1.0)
    p = pricing.black_scholes_price(False, 100, 90, 0.05, 0.02, 0.2, 1.0)
    rhs = 100 * math.exp(-0.02) - 90 * math.exp(-0.05)
    assert (c - p) == pytest.approx(rhs, abs=1e-9)


def test_bs_call_monotonic_in_spot():
    lo = pricing.black_scholes_price(True, 90, 100, 0.05, 0.0, 0.2, 1.0)
    hi = pricing.black_scholes_price(True, 110, 100, 0.05, 0.0, 0.2, 1.0)
    assert hi > lo


def test_bs_put_monotonic_in_spot():
    lo = pricing.black_scholes_price(False, 90, 100, 0.05, 0.0, 0.2, 1.0)
    hi = pricing.black_scholes_price(False, 110, 100, 0.05, 0.0, 0.2, 1.0)
    assert lo > hi


def test_bs_expiry_intrinsic_call():
    assert pricing.black_scholes_price(True, 120, 100, 0.0, 0.0, 0.2, 0.0) == pytest.approx(20.0)


def test_bs_expiry_intrinsic_put():
    assert pricing.black_scholes_price(False, 80, 100, 0.0, 0.0, 0.2, 0.0) == pytest.approx(20.0)


def test_bs_more_time_more_value():
    short = pricing.black_scholes_price(True, 100, 100, 0.05, 0.0, 0.2, 0.5)
    long = pricing.black_scholes_price(True, 100, 100, 0.05, 0.0, 0.2, 2.0)
    assert long > short


def test_bs_higher_vol_more_value():
    lo = pricing.black_scholes_price(True, 100, 100, 0.05, 0.0, 0.1, 1.0)
    hi = pricing.black_scholes_price(True, 100, 100, 0.05, 0.0, 0.4, 1.0)
    assert hi > lo


def test_bs_bad_spot():
    with pytest.raises(ValueError):
        pricing.black_scholes_price(True, -1, 100, 0.05, 0.0, 0.2, 1.0)


def test_bs_within_bounds():
    px = pricing.black_scholes_price(True, 100, 100, 0.05, 0.0, 0.2, 1.0)
    assert diag.option_bounds(px, True, 100, 100, 0.05, 0.0, 1.0) == []


# ─────────────────────────── Black-76 ──────────────────────────────────────

def test_black76_parity():
    c = pricing.black76_price(True, 100, 95, 0.03, 0.2, 1.0)
    p = pricing.black76_price(False, 100, 95, 0.03, 0.2, 1.0)
    rhs = math.exp(-0.03) * (100 - 95)
    assert (c - p) == pytest.approx(rhs, abs=1e-9)


def test_black76_equals_bs_when_q_equals_r():
    f = 100 * math.exp((0.05 - 0.05) * 1.0)     # q=r => F=S
    b76 = pricing.black76_price(True, f, 100, 0.05, 0.2, 1.0)
    bs = pricing.black_scholes_price(True, 100, 100, 0.05, 0.05, 0.2, 1.0)
    assert b76 == pytest.approx(bs, abs=1e-9)


def test_black76_expiry_intrinsic():
    assert pricing.black76_price(True, 110, 100, 0.0, 0.2, 0.0) == pytest.approx(10.0)


# ─────────────────────────── Greeks ────────────────────────────────────────

def test_greek_delta_matches_fd():
    g = pricing.black_scholes_greeks(True, 100, 100, 0.05, 0.01, 0.2, 1.0)
    assert g["delta"] == pytest.approx(gk.fd_delta(True, 100, 100, 0.05, 0.01, 0.2, 1.0), abs=1e-5)


def test_greek_gamma_matches_fd():
    g = pricing.black_scholes_greeks(True, 100, 100, 0.05, 0.01, 0.2, 1.0)
    assert g["gamma"] == pytest.approx(gk.fd_gamma(True, 100, 100, 0.05, 0.01, 0.2, 1.0), abs=1e-4)


def test_greek_vega_matches_fd():
    g = pricing.black_scholes_greeks(True, 100, 100, 0.05, 0.01, 0.2, 1.0)
    assert g["vega"] == pytest.approx(gk.fd_vega(True, 100, 100, 0.05, 0.01, 0.2, 1.0), abs=1e-3)


def test_greek_rho_matches_fd():
    g = pricing.black_scholes_greeks(True, 100, 100, 0.05, 0.01, 0.2, 1.0)
    assert g["rho"] == pytest.approx(gk.fd_rho(True, 100, 100, 0.05, 0.01, 0.2, 1.0), abs=1e-3)


def test_call_delta_between_0_1():
    g = pricing.black_scholes_greeks(True, 100, 100, 0.05, 0.0, 0.2, 1.0)
    assert 0 < g["delta"] < 1


def test_put_delta_between_minus1_0():
    g = pricing.black_scholes_greeks(False, 100, 100, 0.05, 0.0, 0.2, 1.0)
    assert -1 < g["delta"] < 0


def test_gamma_positive():
    assert pricing.black_scholes_greeks(True, 100, 100, 0.05, 0.0, 0.2, 1.0)["gamma"] > 0


def test_call_put_gamma_equal():
    gc = pricing.black_scholes_greeks(True, 100, 100, 0.05, 0.02, 0.2, 1.0)
    gp = pricing.black_scholes_greeks(False, 100, 100, 0.05, 0.02, 0.2, 1.0)
    assert gc["gamma"] == pytest.approx(gp["gamma"])


def test_call_put_vega_equal():
    gc = pricing.black_scholes_greeks(True, 100, 100, 0.05, 0.02, 0.2, 1.0)
    gp = pricing.black_scholes_greeks(False, 100, 100, 0.05, 0.02, 0.2, 1.0)
    assert gc["vega"] == pytest.approx(gp["vega"])


def test_vanna_volga_present():
    g = pricing.black_scholes_greeks(True, 100, 110, 0.05, 0.0, 0.2, 1.0)
    assert "vanna" in g and "volga" in g


def test_greeks_dataclass_add_scale():
    g = val.Greeks(delta=0.5, vega=10)
    assert (g + g).delta == 1.0
    assert g.scale(2).vega == 20


# ─────────────────────────── implied vol ───────────────────────────────────

def test_implied_vol_roundtrip():
    px = pricing.black_scholes_price(True, 100, 100, 0.05, 0.0, 0.3, 1.0)
    assert pricing.implied_vol(True, px, 100, 100, 0.05, 0.0, 1.0) == pytest.approx(0.3, abs=1e-4)


def test_implied_vol_put_roundtrip():
    px = pricing.black_scholes_price(False, 100, 110, 0.05, 0.01, 0.25, 2.0)
    assert pricing.implied_vol(False, px, 100, 110, 0.05, 0.01, 2.0) == pytest.approx(0.25, abs=1e-4)


def test_implied_vol_intrinsic_zero():
    assert pricing.implied_vol(True, 0.0, 100, 200, 0.0, 0.0, 1.0) == 0.0


# ─────────────────────────── American ──────────────────────────────────────

def test_american_call_no_div_equals_european():
    a = american.crr_price(True, 100, 100, 0.05, 0.0, 0.2, 1.0, steps=400)
    e = pricing.black_scholes_price(True, 100, 100, 0.05, 0.0, 0.2, 1.0)
    assert a == pytest.approx(e, abs=0.05)


def test_american_put_ge_european():
    a = american.crr_price(False, 100, 100, 0.05, 0.0, 0.2, 1.0, steps=300)
    e = pricing.black_scholes_price(False, 100, 100, 0.05, 0.0, 0.2, 1.0)
    assert a >= e - 1e-6


def test_american_european_flag_matches_bs():
    a = american.crr_price(True, 100, 100, 0.05, 0.02, 0.2, 1.0, steps=500, american=False)
    e = pricing.black_scholes_price(True, 100, 100, 0.05, 0.02, 0.2, 1.0)
    assert a == pytest.approx(e, abs=0.05)


def test_american_greeks_delta_sign():
    g = american.crr_greeks(True, 100, 100, 0.05, 0.0, 0.2, 1.0, steps=200)
    assert 0 < g["delta"] < 1


def test_american_expiry_intrinsic():
    assert american.crr_price(True, 120, 100, 0.05, 0.0, 0.2, 0.0) == pytest.approx(20.0)


# ─────────────────────────── futures ───────────────────────────────────────

def test_futures_fair_value_carry():
    assert vfut.fair_value(100, 0.05, 0.0, 1.0) == pytest.approx(100 * math.exp(0.05))


def test_futures_convergence_at_expiry():
    assert vfut.fair_value(100, 0.05, 0.02, 0.0) == pytest.approx(100.0)
    assert vfut.converges_at_expiry(100, 0.05, 0.02)


def test_futures_basis():
    fv = vfut.fair_value(100, 0.05, 0.0, 1.0)
    assert vfut.basis(fv, 100) > 0


def test_futures_implied_financing_roundtrip():
    fv = vfut.fair_value(100, 0.04, 0.01, 1.0)
    assert vfut.implied_financing(fv, 100, 0.01, 1.0) == pytest.approx(0.04, abs=1e-9)


def test_futures_dividend_reduces_fair_value():
    hi = vfut.fair_value(100, 0.05, 0.0, 1.0)
    lo = vfut.fair_value(100, 0.05, 0.03, 1.0)
    assert lo < hi


# ─────────────────────────── bonds ─────────────────────────────────────────

def bspec(**kw):
    kw.setdefault("coupon", 0.05)
    kw.setdefault("frequency", 2)
    kw.setdefault("issue", date(2024, 1, 5))
    kw.setdefault("maturity", date(2029, 1, 5))
    return bonds.BondSpec(**kw)


def test_bond_cash_flows_redeem_principal():
    flows = bonds.cash_flows(bspec())
    assert flows[-1][1] == pytest.approx(0.05 / 2 * 100 + 100)


def test_bond_par_when_yield_equals_coupon():
    px = bonds.clean_price_from_yield(bspec(), 0.05, AS_OF)
    assert px == pytest.approx(100.0, abs=1e-6)


def test_bond_ytm_roundtrip():
    spec = bspec()
    px = bonds.clean_price_from_yield(spec, 0.045, AS_OF)
    assert bonds.yield_to_maturity(spec, px, AS_OF) == pytest.approx(0.045, abs=1e-6)


def test_bond_price_yield_inverse_monotonic():
    lo = bonds.clean_price_from_yield(bspec(), 0.06, AS_OF)
    hi = bonds.clean_price_from_yield(bspec(), 0.04, AS_OF)
    assert hi > lo


def test_bond_duration_positive():
    assert bonds.modified_duration(bspec(), 0.05, AS_OF) > 0


def test_bond_modified_lt_macaulay():
    spec = bspec()
    assert bonds.modified_duration(spec, 0.05, AS_OF) < bonds.macaulay_duration(spec, 0.05, AS_OF)


def test_bond_convexity_positive():
    assert bonds.convexity(bspec(), 0.05, AS_OF) > 0


def test_bond_dv01_positive():
    assert bonds.dv01(bspec(), 0.05, AS_OF) > 0


def test_bond_dv01_duration_relationship():
    spec = bspec()
    dirty = bonds.dirty_price_from_yield(spec, 0.05, AS_OF)
    md = bonds.modified_duration(spec, 0.05, AS_OF)
    assert bonds.dv01(spec, 0.05, AS_OF) == pytest.approx(md * dirty * 1e-4, rel=1e-3)


def test_zero_coupon_no_accrued():
    z = bonds.BondSpec(coupon=0.0, frequency=0, maturity=date(2030, 1, 5))
    assert bonds.accrued_interest(z, AS_OF) == 0.0


def test_bond_accrued_positive_midperiod():
    assert bonds.accrued_interest(bspec(), date(2026, 4, 5)) > 0


def test_bond_price_from_curve():
    px = bonds.price_from_curve(bspec(), flat_zc(0.05), AS_OF)
    assert 90 < px < 115


def test_bond_frequency_quarterly():
    spec = bspec(frequency=4)
    flows = bonds.cash_flows(spec)
    assert len(flows) == pytest.approx(20, abs=1)


# ─────────────────────────── swaps ─────────────────────────────────────────

def swap_spec(rate=0.03):
    return vsw.SwapSpec(1e7, rate, tuple(date(2026 + i, 1, 5) for i in range(1, 6)), AS_OF)


def test_swap_par_rate_zeroes_npv():
    zc = flat_zc(0.03)
    par = vsw.par_rate(swap_spec(), zc)
    at_par = vsw.SwapSpec(1e7, par, swap_spec().pay_dates, AS_OF)
    assert vsw.npv(at_par, zc) == pytest.approx(0.0, abs=1e-3)


def test_swap_payer_gains_when_rates_rise():
    par = vsw.par_rate(swap_spec(), flat_zc(0.03))
    at_par = vsw.SwapSpec(1e7, par, swap_spec().pay_dates, AS_OF)
    npv_hi = vsw.npv(at_par, flat_zc(0.05))       # rates up => payer receives more float
    assert npv_hi > 0


def test_swap_fixed_leg_positive():
    assert vsw.fixed_leg_pv(swap_spec(), flat_zc(0.03)) > 0


def test_swap_dv01_positive():
    assert vsw.dv01(swap_spec(), flat_zc(0.03)) > 0


def test_swap_cash_flow_projection_length():
    proj = vsw.cash_flow_projection(swap_spec(), flat_zc(0.03))
    assert len(proj) == 5


def test_swap_receive_fixed_sign_flips():
    zc = flat_zc(0.05)
    pay = vsw.SwapSpec(1e7, 0.03, swap_spec().pay_dates, AS_OF, pay_fixed=True)
    rec = vsw.SwapSpec(1e7, 0.03, swap_spec().pay_dates, AS_OF, pay_fixed=False)
    assert vsw.npv(pay, zc) == pytest.approx(-vsw.npv(rec, zc))


# ─────────────────────────── FX valuation ──────────────────────────────────

def fxp():
    return m16fx.StaticFXRateProvider({"EUR/USD": 1.10, "GBP/USD": 1.25}, pivot="USD")


def test_fx_spot_delegates_m16():
    assert vfx.spot_rate(fxp(), "EUR", "USD") == pytest.approx(1.10)


def test_fx_forward_covered_parity():
    f = vfx.forward_rate(1.10, 0.01, 0.03, 1.0)
    assert f == pytest.approx(1.10 * math.exp(0.02))


def test_fx_forward_points():
    assert vfx.forward_points(1.10, 1.12) == pytest.approx(0.02)


def test_fx_reciprocal_consistent():
    assert vfx.reciprocal_consistent(fxp(), "EUR", "USD")


def test_fx_cross_rate():
    assert vfx.cross_rate(fxp(), "EUR", "GBP", "USD") == pytest.approx(1.10 / 1.25, rel=1e-9)


def test_fx_forward_value_sign():
    v = vfx.fx_forward_value(1e6, 1.10, 1.12, math.exp(-0.03))
    assert v > 0


# ─────────────────────────── cross-currency swap ───────────────────────────

def test_xccy_base_npv_and_exposure():
    recv = xccy.CrossCurrencyLeg(1e7, 0.03, "USD", swap_spec().pay_dates, AS_OF)
    pay = xccy.CrossCurrencyLeg(9e6, 0.02, "EUR", swap_spec().pay_dates, AS_OF)
    res = xccy.value(recv, pay, flat_zc(0.03, "USD"), flat_zc(0.02, "EUR", "EUR"),
                     fxp(), "USD", as_of=AS_OF)
    assert "base_npv" in res
    assert set(res["fx_exposure"]) == {"USD", "EUR"}


# ─────────────────────────── market-data snapshot / PIT ─────────────────────

def test_snapshot_spot_accessor():
    assert make_snap().spot("AAPL") == 150.0


def test_snapshot_missing_spot_raises():
    with pytest.raises(KeyError):
        make_snap().spot("NOPE")


def test_snapshot_fx_rate_via_m16():
    s = make_snap(fx_provider=fxp())
    assert s.fx_rate("EUR", "USD") == pytest.approx(1.10)


def test_snapshot_fx_same_currency():
    assert make_snap().fx_rate("USD", "USD") == 1.0


def test_snapshot_fx_without_provider_raises():
    with pytest.raises(ValueError):
        make_snap().fx_rate("EUR", "USD")


def test_pit_clean():
    assert val.is_pit_safe(make_snap())


def test_pit_rejects_lookahead_quote():
    from aurelius.research.valuation.models import MarketQuote, Provenance
    q = MarketQuote("AAPL", 150, provenance=Provenance(observation_date=date(2026, 2, 1)))
    s = val.build_snapshot(AS_OF, spots={"AAPL": 150}, quotes={"AAPL": q})
    probs = val.validate_pit(s)
    assert any("look-ahead" in p for p in probs)


def test_pit_rejects_stale():
    from aurelius.research.valuation.models import MarketQuote, Provenance
    q = MarketQuote("AAPL", 150, provenance=Provenance(observation_date=date(2025, 1, 1)))
    s = val.build_snapshot(AS_OF, spots={"AAPL": 150}, quotes={"AAPL": q})
    assert val.validate_pit(s, max_staleness_days=30)


def test_pit_rejects_curve_future_refdate():
    fut_curve = val.ZeroCurve("USD", date(2027, 1, 1), (1.0,), (0.03,))
    s = val.build_snapshot(AS_OF, spots={"AAPL": 1}, rates={"USD": fut_curve})
    assert any("ref_date" in p for p in val.validate_pit(s))


def test_pit_timestamp_inconsistent():
    from aurelius.research.valuation.models import MarketQuote, Provenance
    q = MarketQuote("AAPL", 150, provenance=Provenance(
        observation_date=AS_OF, timestamp=datetime(2026, 1, 3, 12, 0)))
    s = val.build_snapshot(AS_OF, spots={"AAPL": 150}, quotes={"AAPL": q})
    assert any("timestamp" in p for p in val.validate_pit(s))


def test_snapshot_fingerprint_stable():
    assert make_snap().fingerprint() == make_snap().fingerprint()


def test_snapshot_fingerprint_changes_with_spot():
    assert make_snap().fingerprint() != make_snap(spots={"AAPL": 151.0}).fingerprint()


# ─────────────────────────── providers ─────────────────────────────────────

def test_static_provider_returns_snapshot():
    p = val.StaticMarketDataProvider(make_snap())
    assert p.snapshot(AS_OF).spot("AAPL") == 150.0


def test_static_provider_strict_date():
    p = val.StaticMarketDataProvider(make_snap(), strict_date=True)
    with pytest.raises(ValueError):
        p.snapshot(date(2026, 2, 1))


def test_historical_provider_pit():
    s1 = val.build_snapshot(date(2026, 1, 1), spots={"AAPL": 100})
    s2 = val.build_snapshot(date(2026, 1, 10), spots={"AAPL": 110})
    p = val.HistoricalMarketDataProvider({date(2026, 1, 1): s1, date(2026, 1, 10): s2})
    assert p.snapshot(date(2026, 1, 5)).spot("AAPL") == 100
    assert p.snapshot(date(2026, 1, 15)).spot("AAPL") == 110


def test_historical_provider_before_history():
    p = val.HistoricalMarketDataProvider({date(2026, 1, 10): make_snap()})
    with pytest.raises(LookupError):
        p.snapshot(date(2026, 1, 1))


def test_mock_provider_builds_snapshot():
    p = val.DeterministicMockMarketDataProvider({"AAPL": 150.0})
    assert p.snapshot(AS_OF).spot("AAPL") == 150.0


def test_mock_provider_accessor():
    p = val.DeterministicMockMarketDataProvider({"AAPL": 150.0}, dividend_yields={"AAPL": 0.02})
    assert p.dividend_yield("AAPL", AS_OF) == 0.02


# ─────────────────────────── engine (multi-asset valuation) ────────────────

def test_engine_equity():
    r = val.ValuationEngine().value(ins.equity("AAPL"), make_snap(), quantity=100)
    assert r.market_value == 15000.0
    assert r.model_name == "equity.spot"


def test_engine_future_fair_value():
    snap = make_snap()
    fut = ins.future("ESZ", underlying="AAPL", contract_size=1, expiry=date(2027, 1, 5))
    r = val.ValuationEngine().value(fut, snap)
    assert r.price > snap.spot("AAPL")             # contango (r>q)


def test_engine_option_greeks():
    r = val.ValuationEngine().value(call_opt(), make_snap())
    assert r.greeks is not None and 0 < r.greeks.delta < 1


def test_engine_option_binomial_config():
    cfg = val.ValuationConfiguration(option_model="binomial", american_steps=100)
    r = val.ValuationEngine().value(call_opt(), make_snap(), cfg)
    assert r.model_name == "option.binomial_crr"


def test_engine_option_black76_config():
    cfg = val.ValuationConfiguration(option_model="black_76")
    r = val.ValuationEngine().value(call_opt(), make_snap(), cfg)
    assert r.model_name == "option.black_76"


def test_engine_bond_from_curve():
    b = ins.bond("UST", face=100.0, coupon=0.05, maturity=date(2029, 1, 5))
    r = val.ValuationEngine().value(b, make_snap(), quantity=10)
    assert r.price > 0 and r.model_name == "bond.dcf"


def test_engine_base_currency_conversion():
    snap = make_snap(fx_provider=fxp())
    e = ins.equity("SAP", currency="EUR")
    snap2 = val.build_snapshot(AS_OF, spots={"SAP": 100.0}, rates={"EUR": flat_zc(0.02, "EUR", "EUR")},
                               fx_provider=fxp())
    cfg = val.ValuationConfiguration(base_currency="USD")
    r = val.ValuationEngine().value(e, snap2, cfg, quantity=10)
    assert r.base_value == pytest.approx(100 * 10 * 1.10)


def test_engine_rejects_lookahead():
    from aurelius.research.valuation.models import MarketQuote, Provenance
    q = MarketQuote("AAPL", 150, provenance=Provenance(observation_date=date(2026, 2, 1)))
    bad = val.build_snapshot(AS_OF, spots={"AAPL": 150}, quotes={"AAPL": q},
                             vol_surfaces={"AAPL": val.flat_surface("AAPL", AS_OF, 0.25)},
                             rates={"USD": flat_zc()})
    with pytest.raises(val.ValuationError):
        val.ValuationEngine().value(ins.equity("AAPL"), bad)


def test_engine_option_no_surface_raises():
    snap = val.build_snapshot(AS_OF, spots={"AAPL": 150.0}, rates={"USD": flat_zc()})
    with pytest.raises(val.ValuationError):
        val.ValuationEngine().value(call_opt(), snap)


def test_engine_pnl_vs_cost():
    r = val.ValuationEngine().value(ins.equity("AAPL"), make_snap(), quantity=100, cost_basis=140.0)
    assert r.pnl == pytest.approx(1000.0)


def test_engine_swap_valuation():
    eng = val.ValuationEngine()
    r = eng.value_swap("IRS", swap_spec(0.03), flat_zc(0.03), snap=make_snap())
    assert r.model_name == "swap.discount_curve"
    assert "dv01" in r.assumptions


def test_engine_xccy_valuation():
    recv = xccy.CrossCurrencyLeg(1e7, 0.03, "USD", swap_spec().pay_dates, AS_OF)
    pay = xccy.CrossCurrencyLeg(9e6, 0.02, "EUR", swap_spec().pay_dates, AS_OF)
    snap = make_snap(fx_provider=fxp())
    res = val.ValuationEngine().value_cross_currency(
        "XS", recv, pay, flat_zc(0.03, "USD"), flat_zc(0.02, "EUR", "EUR"), snap=snap)
    assert res.model_name == "xccy_swap.dual_curve"


# ─────────────────────────── portfolio valuation ───────────────────────────

def test_portfolio_sum_of_parts():
    snap = make_snap()
    positions = [(ins.equity("AAPL"), 100, None), (call_opt(), 10, None)]
    pv = val.PortfolioValuationEngine().value(positions, snap)
    assert pv.base_value == pytest.approx(sum(r.base_value for r in pv.results))


def test_portfolio_greeks_aggregate():
    snap = make_snap()
    pv = val.PortfolioValuationEngine().value([(call_opt(), 10, None)], snap)
    assert pv.greeks.delta != 0


def test_portfolio_risk_inputs():
    pv = val.PortfolioValuationEngine().value([(ins.equity("AAPL"), 100, None)], make_snap())
    assert "portfolio_value" in pv.risk_inputs


def test_portfolio_gross_ge_net():
    snap = make_snap()
    positions = [(ins.equity("AAPL"), 100, None), (ins.equity("AAPL"), -50, None)]
    pv = val.PortfolioValuationEngine().value(positions, snap)
    assert pv.gross_market_value >= abs(pv.net_market_value)


# ─────────────────────────── model governance ──────────────────────────────

def test_result_has_governance_fields():
    r = val.ValuationEngine().value(ins.equity("AAPL"), make_snap())
    assert r.model_name and r.model_version and r.input_fingerprint and r.market_data_fingerprint


def test_reproducible_key_stable():
    a = val.ValuationEngine().value(ins.equity("AAPL"), make_snap())
    b = val.ValuationEngine().value(ins.equity("AAPL"), make_snap())
    assert a.reproducible_key == b.reproducible_key


def test_default_registry_has_models():
    r = val.default_registry()
    assert r.get("option.black_scholes", "1.0.0").name == "option.black_scholes"


def test_registry_duplicate_conflict():
    r = val.ModelRegistry()
    r.register(val.ModelInfo("m", "1", "a"))
    with pytest.raises(ValueError):
        r.register(val.ModelInfo("m", "1", "b"))


def test_registry_unknown_model():
    with pytest.raises(KeyError):
        val.ModelRegistry().get("x", "1")


# ─────────────────────────── determinism / property ────────────────────────

def test_same_snapshot_same_result():
    snap = make_snap()
    a = val.ValuationEngine().value(call_opt(), snap)
    b = val.ValuationEngine().value(call_opt(), snap)
    assert a.price == b.price and a.input_fingerprint == b.input_fingerprint


def test_same_inputs_same_fingerprint():
    a = val.ValuationEngine().value(call_opt(), make_snap())
    b = val.ValuationEngine().value(call_opt(), make_snap())
    assert a.market_data_fingerprint == b.market_data_fingerprint


def test_serialization_deterministic():
    r = val.ValuationEngine().value(call_opt(), make_snap())
    assert ser.to_json(r) == ser.to_json(r)


def test_portfolio_serialization():
    pv = val.PortfolioValuationEngine().value([(ins.equity("AAPL"), 100, None)], make_snap())
    js = ser.to_json(pv)
    assert "results" in js and "market_data_fingerprint" in js


def test_config_fingerprint_changes():
    a = val.ValuationConfiguration(option_model="black_scholes").fingerprint()
    b = val.ValuationConfiguration(option_model="binomial").fingerprint()
    assert a != b


# ─────────────────────────── arbitrage diagnostics ─────────────────────────

def test_diag_negative_df_clean():
    assert diag.negative_discount_factors(flat_zc()) == []


def test_diag_put_call_parity_clean():
    assert diag.put_call_parity(100, 100, 0.05, 0.02, 0.2, 1.0) == []


def test_diag_fx_reciprocal_clean():
    assert diag.fx_reciprocal(fxp(), [("EUR", "USD")]) == []


def test_diag_option_bounds_violation():
    assert diag.option_bounds(1000, True, 100, 100, 0.05, 0.0, 1.0)


def test_diag_calendar_spread_clean():
    s = val.flat_surface("X", AS_OF, 0.2)
    assert diag.calendar_spread(s, 100, 0.5, 1.0) == []


def test_diag_curve_discontinuity_clean():
    assert diag.curve_discontinuities(flat_zc()) == []


def test_diag_negative_prices():
    r = val.ValuationEngine().value(ins.equity("AAPL"), make_snap())
    from dataclasses import replace
    bad = replace(r, price=-1.0)
    assert diag.negative_prices([bad])


# ─────────────────────────── validation ────────────────────────────────────

def test_validator_snapshot_clean():
    assert val.ValuationValidator().validate_snapshot(make_snap()) == []


def test_validator_inputs_missing_surface():
    snap = val.build_snapshot(AS_OF, spots={"AAPL": 150.0}, rates={"USD": flat_zc()})
    probs = val.ValuationValidator().validate_inputs(call_opt(), snap)
    assert any("vol surface" in p for p in probs)


def test_validator_result_clean():
    r = val.ValuationEngine().value(ins.equity("AAPL"), make_snap())
    assert val.ValuationValidator().validate_result(r) == []


def test_validator_reconcile_agree():
    v = val.ValuationEngine()
    a = v.value(call_opt(), make_snap())
    b = v.value(call_opt(), make_snap())
    assert val.ValuationValidator().reconcile(a, b) == []


# ─────────────────────────── reconciliation ────────────────────────────────

def test_recon_clean():
    r = val.ValuationEngine().value(ins.equity("AAPL"), make_snap())
    rep = recon.reconcile([r], {"AAPL": {"price": r.price}})
    assert rep.clean


def test_recon_price_mismatch():
    r = val.ValuationEngine().value(ins.equity("AAPL"), make_snap())
    rep = recon.reconcile([r], {"AAPL": {"price": r.price + 5}})
    assert rep.of_kind("price_mismatch")


def test_recon_missing_external():
    r = val.ValuationEngine().value(ins.equity("AAPL"), make_snap())
    rep = recon.reconcile([r], {})
    assert rep.of_kind("missing")


# ─────────────────────────── M16 / M17 integration ─────────────────────────

def test_m17_adapter_price_matches_engine_option():
    snap = make_snap()
    r = val.ValuationEngine().value(call_opt(), snap)
    t = (date(2027, 1, 5) - AS_OF).days / 365.0
    market = {"spot": 150.0, "strike": 150.0, "vol": 0.25,
              "rate": snap.rates["USD"].zero_rate(t), "div_yield": 0.0, "t": t}
    px = val.M18Pricer().price(call_opt(), market)
    assert px == pytest.approx(r.price, abs=0.2)


def test_m17_adapter_equity_price():
    assert val.M18Pricer().price(ins.equity("AAPL"), {"mark": 150.0}) == 150.0


def test_m17_adapter_greeks_return_m17_type():
    from aurelius.research.instruments.models import Greeks as M17G
    g = val.M18Pricer().greeks(call_opt(), {"spot": 150, "vol": 0.25, "rate": 0.03, "t": 1.0})
    assert isinstance(g, M17G) and 0 < g.delta < 1


def test_m17_adapter_american_price():
    px = val.M18Pricer().price(call_opt(), {"spot": 150, "vol": 0.25, "rate": 0.03,
                                            "t": 1.0, "american": True, "steps": 100})
    assert px > 0


def test_m17_yield_adapter_ytm():
    b = ins.bond("UST", face=100.0, coupon=0.05, maturity=date(2029, 1, 5))
    prov = val.M18YieldProvider(settle=AS_OF)
    px = bonds.clean_price_from_yield(
        bonds.BondSpec(coupon=0.05, frequency=2, maturity=date(2029, 1, 5)), 0.05, AS_OF)
    assert prov.ytm(b, px) == pytest.approx(0.05, abs=1e-4)


def test_m17_yield_adapter_duration():
    b = ins.bond("UST", face=100.0, coupon=0.05, maturity=date(2029, 1, 5))
    assert val.M18YieldProvider(settle=AS_OF).duration(b, 100.0) > 0


def test_m18_pricer_drops_into_m17_book_greeks():
    # M17 InstrumentBook risk consuming M18 greeks provider
    from aurelius.research.instruments import risk as m17risk
    b = ins.InstrumentBook(1_000_000.0)
    opt = ins.call("AAPL-C", underlying="AAPL", strike=150, expiry=date(2027, 1, 5))
    b.book_trade(opt, 10, 5.0)
    rep = m17risk.exposures(b, {"AAPL-C": 5.0}, greeks_provider=val.M18Pricer(),
                            market={"AAPL-C": {"spot": 150, "vol": 0.25, "rate": 0.03, "t": 1.0}})
    assert rep.gamma > 0


def test_m16_fx_reused_not_forked():
    # cross-currency valuation must call the M16 provider, not a new FX impl
    snap = make_snap(fx_provider=fxp())
    assert snap.fx_rate("EUR", "USD") == fxp().rate("EUR", "USD")
