"""Phase-8 construction tests: aggregation, sizing, optimization, exposure, seam."""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np

from mentisrex.backtesting.portfolio.state import PortfolioState
from mentisrex.construction import (
    ExposureLimits,
    Method,
    PortfolioBuilder,
    RawSignal,
    SignalAggregator,
    SignalSource,
    apply_limits,
    condition_number,
    constrained_min_variance,
    equal_weight,
    max_sharpe,
    min_variance,
    risk_parity,
    sample_covariance,
    volatility_target,
)

# ── aggregation ───────────────────────────────────────────────────────────────


def test_aggregation_zscores_and_blends():
    sigs = [
        RawSignal("AAA", SignalSource.MOMENTUM, 2.0),
        RawSignal("BBB", SignalSource.MOMENTUM, 0.0),
        RawSignal("AAA", SignalSource.ML, 1.0),
        RawSignal("BBB", SignalSource.ML, -1.0),
    ]
    alpha = SignalAggregator().combine(sigs)
    # AAA is the high name in both sources -> positive; BBB negative; symmetric.
    assert alpha["AAA"] > 0 > alpha["BBB"]
    assert math.isclose(alpha["AAA"], -alpha["BBB"], abs_tol=1e-9)


def test_aggregation_no_cross_section_is_zero():
    alpha = SignalAggregator().combine([RawSignal("AAA", SignalSource.MOMENTUM, 5.0)])
    assert alpha["AAA"] == 0.0  # one name -> no information


def test_aggregation_zero_dispersion_is_zero():
    sigs = [RawSignal("AAA", SignalSource.ML, 1.0), RawSignal("BBB", SignalSource.ML, 1.0)]
    alpha = SignalAggregator().combine(sigs)
    assert alpha == {"AAA": 0.0, "BBB": 0.0}


# ── sizing ────────────────────────────────────────────────────────────────────


def test_equal_weight_signs_and_sum():
    w = equal_weight({"AAA": 0.5, "BBB": -0.3, "CCC": 0.0})
    assert w == {"AAA": 0.5, "BBB": -0.5}  # CCC dropped (alpha 0); 1/N each
    assert abs(sum(abs(v) for v in w.values()) - 1.0) < 1e-9


def test_volatility_target_hits_target():
    # Independent assets, cov given -> scaled book should have ~target vol.
    syms = ["AAA", "BBB"]
    cov = np.diag([0.04, 0.09])  # ann var -> vols 0.2, 0.3
    vols = {"AAA": 0.2, "BBB": 0.3}
    w = volatility_target({"AAA": 1.0, "BBB": 1.0}, vols, target_vol=0.10, cov=(syms, cov))
    vec = np.array([w["AAA"], w["BBB"]])
    port_vol = math.sqrt(vec @ cov @ vec)
    assert abs(port_vol - 0.10) < 1e-9
    # inverse-vol: lower-vol AAA gets more weight
    assert w["AAA"] > w["BBB"] > 0


def test_risk_parity_equalizes_risk_contribution():
    cov = np.array([[0.04, 0.006], [0.006, 0.09]])
    syms = ["AAA", "BBB"]
    w = risk_parity(syms, cov, {"AAA": 1.0, "BBB": 1.0})
    vec = np.array([w["AAA"], w["BBB"]])
    sigma_w = cov @ vec
    rc = vec * sigma_w
    assert abs(rc[0] - rc[1]) < 1e-4  # equal risk contribution
    assert w["AAA"] > w["BBB"]  # lower-vol name gets more capital


# ── optimization ──────────────────────────────────────────────────────────────


def test_min_variance_prefers_low_vol():
    cov = np.diag([0.01, 0.25])  # AAA far less volatile
    w = min_variance(cov)
    assert abs(w.sum() - 1.0) < 1e-9
    assert w[0] > w[1]  # more weight to low-vol asset


def test_min_variance_survives_singular_cov():
    cov = np.array([[0.04, 0.04], [0.04, 0.04]])  # singular
    w = min_variance(cov)
    assert abs(w.sum() - 1.0) < 1e-6  # pinv fallback, still sums to 1


def test_max_sharpe_tilts_to_higher_mu():
    cov = np.eye(2) * 0.04
    w = max_sharpe(np.array([0.10, 0.02]), cov)
    assert w[0] > w[1]  # higher expected return -> higher weight


