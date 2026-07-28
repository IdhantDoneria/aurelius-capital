"""Tests for statistical feature library: mean_deviation_20, correlation_60, beta_60.

Module at 72% — the benchmark-dependent features (correlation_60, beta_60)
and edge cases for mean_deviation_20 (zero mean) are not covered.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aurelius.features.registry import Window
from aurelius.features import get


def _win(closes: list[float], market: list[float] | None = None) -> Window:
    d = [Decimal(str(c)) for c in closes]
    m = [Decimal(str(c)) for c in market] if market is not None else None
    return Window(
        open=d,
        high=[x + Decimal("1") for x in d],
        low=[x - Decimal("1") for x in d],
        close=d,
        volume=d,
        market=m,
    )


# ── mean_deviation_20 ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_mean_deviation_20_above_mean_positive():
    closes = [100.0] * 19 + [110.0]  # last bar above mean
    v = get("mean_deviation_20")(_win(closes))
    assert v is not None
    assert v > 0


@pytest.mark.unit
def test_mean_deviation_20_below_mean_negative():
    closes = [100.0] * 19 + [90.0]  # last bar below mean
    v = get("mean_deviation_20")(_win(closes))
    assert v is not None
    assert v < 0


@pytest.mark.unit
def test_mean_deviation_20_at_mean_zero():
    closes = [100.0] * 20  # flat; last bar = mean
    v = get("mean_deviation_20")(_win(closes))
    assert v == Decimal("0")


@pytest.mark.unit
def test_mean_deviation_20_insufficient_history_is_none():
    closes = [100.0] * 15
    v = get("mean_deviation_20")(_win(closes))
    assert v is None


@pytest.mark.unit
def test_mean_deviation_20_zero_mean_safe():
    # Mean of 0 → should return None, not raise ZeroDivisionError
    closes = [0.0] * 20
    # Window with zero-valued closes; mean=0, divisor would be 0
    # We construct manually to allow zero (normally gt=0 only applies to OHLCVIngest)
    from aurelius.features.registry import Window as W
    d = [Decimal("0")] * 20
    w = W(open=d, high=d, low=d, close=d, volume=d)
    v = get("mean_deviation_20")(w)
    assert v is None  # guarded against zero-mean


# ── correlation_60 ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_correlation_60_self_correlation_is_one():
    closes = [100 + i for i in range(62)]
    v = get("correlation_60")(_win(closes, market=closes))
    assert v is not None
    assert abs(v - Decimal("1")) < Decimal("0.001")


@pytest.mark.unit
def test_correlation_60_uncorrelated_series_not_one():
    # A series with alternating up/down vs its reverse: not 1.0
    # The correlation with itself is 1; a permuted version should differ.
    # We verify that a genuinely different market series gives a correlation != 1.
    closes = [100 + (i % 5) * 1.5 for i in range(62)]
    market = [100 + ((i + 2) % 5) * 1.5 for i in range(62)]  # phase-shifted
    v_self = get("correlation_60")(_win(closes, market=closes))
    v_shifted = get("correlation_60")(_win(closes, market=market))
    assert v_self is not None
    assert v_shifted is not None
    assert abs(v_self - Decimal("1")) < Decimal("0.001")  # self = 1
    assert v_shifted != v_self  # phase-shifted series differs


@pytest.mark.unit
def test_correlation_60_no_market_returns_none():
    closes = [100 + i for i in range(62)]
    v = get("correlation_60")(_win(closes, market=None))
    assert v is None


@pytest.mark.unit
def test_correlation_60_insufficient_history_returns_none():
    closes = [100.0] * 50
    v = get("correlation_60")(_win(closes, market=closes))
    assert v is None


@pytest.mark.unit
def test_correlation_60_flat_series_returns_none():
    closes = [100.0] * 62  # zero variance → StatisticsError → None
    v = get("correlation_60")(_win(closes, market=closes))
    assert v is None  # guarded: zero-variance leg


# ── beta_60 ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_beta_60_self_is_one():
    closes = [100 + i for i in range(62)]
    v = get("beta_60")(_win(closes, market=closes))
    assert v is not None
    assert abs(v - Decimal("1")) < Decimal("0.01")


@pytest.mark.unit
def test_beta_60_higher_beta_than_market():
    # Symbol with larger moves than market → beta > 1
    market = [100 + i * 0.5 for i in range(62)]
    symbol = [100 + i * 1.5 for i in range(62)]  # 3x the daily move of market
    v = get("beta_60")(_win(symbol, market=market))
    assert v is not None
    assert v > Decimal("1")  # symbol amplifies market moves → beta > 1


@pytest.mark.unit
def test_beta_60_no_market_returns_none():
    closes = [100 + i for i in range(62)]
    v = get("beta_60")(_win(closes, market=None))
    assert v is None


@pytest.mark.unit
def test_beta_60_flat_market_returns_none():
    closes = [100 + i for i in range(62)]
    flat_market = [100.0] * 62  # zero variance → undefined beta
    v = get("beta_60")(_win(closes, market=flat_market))
    assert v is None


@pytest.mark.unit
def test_beta_60_insufficient_history_returns_none():
    closes = [100.0] * 50
    v = get("beta_60")(_win(closes, market=closes))
    assert v is None
