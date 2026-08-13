"""AIDP M16 — Multi-Currency & FX Portfolio Book tests.

Deterministic, offline. Covers the currency model, FX rate providers/conventions,
conversions, multi-currency cash/valuation/settlement, cross-currency trades, FX
exposure/P&L/risk/stress, corporate actions, reconciliation, performance attribution,
serialization, registry, validation, backward compatibility with M15, determinism,
invariants, and edge cases.
"""

from __future__ import annotations

from datetime import date

import pytest

from mentisrex.research import fx
from mentisrex.research.fx import conversion as conv
from mentisrex.research.post_trade import PostTradeEngine, SettlementConfig
from mentisrex.research.post_trade import fingerprint as pt_fingerprint

D0 = date(2026, 1, 5)          # Monday
D1 = date(2026, 1, 6)


def static(**extra):
    r = {"EUR/USD": 1.10, "GBP/USD": 1.25, "JPY/USD": 0.0068, "INR/USD": 0.012, **extra}
    return fx.StaticFXRateProvider(r, pivot="USD")


def book(initial=None, provider=None, base="USD"):
    return fx.MultiCurrencyBook(base, provider or static(),
                                initial=initial or {"USD": 1_000_000.0},
                                settlement_config=SettlementConfig(default_days=2))


# ─────────────────────────── currency model ────────────────────────────────

def test_validate_code_upper():
    assert fx.validate_code("usd") == "USD"


def test_validate_code_strips():
    assert fx.validate_code("  eur ") == "EUR"


def test_invalid_code_rejected():
    with pytest.raises(ValueError):
        fx.validate_code("US")


def test_invalid_code_digits_rejected():
    with pytest.raises(ValueError):
        fx.validate_code("US1")


def test_is_valid_code_true():
    assert fx.is_valid_code("gbp")


def test_is_valid_code_false():
    assert not fx.is_valid_code("dollar")


def test_is_valid_code_non_string():
    assert not fx.is_valid_code(123)


def test_same_currency():
    assert fx.same_currency("usd", "USD")


def test_require_same_ok():
    assert fx.require_same("eur", "EUR") == "EUR"


def test_require_same_mismatch():
    with pytest.raises(fx.CurrencyMismatchError):
        fx.require_same("USD", "EUR")


def test_currency_normalizes():
    assert fx.Currency("usd").code == "USD"


def test_currency_pair_symbol():
    assert fx.CurrencyPair("EUR", "USD").symbol == "EUR/USD"


def test_currency_pair_inverse():
    assert fx.CurrencyPair("EUR", "USD").inverse().symbol == "USD/EUR"


# ─────────────────────────── FX rate conventions ───────────────────────────

def test_direct_rate():
    assert static().rate("EUR", "USD") == pytest.approx(1.10)


def test_inverse_rate():
    assert static().rate("USD", "EUR") == pytest.approx(1 / 1.10)


def test_identity_rate():
    assert static().rate("USD", "USD") == 1.0


def test_rate_inversion_invariant():
    p = static()
    assert p.rate("EUR", "USD") * p.rate("USD", "EUR") == pytest.approx(1.0, abs=1e-12)


def test_cross_rate():
    # EUR/GBP via USD pivot = (USD per EUR) * (GBP per USD) = 1.10/1.25
    assert static().rate("EUR", "GBP") == pytest.approx(1.10 / 1.25)


def test_cross_rate_inversion():
    p = static()
    assert p.rate("EUR", "GBP") * p.rate("GBP", "EUR") == pytest.approx(1.0, abs=1e-9)


def test_direction_direct():
    _, d, _ = static().resolve("EUR", "USD")
    assert d.value == "direct"


def test_direction_inverse():
    _, d, _ = static().resolve("USD", "EUR")
    assert d.value == "inverse"


def test_direction_cross():
    _, d, _ = static().resolve("EUR", "GBP")
    assert d.value == "cross"


def test_direction_identity():
    _, d, _ = static().resolve("USD", "USD")
    assert d.value == "identity"


def test_spot_returns_fxrate():
    r = static().spot("EUR", "USD")
    assert r.pair.symbol == "EUR/USD" and r.rate == pytest.approx(1.10)


def test_snapshot():
    snap = static().snapshot(["EUR", "GBP"], "USD")
    assert snap.rates["EUR/USD"] == pytest.approx(1.10)
    assert snap.base == "USD"


def test_fxrate_convert():
    r = fx.FXRate(fx.CurrencyPair("EUR", "USD"), 1.10)
    assert r.convert(100) == pytest.approx(110)


def test_fxrate_inverse_model():
    inv = fx.FXRate(fx.CurrencyPair("EUR", "USD"), 1.10).inverse()
    assert inv.pair.symbol == "USD/EUR" and inv.rate == pytest.approx(1 / 1.10)