def test_constrained_respects_box():
    cov = np.diag([0.01, 0.25])
    w = constrained_min_variance(cov, lo=0.0, hi=0.6)
    assert abs(w.sum() - 1.0) < 1e-6
    assert (w >= -1e-9).all()
    assert (w <= 0.6 + 1e-6).all()


def test_condition_number_flags_singular():
    assert condition_number(np.array([[0.04, 0.04], [0.04, 0.04]])) == float("inf")


def test_sample_covariance_shape():
    rets = {"AAA": [0.01, -0.01, 0.02, 0.0], "BBB": [0.0, 0.01, -0.01, 0.02]}
    syms, cov = sample_covariance(rets)
    assert syms == ["AAA", "BBB"]
    assert cov.shape == (2, 2)


# ── exposure ──────────────────────────────────────────────────────────────────


def test_asset_cap_clips():
    w = apply_limits({"AAA": 0.5}, ExposureLimits(max_asset_weight=0.1, max_gross_leverage=1.0))
    assert abs(w["AAA"]) <= 0.1 + 1e-9


def test_sector_cap_scales_down():
    lim = ExposureLimits(max_asset_weight=0.5, max_sector_weight=0.3, max_gross_leverage=2.0)
    w = apply_limits({"AAA": 0.3, "BBB": 0.3}, lim, sector_map={"AAA": "T", "BBB": "T"})
    assert sum(abs(v) for v in w.values()) <= 0.3 + 1e-9  # sector gross <= cap


def test_gross_leverage_scaled():
    lim = ExposureLimits(max_asset_weight=1.0, max_gross_leverage=1.0)
    w = apply_limits({"AAA": 0.8, "BBB": -0.8}, lim)
    assert abs(sum(abs(v) for v in w.values()) - 1.0) < 1e-9


def test_correlation_haircut_delevers():
    lim = ExposureLimits(max_asset_weight=1.0, max_gross_leverage=1.0, correlation_threshold=0.7)
    base = {"AAA": 0.5, "BBB": 0.5}
    w = apply_limits(base, lim, avg_correlation=0.9)
    # budget = 1.0 * (1 - 0.9) = 0.1 -> heavily delevered
    assert abs(sum(abs(v) for v in w.values()) - 0.1) < 1e-9


# ── end-to-end seam (backtesting state + risk engine + orders) ─────────────────


def _state(price=100, n=3):
    s = PortfolioState(Decimal("1000000"))
    for i in range(n):
        s.position(f"S{i}").last_price = Decimal(str(price))
    return s


def _returns(syms, seed=1):
    import random

    r = random.Random(seed)
    return {s: [r.gauss(0.0003, 0.01) for _ in range(120)] for s in syms}


def test_builder_produces_screened_orders():
    syms = ["S0", "S1", "S2"]
    state = _state()
    signals = [
        RawSignal("S0", SignalSource.MOMENTUM, 1.5),
        RawSignal("S1", SignalSource.MOMENTUM, -0.5),
        RawSignal("S2", SignalSource.MOMENTUM, 0.3),
    ]
    prices = {s: Decimal("100") for s in syms}
    tp = PortfolioBuilder(method=Method.EQUAL_WEIGHT).build(signals, _returns(syms), prices, state)
    assert tp.orders  # orders emitted
    assert all(o.quantity > 0 for o in tp.orders)


def test_builder_risk_engine_rejects_when_halted():
    from mentisrex.risk import RiskEngine

    syms = ["S0", "S1", "S2"]
    state = _state()
    eng = RiskEngine()
    eng.trip("manual shutdown")  # kill switch on
    signals = [
        RawSignal(s, SignalSource.ML, v) for s, v in [("S0", 1.0), ("S1", -0.5), ("S2", 0.2)]
    ]
    prices = {s: Decimal("100") for s in syms}
    tp = PortfolioBuilder(method=Method.EQUAL_WEIGHT, risk_engine=eng).build(
        signals, _returns(syms), prices, state
    )
    assert tp.orders == []  # everything rejected by the kill switch
    assert tp.rejected  # and recorded


def test_demo_self_check():
    from mentisrex.construction import demo

    demo()
