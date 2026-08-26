"""build_orders: the target-book-vs-current-holdings diff at the broker seam.

Pure function, no network -- AlpacaSwingBroker itself is exercised only by
the M28 AlpacaPaperBroker suite it wraps (tests/paper/test_m28_alpaca_paper_broker.py),
since it adds no logic beyond a `time_in_force="cls"` payload over that
already-tested client.
"""
from __future__ import annotations

import pandas as pd
import pytest

from mentisrex.swing.execution import MIN_ORDER_USD, build_orders


def book(rows):
    return pd.DataFrame(rows, columns=["symbol", "weight", "reference_price"])


AS_OF = pd.Timestamp("2026-01-05")


def test_flat_to_target_buys_and_sells():
    b = book([("AAA", 0.02, 100.0), ("BBB", -0.02, 50.0)])
    os_ = build_orders(b, {}, nav=1_000_000.0, strategy="nightfall", as_of=AS_OF)
    by_symbol = {o.symbol: o for o in os_.orders}
    assert by_symbol["AAA"].side == "BUY"
    assert by_symbol["AAA"].quantity == 200  # 0.02 * 1e6 / 100
    assert by_symbol["BBB"].side == "SELL"
    assert by_symbol["BBB"].quantity == -400  # -0.02 * 1e6 / 50
    assert os_.suppressed == ()
    assert os_.missing_price == ()


def test_no_delta_when_already_at_target():
    b = book([("AAA", 0.02, 100.0)])
    os_ = build_orders(b, {"AAA": 200.0}, nav=1_000_000.0, strategy="nightfall", as_of=AS_OF)
    assert os_.orders == ()
    assert "AAA" in os_.suppressed


def test_small_delta_suppressed_below_min_order_usd():
    b = book([("AAA", 0.02, 100.0)])
    # current already within one share of target -> delta notional < $250
    os_ = build_orders(b, {"AAA": 199.0}, nav=1_000_000.0, strategy="nightfall", as_of=AS_OF)
    assert os_.orders == ()
    assert os_.suppressed == ("AAA",)


def test_missing_price_skips_trade_and_keeps_current_weight():
    b = book([("AAA", 0.02, float("nan"))])
    os_ = build_orders(b, {"AAA": 50.0}, nav=1_000_000.0, strategy="nightfall", as_of=AS_OF)
    assert os_.orders == ()
    assert os_.missing_price == ("AAA",)
    # current holding is untouched by an unpriceable name, but its dollar
    # contribution to realized weight cannot be computed without a price,
    # so it is left out of gross/net rather than guessed.
    assert os_.target_weights["AAA"] == 0.0


def test_stale_position_absent_from_target_is_flattened():
    b = book([("AAA", 0.0, 100.0)])
    os_ = build_orders(b, {"BBB": 100.0}, nav=1_000_000.0, strategy="nightfall", as_of=AS_OF)
    # BBB has no price anywhere in the target book -> can't be traded out
    # automatically; it is surfaced as missing_price rather than silently
    # dropped, so an operator sees it needs a manual close.
    assert "BBB" in os_.missing_price


def test_stale_position_flattened_when_price_available():
    b = book([("AAA", 0.0, 100.0), ("BBB", 0.0, 50.0)])
    os_ = build_orders(b, {"BBB": 100.0}, nav=1_000_000.0, strategy="nightfall", as_of=AS_OF)
    by_symbol = {o.symbol: o for o in os_.orders}
    assert by_symbol["BBB"].side == "SELL"
    assert by_symbol["BBB"].quantity == -100


def test_gross_and_net_reflect_only_realized_weights():
    b = book([("AAA", 0.02, 100.0), ("BBB", -0.02, 50.0)])
    os_ = build_orders(b, {}, nav=1_000_000.0, strategy="nightfall", as_of=AS_OF)
    assert os_.gross == pytest.approx(0.04)
    assert os_.net == pytest.approx(0.0)


def test_min_order_usd_default_is_250():
    assert MIN_ORDER_USD == 250.0