# ─────────────────────────── rate providers ────────────────────────────────

def test_static_missing_rate():
    with pytest.raises(fx.MissingFXRateError):
        fx.StaticFXRateProvider({"EUR/USD": 1.1}).rate("EUR", "GBP")


def test_zero_rate_rejected():
    with pytest.raises(fx.InvalidFXRateError):
        fx.StaticFXRateProvider({"EUR/USD": 0.0}).rate("EUR", "USD")


def test_negative_rate_rejected():
    with pytest.raises(fx.InvalidFXRateError):
        fx.StaticFXRateProvider({"EUR/USD": -1.1}).rate("EUR", "USD")


def test_historical_as_of():
    p = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10, D1: 1.20}}, pivot="USD")
    assert p.rate("EUR", "USD", as_of=D0) == pytest.approx(1.10)
    assert p.rate("EUR", "USD", as_of=D1) == pytest.approx(1.20)


def test_historical_before_first():
    p = fx.HistoricalFXRateProvider({"EUR/USD": {D1: 1.20}}, pivot="USD")
    with pytest.raises(fx.MissingFXRateError):
        p.rate("EUR", "USD", as_of=D0)


def test_historical_latest_when_none():
    p = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10, D1: 1.20}})
    assert p.rate("EUR", "USD") == pytest.approx(1.20)


def test_historical_staleness_raises():
    p = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10}}, max_staleness_days=1)
    with pytest.raises(fx.StaleFXRateError):
        p.rate("EUR", "USD", as_of=date(2026, 2, 1))


def test_historical_staleness_ok():
    p = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10}}, max_staleness_days=5)
    assert p.rate("EUR", "USD", as_of=date(2026, 1, 8)) == pytest.approx(1.10)


def test_mock_deterministic():
    a = fx.DeterministicMockFXProvider("USD")
    b = fx.DeterministicMockFXProvider("USD")
    assert a.rate("EUR", "USD") == b.rate("EUR", "USD")


def test_mock_inversion():
    p = fx.DeterministicMockFXProvider("USD")
    assert p.rate("EUR", "USD") * p.rate("USD", "EUR") == pytest.approx(1.0, abs=1e-12)


def test_mock_cross_inversion():
    p = fx.DeterministicMockFXProvider("USD")
    assert p.rate("EUR", "GBP") * p.rate("GBP", "EUR") == pytest.approx(1.0, abs=1e-9)


def test_mock_seeds():
    p = fx.DeterministicMockFXProvider("USD", seeds={"EUR": 1.15})
    assert p.rate("EUR", "USD") == pytest.approx(1.15)


def test_mock_drift_dated():
    p = fx.DeterministicMockFXProvider("USD", seeds={"EUR": 1.10}, drift=0.1)
    assert p.rate("EUR", "USD", as_of=D0) != p.rate("EUR", "USD", as_of=date(2026, 6, 1))


def test_production_adapter_interface():
    with pytest.raises(NotImplementedError):
        fx.ProductionFXRateAdapter().rate("EUR", "USD")


# ─────────────────────────── conversions ───────────────────────────────────

def test_convert_amount():
    c = conv.convert(static(), 100, "EUR", "USD")
    assert c.to_amount == pytest.approx(110)


def test_convert_same_currency_identity():
    c = conv.convert(static(), 100, "USD", "USD")
    assert c.rate == 1.0 and c.direction.value == "identity"


def test_convert_to_target():
    c = conv.convert_to_target(static(), 110, "USD", "EUR")
    # need enough USD to obtain 110 EUR
    assert c.to_amount == pytest.approx(110)
    assert c.from_currency == "USD" and c.to_currency == "EUR"


def test_round_trip_zero_error():
    assert conv.round_trip_error(static(), 1000, "EUR", "USD") == pytest.approx(0.0, abs=1e-9)


def test_multi_hop_conversion():
    c = conv.convert(static(), 100, "EUR", "GBP")
    assert c.direction.value == "cross"
    assert c.to_amount == pytest.approx(100 * 1.10 / 1.25)


def test_conversion_dict_round_trip():
    c = conv.convert(static(), 100, "EUR", "USD", as_of=D0)
    back = conv.conversion_from_dict(conv.conversion_to_dict(c))
    assert back == c


# ─────────────────────────── book / cross-currency trades ──────────────────

def test_book_single_currency_trade():
    b = book()
    b.book_fill(security_id="AAPL", quantity=100, price=150.0, currency="USD", trade_date=D0)
    assert b.books["USD"].accounting.shares("AAPL") == 100


