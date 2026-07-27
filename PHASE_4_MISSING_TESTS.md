# Phase 4: Missing Test Cases Checklist

## Overview

Current test suite: 38 unit tests covering core happy paths.  
This document identifies edge cases that should be tested before production strategies run.

---

## CRITICAL GAPS (Must Have Before Large Backtests)

### 1. Gap Fill Behavior

**Test Case:** Order placed below today's open; bar opens above stop; should NOT fill  
**Current Behavior:** Fills if `low ≤ stop` (ignores gap)  
**Severity:** LOW (edge case; unlikely to trigger with real data)  
**Status:** MISSING

```python
def test_stop_order_does_not_fill_if_gapped_over():
    """Stop at 184, but bar opens at 190 (gapped up) → should NOT fill"""
    order = OrderEvent(
        timestamp=datetime(2024, 1, 14, tzinfo=UTC),
        symbol="AAPL",
        order_type=OrderType.STOP,
        side=Side.BUY,
        quantity=Decimal("100"),
        stop_price=Decimal("184"),
    )
    bar = _bar(open_=190, high=195, low=188)  # Gapped above stop
    fill = _sim().try_fill(order, bar)
    # Current code: fills (because low ≥ stop not checked)
    # Correct code: should NOT fill (price jumped over stop without touching it)
    assert fill is None, "Gap fills should not trigger stop orders"
```

**Why Matters:** Daily → intraday transitions (market opens with gap). Stop orders should respect gaps.  
**Fix Cost:** 2 lines in ExecutionSimulator._base_price() for stop orders.

---

### 2. Extreme Drawdown & Halt Edge Cases

**Test Case 1:** Portfolio at exactly -20% drawdown; should halt on *next* order attempt  
**Test Case 2:** Halted engine should reject all subsequent orders  
**Test Case 3:** Pending orders should NOT fill after halt  
**Severity:** MEDIUM (affects risk management correctness)  
**Status:** MISSING

```python
def test_drawdown_halt_at_exact_limit():
    """Portfolio falls to exactly -20%; next order should be rejected"""
    state = PortfolioState(Decimal("1_000_000"))
    state.update_peak()
    state.debit(Decimal("200_000"))  # 20% drawdown
    risk = RiskEngine(BacktestConfig(max_drawdown_halt=Decimal("0.20")))
    
    order = _market_order()  # Any order
    result = risk.check(order, state)
    assert result.passed is False, "Should reject order at -20% drawdown"
```

**Test Case 2:**
```python
def test_halted_engine_rejects_all_orders():
    """Once halted, all subsequent orders rejected"""
    # Halts at first drawdown check
    result1 = risk.check(order1, state_at_minus_20)
    assert not result1.passed
    
    # State improves to -15% (still below peak)
    state.update_peak()
    state.credit(Decimal("50_000"))  # Back to -15%
    
    # Should still reject (engine is halted)
    result2 = risk.check(order2, state_at_minus_15)
    assert not result2.passed, "Halted flag should persist"
```

---

### 3. Zero Volume Handling

**Test Case 1:** Bar volume = 0; market order should still fill (with fallback slippage)  
**Test Case 2:** Limit order at zero volume; fill price should use fallback slippage  
**Severity:** LOW (rare but possible in thinly traded symbols)  
**Status:** MISSING

```python
def test_market_order_fills_at_zero_volume():
    """Even with zero volume, market order should fill"""
    bar = _bar(volume=0)
    order = _market_order()
    fill = _sim().try_fill(order, bar)
    assert fill is not None, "Market order should always fill"
```

---

### 4. Negative Cash & Margin

**Test Case:** Portfolio cash goes negative; no check/rejection  
**Expected:** Should allow (implies margin lending) or reject explicitly  
**Current:** Allows negative cash silently  
**Severity:** LOW (not an error; just undocumented behavior)  
**Status:** MISSING

