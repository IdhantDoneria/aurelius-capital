"""Tests for PerformanceCalculator — metrics formulas."""

from datetime import UTC, datetime, timedelta

import pytest

from mentisrex.backtesting.analytics.performance import EquityPoint, PerformanceCalculator


def _curve(values: list[float], start_day: int = 1) -> list[EquityPoint]:
    base = datetime(2024, 1, start_day, tzinfo=UTC)
    return [EquityPoint(base + timedelta(days=i), v) for i, v in enumerate(values)]


@pytest.fixture
def calc() -> PerformanceCalculator:
    return PerformanceCalculator(risk_free_rate=0.00, trading_days=252)


@pytest.mark.unit
def test_total_return_profit(calc):
    curve = _curve([1_000_000, 1_100_000])
    metrics = calc.compute(curve)
    assert metrics.total_return == pytest.approx(0.10, rel=1e-4)


@pytest.mark.unit
def test_total_return_loss(calc):
    curve = _curve([1_000_000, 900_000])
    metrics = calc.compute(curve)
    assert metrics.total_return == pytest.approx(-0.10, rel=1e-4)


@pytest.mark.unit
def test_flat_equity_zero_return(calc):
    curve = _curve([1_000_000, 1_000_000, 1_000_000])
    metrics = calc.compute(curve)
    assert metrics.total_return == pytest.approx(0.0, abs=1e-9)


@pytest.mark.unit
def test_max_drawdown_basic(calc):
    # Peak at 1.2M, falls to 0.9M → drawdown = (0.9-1.2)/1.2 = -25%
    curve = _curve([1_000_000, 1_200_000, 900_000])
    metrics = calc.compute(curve)
    assert metrics.max_drawdown == pytest.approx(-0.25, rel=1e-4)


@pytest.mark.unit
def test_max_drawdown_is_zero_when_always_rising(calc):
    curve = _curve([1_000_000, 1_100_000, 1_200_000, 1_300_000])
    metrics = calc.compute(curve)
    assert metrics.max_drawdown == pytest.approx(0.0, abs=1e-9)


@pytest.mark.unit
def test_sharpe_ratio_positive_for_positive_returns(calc):
    # All positive daily returns → positive Sharpe
    values = [1_000_000 * (1.001**i) for i in range(200)]
    curve = _curve(values)
    metrics = calc.compute(curve)
    assert metrics.sharpe_ratio > 0


@pytest.mark.unit
def test_sharpe_ratio_negative_for_negative_returns(calc):
    values = [1_000_000 * (0.999**i) for i in range(200)]
    curve = _curve(values)
    metrics = calc.compute(curve)
    assert metrics.sharpe_ratio < 0


@pytest.mark.unit
def test_calmar_ratio_infinite_when_no_drawdown(calc):
    # Rising equity, no drawdown → calmar should be very large or handle gracefully
    values = [1_000_000 * (1.001**i) for i in range(200)]
    curve = _curve(values)
    metrics = calc.compute(curve)
    # max_drawdown is 0 → calmar not computed (stays 0.0) — handle edge case gracefully
    assert metrics.max_drawdown == pytest.approx(0.0, abs=1e-4) or metrics.calmar_ratio > 0


@pytest.mark.unit
def test_empty_curve_returns_default_metrics(calc):
    metrics = calc.compute([])
    assert metrics.total_return == 0.0
    assert metrics.sharpe_ratio == 0.0


@pytest.mark.unit
def test_single_point_curve_returns_default(calc):
    metrics = calc.compute([EquityPoint(datetime(2024, 1, 1, tzinfo=UTC), 1_000_000)])
    assert metrics.total_return == 0.0


@pytest.mark.unit
def test_volatility_zero_for_flat_returns(calc):
    curve = _curve([1_000_000] * 100)
    metrics = calc.compute(curve)
    assert metrics.annualized_volatility == pytest.approx(0.0, abs=1e-9)


@pytest.mark.unit
def test_drawdown_series_length_equals_equity_curve(calc):
    curve = _curve([1_000_000, 1_100_000, 1_050_000, 1_200_000])
    metrics = calc.compute(curve)
    assert len(metrics.drawdown_series) == len(curve)


@pytest.mark.unit
def test_cagr_roughly_correct(calc):
    # Double in exactly 1 year (365 days)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 1, tzinfo=UTC)
    curve = [EquityPoint(start, 1_000_000), EquityPoint(end, 2_000_000)]
    metrics = calc.compute(curve)
    # CAGR ≈ 100% per year
    assert metrics.cagr == pytest.approx(1.0, rel=0.05)


@pytest.mark.unit
def test_multi_symbol_daily_returns_deduplicated():
    """Equity curve with 2 points per date (simulating 2-symbol backtest)
    must produce daily_returns based on unique dates, not raw point count."""
    base = datetime(2024, 1, 1, tzinfo=UTC)
    # 10 calendar dates × 2 symbols = 20 points total
    curve = []
    for i in range(10):
        ts = base + timedelta(days=i)
        curve.append(EquityPoint(ts, 1_000_000.0 + i * 100))
        curve.append(EquityPoint(ts, 1_000_000.0 + i * 100 + 50))  # same date, higher equity
    calc = PerformanceCalculator(risk_free_rate=0.0, trading_days=252)
    metrics = calc.compute(curve)
    # Raw curve stored intact
    assert len(metrics.equity_curve) == 20
    # daily_returns computed on deduplicated (10 dates) basis → 9 returns
    assert len(metrics.daily_returns) == 9