def test_usd_security_usd_cash():
    b = book()
    b.book_fill(security_id="AAPL", quantity=10, price=100.0, currency="USD",
                funding_currency="USD", trade_date=D0)
    assert b.currencies() == ["USD"]
    assert b.books["USD"].accounting.cash == pytest.approx(1_000_000 - 1000)


def test_eur_security_usd_cash_creates_eur_book():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    assert "EUR" in b.currencies()
    assert b.books["EUR"].accounting.shares("SAP") == 100


def test_eur_funded_from_usd_moves_usd_cash():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    # 5000 EUR needed → 5000/ (1/1.10) USD = 5500 USD
    assert b.books["USD"].accounting.cash == pytest.approx(1_000_000 - 5500)


def test_eur_funded_leaves_eur_cash_flat():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    assert b.books["EUR"].accounting.cash == pytest.approx(0.0, abs=1e-6)


def test_inr_security_usd_cash():
    b = book()
    b.book_fill(security_id="INFY", quantity=1000, price=1500.0, currency="INR",
                funding_currency="USD", trade_date=D0)
    assert b.books["INR"].accounting.shares("INFY") == 1000


def test_eur_proceeds_retained_in_eur():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    b.book_fill(security_id="SAP", quantity=-100, price=55.0, currency="EUR", trade_date=D0)
    # proceeds stay in EUR; no conversion
    assert b.books["EUR"].accounting.cash == pytest.approx(100_000 + 500)
    assert len(b.conversions) == 0


def test_eur_proceeds_converted_to_usd():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=-100, price=55.0, currency="EUR", trade_date=D0)
    b.convert(amount=5500, from_currency="EUR", to_currency="USD", when=D0)
    assert b.books["EUR"].accounting.cash == pytest.approx(100_000 + 5500 - 5500)
    assert b.books["USD"].accounting.cash == pytest.approx(1_000_000 + 5500 * 1.10)


def test_gbp_settlement_funded_from_usd():
    b = book()
    b.book_fill(security_id="LLOY", quantity=1000, price=0.5, currency="GBP",
                funding_currency="USD", trade_date=D0)
    assert b.books["GBP"].accounting.shares("LLOY") == 1000


def test_security_currency_mismatch_rejected():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    with pytest.raises(fx.CurrencyMismatchError):
        b.book_fill(security_id="SAP", quantity=50, price=51.0, currency="USD", trade_date=D0)


def test_conversion_recorded():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    assert len(b.conversions) == 1
    assert b.conversions[0].reason == "trade_funding"


def test_base_book_always_exists():
    b = fx.MultiCurrencyBook("USD", static(), initial={"EUR": 100.0})
    assert "USD" in b.currencies()


# ─────────────────────────── multi-currency cash ───────────────────────────

def test_currency_balances_independent():
    b = book(initial={"USD": 500_000.0, "EUR": 200_000.0})
    bals = fx.settlement_by_currency(b)  # just ensure book set up
    from mentisrex.research.fx.multi_currency_cash import currency_balances
    cb = currency_balances(b)
    assert cb["USD"].economic == pytest.approx(500_000)
    assert cb["EUR"].economic == pytest.approx(200_000)
    assert bals.base_currency == "USD"


def test_multi_currency_cash_base_total():
    b = book(initial={"USD": 500_000.0, "EUR": 200_000.0})
    mc = fx.MultiCurrencyBook  # noqa: F841
    m = __import__("mentisrex.research.fx.multi_currency_cash", fromlist=["multi_currency_cash"])
    res = m.multi_currency_cash(b, as_of=D0)
    assert res.total_base_economic == pytest.approx(500_000 + 200_000 * 1.10)


def test_cash_not_collapsed():
    b = book(initial={"USD": 500_000.0, "EUR": 200_000.0})
    m = __import__("mentisrex.research.fx.multi_currency_cash", fromlist=["currency_balances"])
    cb = m.currency_balances(b)
    assert set(cb) == {"USD", "EUR"}


# ─────────────────────────── valuation ─────────────────────────────────────

def test_valuation_base_total():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    v = fx.valuation(b, as_of=D0)
    assert v.total_base == pytest.approx(1_000_000 + 100_000 * 1.10)


def test_valuation_with_prices():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    v = fx.valuation(b, as_of=D0, prices={"SAP": 52.0})
    # EUR local: cash (100000-5000) + positions (5200) = 100200; base *1.10
    assert v.by_currency["EUR"].total_local == pytest.approx(100_200)
    assert v.by_currency["EUR"].total_base == pytest.approx(100_200 * 1.10)


def test_valuation_cash_positions_split():
    b = book(initial={"USD": 1_000_000.0})
    b.book_fill(security_id="AAPL", quantity=100, price=150.0, currency="USD", trade_date=D0)
    b.mark({"AAPL": 160.0})
    v = fx.valuation(b, as_of=D0)
    assert v.positions_base == pytest.approx(16000)
    assert v.cash_base == pytest.approx(1_000_000 - 15000)