```python
def test_portfolio_negative_cash_allowed():
    """Negative cash = implicit margin borrowing; should be documented"""
    state = PortfolioState(Decimal("1_000_000"))
    state.debit(Decimal("1_500_000"))  # Exceeds cash
    assert state.cash < 0, "Negative cash should be allowed"
    # Portfolio still valid (margin account assumption)
```

---

### 5. Long-Short Edge Cases

**Test Case:** Buy 100, sell 200 → correctly goes short 100  
**Test Case:** Short 100, buy 200 → correctly goes long 100  
**Status:** IMPLICIT (tested via position tests, but no E2E)  
**Severity:** LOW (edge case; position accounting tested separately)

```python
def test_engine_long_to_short_transition():
    """Buy 100, sell 200 → correctly goes short 100 (not long -100)"""
    engine = BacktestEngine(
        strategy=SellMoreThanHeld(),  # Sell 2× position on first signal
        data_feed=uptrend_feed,
        config=default_config,
    )
    report = engine.run()
    # Check final state: net short 100
    assert report.metrics.net_exposure < 0
```

---

### 6. Order Type Priority Within Bar

**Test Case:** Market order + limit order both possible in same bar; which fills first?  
**Current:** Handled separately (market always fills; limit has conditions)  
**Severity:** LOW (single strategy doesn't generate both in one bar)  
**Status:** MISSING (out of scope; strategies emit one signal per bar)

---

### 7. Partial Fill Remainder Accounting

**Test Case:** Order 50k shares, only 20k fill (20% ADV). Remainder should stay pending.  
**Subsequence:** Next bar, if volume available, remainder should fill.  
**Status:** TESTED (test_execution.py has partial fill test, but no multi-bar persistence)  
**Severity:** LOW

```python
def test_partial_fill_persists_across_bars():
    """Order 50k shares with 20% ADV = 20k fill. Remainder should pend."""
    bar1 = _bar(volume=100_000)  # 20k max fill
    bar2 = _bar(volume=500_000)  # Enough for remainder
    
    order = OrderEvent(..., quantity=Decimal("50_000"))
    fill1 = sim.try_fill(order, bar1)
    assert fill1.quantity == Decimal("20_000")
    
    # Manually rebuild remainder
    order_remainder = OrderEvent(..., quantity=Decimal("30_000"))
    fill2 = sim.try_fill(order_remainder, bar2)
    assert fill2.quantity == Decimal("30_000"), "Remainder should fill in next bar"
```

---

### 8. Limit Order Fill Price Optimization

**Test Case:** Limit buy at 184, bar=[open 185, low 180]. Should fill at 184 (best price ≤ limit).  
**Current:** Fills at min(open, limit) = min(185, 184) = 184 ✅  
**Status:** TESTED (test_execution.py)  
**Severity:** LOW (already correct)

---

### 9. Commission Rounding

**Test Case:** Notional = $0.005; commission at 0.1% = $0.000005. Should round to $0.01?  
**Current:** `.quantize(Decimal("0.01"))` rounds to nearest cent  
**Status:** TESTED (test_execution.py)  
**Severity:** LOW (edge case; configurable)

---

### 10. Strategy Crash During on_bar()

**Test Case:** Strategy raises exception; engine should catch it  
**Current:** No try-except around strategy.on_bar()  
**Severity:** HIGH (could crash entire backtest)  
**Status:** MISSING

```python
def test_engine_catches_strategy_exception():
    """If strategy crashes, backtest should report error, not raise"""
    class BuggyStrategy(Strategy):
        def on_bar(self, ctx, bar):
            raise ValueError("Intentional crash")
    
    engine = BacktestEngine(
        strategy=BuggyStrategy(),
        data_feed=uptrend_feed,
        config=default_config,
    )
    # Should not raise; should catch and report
    report = engine.run()
    assert report.error is not None
```

---

## MODERATE GAPS (Should Have Before Production)

### 11. Multi-Symbol Correlation Tests

**Test Case:** Two correlated symbols; ensure fills are independent per symbol  
**Current:** Each symbol gets own Position; fills processed per bar  
**Severity:** MEDIUM (common use case; not tested)  
**Status:** MISSING

```python
def test_two_symbol_portfolio_independent_fills():
    """AAPL and MSFT should have independent positions and fills"""
    # Engine with strategy that trades both AAPL and MSFT
    # Verify fills don't cross-contaminate positions
```

---

### 12. Risk Check Order: Position > Leverage > Drawdown

**Test Case:** All three limits would be violated. Which one rejects?  
**Current:** Drawdown (first), then position (line 65), then leverage (line 80)  
**Severity:** LOW (ordering matters for debugging)  
**Status:** MISSING (no test for interaction)

---

### 13. Performance Metrics on Flat Return

**Test Case:** Equity curve = [1M, 1M, 1M] (no change)  
**Expected:** Sharpe = 0, Sortino = 0, Max Drawdown = 0  
**Current:** Handled? (test_analytics.py has flat_equity_zero_return)  
**Severity:** LOW

---

### 14. Win Rate & Profit Factor Edge Cases

**Test Case 1:** All trades are wins (losses = 0); profit_factor = inf  
**Test Case 2:** All trades are losses; profit_factor = 0  
**Test Case 3:** One trade (can't have win rate as percentage)  
**Severity:** LOW

```python
def test_profit_factor_all_wins():
    """All trades win; profit_factor should be inf or large number"""
    metrics = calc.compute(equity_curve, fills_all_wins)
    assert metrics.profit_factor == float("inf")
```

---

## MINOR GAPS (Nice-to-Have)

### 15. Floating Point vs Decimal Consistency

**Test Case:** Mix of float and Decimal inputs; should maintain precision  
**Current:** BarData uses Decimal; events use Decimal; positions use Decimal  
**Severity:** VERY LOW (good discipline already)

---

### 16. Reproducibility Across Runs

**Test Case:** Same seed, same data, same config → same results (bit-perfect)  
**Current:** Config has `random_seed` but not used by engine  
**Severity:** LOW (nice-to-have for research reproducibility)

```python
def test_same_seed_produces_same_results():
    """Seed 42 twice should produce identical equity curves"""
    config1 = BacktestConfig(random_seed=42)
    report1 = engine.run()
    
    config2 = BacktestConfig(random_seed=42)
    report2 = engine.run()
    
    assert report1.metrics.total_return == report2.metrics.total_return
```

---

## TEST PRIORITY MATRIX

| Test | Severity | Likelihood | Add Before | Effort |
|------|----------|-----------|-----------|--------|
| Gap fills | Low | Medium | Multi-year backtest | 1 hour |
| Drawdown halt edge cases | Medium | High | First strategy | 2 hours |
| Zero volume | Low | Low | ThinlyTraded test | 1 hour |
| Negative cash | Low | Low | Risk course | 1 hour |
| Long-short transitions | Low | High | Pairs strategy | 1 hour |
| Partial fill persistence | Low | Medium | Large orders | 2 hours |
| Strategy crash handling | High | Medium | First strategy | 3 hours |
| Multi-symbol correlation | Medium | High | Factor strategy | 3 hours |
| Performance on edge cases | Low | Low | Metrics course | 2 hours |
| Reproducibility | Low | Low | Paper writing | 1 hour |

---

## IMPLEMENTATION PLAN

**Phase 4a (Before Phase 5 starts):** Add 3 critical tests
1. Drawdown halt edge cases
2. Strategy crash handling
3. Zero volume market order

**Phase 5 (During strategy development):** Add 5 contextual tests
- Run tests when each strategy type is first deployed
- Gap fills (before daily backtests)
- Multi-symbol (before factor strategies)
- Partial fills (before large position sizes)
- Long-short transitions (before market-neutral)
- Profit factor edge cases (before performance reporting)

**Phase 6+ (As codebase matures):** Regression suite
- Add known-baseline strategies (SMA 10/50, simple pairs)
- Lock results to repo (fail CI if metrics drift)
- Stress test DuckDB with 10+ years / 1000+ symbols