def test_base_value_helper():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    assert fx.base_value(b, as_of=D0) == pytest.approx(1_000_000 + 110_000)


def test_valuation_base_rate_one():
    b = book()
    assert fx.valuation(b, as_of=D0).by_currency["USD"].fx_rate_to_base == 1.0


# ─────────────────────────── FX exposure ───────────────────────────────────

def test_exposure_base_currency_excluded():
    b = book(initial={"USD": 1_000_000.0})
    assert fx.fx_exposure(b, as_of=D0).by_currency == {}


def test_exposure_by_currency():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    exp = fx.fx_exposure(b, as_of=D0)
    assert exp.by_currency["EUR"].net_base == pytest.approx(110_000)
    assert exp.largest_currency == "EUR"


def test_exposure_gross_net():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0, "GBP": 50_000.0})
    exp = fx.fx_exposure(b, as_of=D0)
    assert exp.gross == pytest.approx(110_000 + 62_500)
    assert exp.net == pytest.approx(110_000 + 62_500)


def test_exposure_cash_vs_security_split():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    b.mark({"SAP": 50.0})
    exp = fx.fx_exposure(b, as_of=D0)
    e = exp.by_currency["EUR"]
    assert e.security_exposure_base == pytest.approx(5000 * 1.10)
    assert e.cash_exposure_base == pytest.approx(95_000 * 1.10)


def test_exposure_hedge_nets():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.add_hedge(fx.make_forward("EUR", 110_000))
    exp = fx.fx_exposure(b, as_of=D0)
    assert exp.by_currency["EUR"].net_base == pytest.approx(0.0, abs=1e-6)


def test_exposure_settlement_component():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    exp = fx.fx_exposure(b, as_of=D0)
    assert exp.by_currency["EUR"].settlement_exposure_base > 0


# ─────────────────────────── FX P&L ────────────────────────────────────────

def test_fx_pnl_reconciles():
    prov = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10, D1: 1.20}}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    s0 = fx.value_snapshot(b, as_of=D0)
    s1 = fx.value_snapshot(b, as_of=D1)
    rep = fx.fx_pnl(b, s0, s1)
    assert rep.reconciles


def test_fx_pnl_pure_fx_move():
    prov = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10, D1: 1.20}}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    s0 = fx.value_snapshot(b, as_of=D0)
    s1 = fx.value_snapshot(b, as_of=D1)
    rep = fx.fx_pnl(b, s0, s1)
    # only EUR rate changed, no position change → all in fx term
    assert rep.fx_pnl == pytest.approx(100_000 * (1.20 - 1.10))
    assert rep.local_pnl == pytest.approx(0.0)


def test_fx_pnl_decomposition_sums():
    prov = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10, D1: 1.20}}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"EUR": 100_000.0})
    s0 = fx.value_snapshot(b, as_of=D0)
    s1 = fx.value_snapshot(b, as_of=D1)
    rep = fx.fx_pnl(b, s0, s1)
    assert rep.total_pnl == pytest.approx(rep.local_pnl + rep.fx_pnl + rep.interaction)


def test_fx_pnl_base_currency_no_fx():
    b = book()
    s0 = fx.value_snapshot(b, as_of=D0)
    s1 = fx.value_snapshot(b, as_of=D1)
    rep = fx.fx_pnl(b, s0, s1)
    assert rep.fx_pnl == pytest.approx(0.0)


# ─────────────────────────── realized FX P&L ───────────────────────────────

def test_realized_fx_pnl_on_round_trip_gain():
    prov = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10, D1: 1.20}}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"USD": 1_000_000.0})
    b.convert(needed_to=100_000, from_currency="USD", to_currency="EUR", when=D0)
    b.convert(amount=100_000, from_currency="EUR", to_currency="USD", when=D1)
    assert b.realized_fx_pnl == pytest.approx((1.20 - 1.10) * 100_000)


def test_realized_fx_pnl_zero_same_rate():
    b = book()
    b.convert(needed_to=100_000, from_currency="USD", to_currency="EUR", when=D0)
    b.convert(amount=100_000, from_currency="EUR", to_currency="USD", when=D0)
    assert b.realized_fx_pnl == pytest.approx(0.0, abs=1e-6)


def test_base_realized_includes_fx():
    prov = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10, D1: 1.20}}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"USD": 1_000_000.0})
    b.convert(needed_to=100_000, from_currency="USD", to_currency="EUR", when=D0)
    b.convert(amount=100_000, from_currency="EUR", to_currency="USD", when=D1)
    assert fx.base_realized_pnl(b, as_of=D1) == pytest.approx(b.realized_fx_pnl)


# ─────────────────────────── settlement ────────────────────────────────────

def test_settle_per_currency():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    settled = b.settle(date(2026, 1, 8))
    assert any(settled[c] for c in settled)


def test_settlement_by_currency_report():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    rep = fx.settlement_by_currency(b, as_of=D0)
    assert rep.by_currency["EUR"]["pending"] == 1


def test_fund_settlement_creates_conversion():
    b = book()
    tid = b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    n0 = len(b.conversions)
    b.fund_settlement("EUR", tid, "USD", when=D0) if False else fx.fund_settlement(
        b, "EUR", tid, "USD", when=D0)
    assert len(b.conversions) == n0 + 1


def test_failed_fx_funding_raises():
    # provider without EUR->USD... use a provider missing the needed cross
    prov = fx.StaticFXRateProvider({"GBP/USD": 1.25}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"USD": 1_000_000.0})
    # book an EUR trade by pre-funding EUR so no rate needed at booking
    b2 = fx.MultiCurrencyBook("USD", prov, initial={"EUR": 100_000.0})
    tid = b2.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    with pytest.raises(fx.MissingFXRateError):
        fx.fund_settlement(b2, "EUR", tid, "USD", when=D0)
    assert b is not None


def test_obligations_by_currency():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    ob = fx.obligations_by_currency(b)
    assert any(k[0] == "EUR" for k in ob)


def test_different_trade_and_settlement_currency():
    # trade in EUR, funded/settled from USD base
    b = book()
    tid = b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                      funding_currency="USD", trade_date=D0)
    fx.fund_settlement(b, "EUR", tid, "USD", when=D0)
    b.settle(date(2026, 1, 8))
    assert b.books["EUR"].trades[tid].value == "settled"


def test_fund_settlement_inflow_noop():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    tid = b.book_fill(security_id="SAP", quantity=-100, price=50.0, currency="EUR", trade_date=D0)
    assert fx.fund_settlement(b, "EUR", tid, "USD", when=D0) is None


# ─────────────────────────── corporate actions ─────────────────────────────

def test_dividend_in_security_currency():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    from mentisrex.research.post_trade import DividendEvent
    fx.apply_corporate_action(b, DividendEvent("D1", "SAP", amount_per_share=2.0, ex_date=D0))
    # dividend lands in EUR book
    assert b.books["EUR"].accounting.cash == pytest.approx(100_000 - 5000 + 200)


def test_dividend_converted_to_base():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    from mentisrex.research.post_trade import DividendEvent
    n0 = len(b.conversions)
    fx.apply_corporate_action(b, DividendEvent("D1", "SAP", amount_per_share=2.0, ex_date=D0),
                              receive_currency="USD")
    assert len(b.conversions) == n0 + 1


def test_split_multi_currency():
    b = book(initial={"EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    from mentisrex.research.post_trade import SplitEvent
    fx.apply_corporate_action(b, SplitEvent("S1", "SAP", ratio=2.0, ex_date=D0))
    assert b.books["EUR"].accounting.shares("SAP") == 200


# ─────────────────────────── accounting ────────────────────────────────────

def test_position_accounting_base_translation():
    b = book(initial={"EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    b.mark({"SAP": 55.0})
    pa = fx.position_accounting(b, "SAP", as_of=D0)
    assert pa["local_unrealized_pnl"] == pytest.approx(500)
    assert pa["base_unrealized_pnl"] == pytest.approx(500 * 1.10)
    assert pa["currency"] == "EUR"


def test_position_accounting_unknown():
    assert fx.position_accounting(book(), "NOPE") is None


def test_base_unrealized_pnl_translates():
    b = book(initial={"EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    b.mark({"SAP": 60.0})
    assert fx.base_unrealized_pnl(b, as_of=D0) == pytest.approx(1000 * 1.10)


# ─────────────────────────── reconciliation ────────────────────────────────

def test_reconcile_clean():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    assert fx.reconcile(b, as_of=D0).ok


def test_reconcile_detects_bad_conversion():
    from mentisrex.research.fx.models import ConversionDirection, FXConversion
    b = book()
    b.conversions.append(FXConversion("BAD", "EUR", "USD", 100, 999, 1.10,
                                      ConversionDirection.DIRECT, D0, "static"))
    r = fx.reconcile(b, as_of=D0)
    assert not r.ok and "fx_conversion_mismatch" in r.categories


def test_reconcile_detects_bad_rate():
    from mentisrex.research.fx.models import ConversionDirection, FXConversion
    b = book()
    b.conversions.append(FXConversion("BAD", "EUR", "USD", 100, -110, -1.10,
                                      ConversionDirection.DIRECT, D0, "static"))
    r = fx.reconcile(b, as_of=D0)
    assert "wrong_fx_rate" in r.categories


def test_reconcile_broker_positions():
    from mentisrex.research.paper_trading.models import BrokerAccount, BrokerPosition
    b = book(initial={"EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR", trade_date=D0)
    acct = BrokerAccount(account_id="x", cash=b.books["EUR"].accounting.cash,
                         positions={"SAP": BrokerPosition("SAP", 90, 50.0)})
    r = fx.reconcile(b, broker_accounts={"EUR": acct}, as_of=D0)
    assert not r.ok


# ─────────────────────────── risk & stress ─────────────────────────────────

def test_fx_risk_report():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    rep = fx.fx_risk_report(b, vols={"EUR": 0.08}, as_of=D0)
    assert rep.by_currency["EUR"]["vol"] == 0.08
    assert rep.fx_var > 0


def test_fx_var_scales_with_exposure():
    small = book(initial={"USD": 1_000_000.0, "EUR": 10_000.0})
    big = book(initial={"USD": 1_000_000.0, "EUR": 500_000.0})
    r_small = fx.fx_risk_report(small, vols={"EUR": 0.1}, as_of=D0)
    r_big = fx.fx_risk_report(big, vols={"EUR": 0.1}, as_of=D0)
    assert r_big.fx_var > r_small.fx_var


def test_fx_concentration():
    b = book(initial={"USD": 100_000.0, "EUR": 100_000.0})
    rep = fx.fx_risk_report(b, vols={"EUR": 0.1}, as_of=D0)
    assert rep.largest_currency == "EUR"
    assert 0 < rep.concentration <= 1


def test_fx_limits_violation():
    b = book(initial={"USD": 100_000.0, "EUR": 500_000.0})
    v = fx.check_fx_limits(b, fx.FXLimits(max_currency_share=0.2), as_of=D0)
    assert any(x["limit"] == "max_currency_share" for x in v)


def test_fx_limits_ok():
    b = book(initial={"USD": 1_000_000.0, "EUR": 10_000.0})
    v = fx.check_fx_limits(b, fx.FXLimits(max_currency_share=0.5), as_of=D0)
    assert v == []


def test_fx_gross_limit():
    b = book(initial={"USD": 100_000.0, "EUR": 300_000.0, "GBP": 300_000.0})
    v = fx.check_fx_limits(b, fx.FXLimits(max_gross_fx=0.5), as_of=D0)
    assert any(x["limit"] == "max_gross_fx" for x in v)


def test_stress_eur_up():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    res = fx.apply_fx_stress(b, fx.CURRENCY_SCENARIOS["eur_up_10"], as_of=D0)
    assert res.pnl_base == pytest.approx(110_000 * 0.10)


def test_stress_usd_up_hits_foreign():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    res = fx.apply_fx_stress(b, fx.CURRENCY_SCENARIOS["usd_up_10"], as_of=D0)
    # USD strengthens 10% → EUR base value down 10%
    assert res.pnl_base == pytest.approx(-110_000 * 0.10)


def test_stress_simultaneous():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0, "INR": 1_000_000.0})
    scen = fx.FXStressScenario("multi", {"EUR": 0.05, "INR": -0.10})
    res = fx.apply_fx_stress(b, scen, as_of=D0)
    assert res.by_currency["EUR"] > 0 and res.by_currency["INR"] < 0


def test_stress_test_all_scenarios():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    results = fx.stress_test(b, as_of=D0)
    assert len(results) == len(fx.CURRENCY_SCENARIOS)


def test_stress_base_only_no_pnl():
    b = book(initial={"USD": 1_000_000.0})
    res = fx.apply_fx_stress(b, fx.CURRENCY_SCENARIOS["eur_up_10"], as_of=D0)
    assert res.pnl_base == pytest.approx(0.0)


# ─────────────────────────── hedging ───────────────────────────────────────

def test_make_forward():
    h = fx.make_forward("EUR", 100_000)
    assert h.instrument == "forward" and h.currency == "EUR"


def test_make_future_swap():
    assert fx.make_future("EUR", 1).instrument == "future"
    assert fx.make_swap("EUR", 1).instrument == "swap"


def test_unhedged_by_currency():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.add_hedge(fx.make_forward("EUR", 50_000))
    u = fx.unhedged_by_currency(b, as_of=D0)
    assert u["EUR"] == pytest.approx(110_000 - 50_000)


# ─────────────────────────── performance attribution ───────────────────────

def test_currency_attribution_reconciles():
    prov = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10, D1: 1.20}}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    s0 = fx.value_snapshot(b, as_of=D0)
    s1 = fx.value_snapshot(b, as_of=D1)
    att = fx.currency_attribution(b, s0, s1)
    assert att.reconciles
    assert att.total_return == pytest.approx(att.local_return + att.fx_return + att.interaction)


# ─────────────────────────── reporting ─────────────────────────────────────

def test_cash_by_currency_report():
    b = book(initial={"USD": 500_000.0, "EUR": 200_000.0})
    rep = fx.cash_by_currency_report(b, as_of=D0)
    assert set(rep.balances) == {"USD", "EUR"}
    assert rep.total_base == pytest.approx(500_000 + 200_000 * 1.10)


def test_multi_currency_portfolio_report():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    rep = fx.multi_currency_portfolio_report(b, as_of=D0)
    assert rep.n_currencies == 2
    assert rep.value.total_base == pytest.approx(1_110_000)
    assert rep.reconciliation.ok


def test_portfolio_report_with_pnl():
    prov = fx.HistoricalFXRateProvider({"EUR/USD": {D0: 1.10, D1: 1.20}}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"EUR": 100_000.0})
    s0 = fx.value_snapshot(b, as_of=D0)
    s1 = fx.value_snapshot(b, as_of=D1)
    rep = fx.multi_currency_portfolio_report(b, as_of=D1, snap0=s0, snap1=s1)
    assert rep.pnl is not None and rep.pnl.reconciles


# ─────────────────────────── serialization ─────────────────────────────────

def test_serialization_round_trip_conversions():
    from mentisrex.research.fx import serialization
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    d = serialization.to_dict(b, as_of=D0)
    restored = [conv.conversion_from_dict(c) for c in d["conversions"]]
    assert restored == b.conversions


def test_serialization_json_stable():
    from mentisrex.research.fx import serialization
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    assert serialization.to_json(b, as_of=D0) == serialization.to_json(b, as_of=D0)


def test_serialization_preserves_currencies():
    from mentisrex.research.fx import serialization
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    d = serialization.to_dict(b, as_of=D0)
    assert set(d["currencies"]) == {"USD", "EUR"}


# ─────────────────────────── registry ──────────────────────────────────────

def test_attach_fx(tmp_path):
    from types import SimpleNamespace

    store = SimpleNamespace(rows={})
    store.insert = lambda exp: store.rows.__setitem__(exp.experiment_id, exp)
    registry = SimpleNamespace(store=store, load=lambda _id: None)
    exp = SimpleNamespace(experiment_id="E1", metrics={}, notes="", artifacts=[])

    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    out = fx.attach_fx(registry, exp, b, artifacts_dir=str(tmp_path), as_of=D0)
    assert out["hash"]
    assert exp.metrics["FXBaseValue"] == pytest.approx(1_110_000)
    assert (tmp_path / "fx_session.json").exists()


# ─────────────────────────── validation ────────────────────────────────────

def test_validate_book_clean():
    b = book()
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    assert fx.validate_book(b).ok


def test_validate_book_detects_bad_conversion():
    from mentisrex.research.fx.models import ConversionDirection, FXConversion
    b = book()
    b.conversions.append(FXConversion("BAD", "EUR", "USD", 100, 999, 1.10,
                                      ConversionDirection.DIRECT, D0, "static"))
    assert not fx.validate_book(b).ok


def test_validate_rate_inversion():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=1, price=1.0, currency="EUR", trade_date=D0)
    assert fx.validate_book(b).ok


# ─────────────────────────── backward compatibility ────────────────────────

def _m15_engine():
    eng = PostTradeEngine(1_000_000.0, settlement_config=SettlementConfig(default_days=2))
    eng.book_fill(security_id="AAPL", quantity=100, price=150.0, cost=1.0, trade_date=D0)
    eng.book_fill(security_id="MSFT", quantity=50, price=300.0, cost=1.0, trade_date=D0)
    eng.settle(date(2026, 1, 8))
    return eng


def _single_ccy_book():
    b = fx.MultiCurrencyBook("USD", static(), initial={"USD": 1_000_000.0},
                             settlement_config=SettlementConfig(default_days=2))
    b.book_fill(security_id="AAPL", quantity=100, price=150.0, cost=1.0, currency="USD", trade_date=D0)
    b.book_fill(security_id="MSFT", quantity=50, price=300.0, cost=1.0, currency="USD", trade_date=D0)
    b.settle(date(2026, 1, 8))
    return b


def test_single_currency_matches_m15_cash():
    assert _single_ccy_book().books["USD"].accounting.cash == pytest.approx(_m15_engine().accounting.cash)


def test_single_currency_matches_m15_value():
    assert _single_ccy_book().books["USD"].accounting.value() == pytest.approx(_m15_engine().accounting.value())


def test_single_currency_matches_m15_fingerprint():
    assert pt_fingerprint(_single_ccy_book().books["USD"]) == pt_fingerprint(_m15_engine())


def test_single_currency_no_fx_exposure():
    assert _single_ccy_book().currencies() == ["USD"]
    assert fx.fx_exposure(_single_ccy_book(), as_of=D0).by_currency == {}


def test_single_currency_base_value_equals_local():
    b = _single_ccy_book()
    assert fx.base_value(b, as_of=D0) == pytest.approx(b.books["USD"].accounting.value())


# ─────────────────────────── determinism / invariants ──────────────────────

def _build():
    b = book(initial={"USD": 1_000_000.0, "EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    b.book_fill(security_id="AAPL", quantity=100, price=150.0, currency="USD", trade_date=D0)
    b.settle(date(2026, 1, 8))
    return b


def test_determinism_fingerprint():
    assert fx.check_determinism(_build)


def test_fingerprint_changes_with_trade():
    a = _build()
    b = _build()
    b.book_fill(security_id="SAP", quantity=10, price=51.0, currency="EUR",
                funding_currency="USD", trade_date=D0)
    assert fx.fingerprint(a) != fx.fingerprint(b)


def test_invariant_convert_round_trip():
    p = static()
    for a, c in [("EUR", "USD"), ("USD", "EUR"), ("EUR", "GBP"), ("GBP", "JPY")]:
        assert conv.round_trip_error(p, 12345.0, a, c) == pytest.approx(0.0, abs=1e-6)


def test_invariant_cash_sum_equals_base():
    b = book(initial={"USD": 500_000.0, "EUR": 200_000.0, "GBP": 100_000.0})
    m = __import__("mentisrex.research.fx.multi_currency_cash", fromlist=["currency_balances"])
    cb = m.currency_balances(b)
    manual = sum(bal.economic * b.base_rate(c, D0) for c, bal in cb.items())
    assert fx.valuation(b, as_of=D0).cash_base == pytest.approx(manual)


def test_invariant_pnl_reconciles_multi_currency():
    prov = fx.HistoricalFXRateProvider(
        {"EUR/USD": {D0: 1.10, D1: 1.15}, "GBP/USD": {D0: 1.25, D1: 1.30}}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"USD": 1e6, "EUR": 1e5, "GBP": 1e5})
    s0 = fx.value_snapshot(b, as_of=D0)
    s1 = fx.value_snapshot(b, as_of=D1)
    assert fx.fx_pnl(b, s0, s1).reconciles


def test_diagnostics_shape():
    d = fx.diagnostics(_build(), as_of=D0)
    assert d["n_currencies"] == 2 and "per_book_fingerprint" in d


# ─────────────────────────── edge cases ────────────────────────────────────

def test_same_currency_conversion_no_pnl():
    b = book()
    b.convert(amount=1000, from_currency="USD", to_currency="USD", when=D0)
    assert b.realized_fx_pnl == 0.0


def test_zero_fx_rate_book_rejects():
    prov = fx.StaticFXRateProvider({"EUR/USD": 0.0}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"USD": 1e6})
    with pytest.raises(fx.InvalidFXRateError):
        b.convert(amount=100, from_currency="USD", to_currency="EUR", when=D0)


def test_missing_rate_book_rejects():
    prov = fx.StaticFXRateProvider({"GBP/USD": 1.25}, pivot="USD")
    b = fx.MultiCurrencyBook("USD", prov, initial={"USD": 1e6})
    with pytest.raises(fx.MissingFXRateError):
        b.convert(amount=100, from_currency="USD", to_currency="EUR", when=D0)


def test_partial_conversion():
    b = book()
    b.convert(needed_to=50_000, from_currency="USD", to_currency="EUR", when=D0)
    assert b.books["EUR"].accounting.cash == pytest.approx(50_000)


def test_weekend_settlement_skips():
    # trade Friday, T+2 settles Tuesday (skips weekend)
    b = book()
    tid = b.book_fill(security_id="SAP", quantity=100, price=50.0, currency="EUR",
                      trade_date=date(2026, 1, 9))  # Friday
    inst = b.books["EUR"].settlement.instructions[f"S-{tid}"]
    assert inst.settle_date == date(2026, 1, 13)  # Tuesday


def test_empty_book_valuation():
    b = fx.MultiCurrencyBook("USD", static(), initial={"USD": 1000.0})
    assert fx.base_value(b, as_of=D0) == pytest.approx(1000.0)


def test_multi_currency_negative_position():
    b = book(initial={"EUR": 100_000.0})
    b.book_fill(security_id="SAP", quantity=-100, price=50.0, currency="EUR", trade_date=D0)
    assert b.books["EUR"].accounting.shares("SAP") == -100
