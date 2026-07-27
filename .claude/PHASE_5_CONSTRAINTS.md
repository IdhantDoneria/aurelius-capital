# Phase 5: Backtesting Engine Constraints & Locked Interfaces

**Context:** Phase 4 production readiness review complete. Engine approved for research. This file documents what IS and IS NOT allowed to change.

---

## Locked Interfaces (DO NOT BREAK)

### Strategy Interface
```python
class Strategy(ABC):
    @abstractmethod
    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        """Return signals for current bar. This signature is locked."""
```
- Researchers depend on this contract
- Can ADD new methods, but never change `on_bar()` signature
- Can add optional `on_start()` and `on_end()` hooks

### StrategyContext API (Stable)
- `context.history(symbol, lookback)` — returns bars ≤ current timestamp only
- `context.close_series(symbol, lookback)` — convenience for close prices
- `context.portfolio` — read-only PortfolioState
- `context.now` — current simulation timestamp

Can extend with new convenience methods, but never remove or change existing ones.

### BacktestConfig Fields (Backward Compatible)
Can ADD new fields (e.g., `margin_rate`, `borrowing_cost`), but DO NOT REMOVE existing:
- `initial_capital`, `start_date`, `end_date`
- `commission_rate`, `spread_bps`, `slippage_impact_bps`, `max_fill_pct_adv`
- `max_position_pct`, `max_gross_leverage`, `max_drawdown_halt`
- `risk_free_rate`, `trading_days_per_year`, `random_seed`, `max_history_bars`

### BacktestReport Fields (Backward Compatible)
Can ADD new fields, but DO NOT REMOVE:
- `strategy_name`, `strategy_parameters`, `run_id`
- `symbols`, `start_date`, `end_date`, `total_bars`
- `initial_capital`, `commission_rate_bps`, `spread_bps`, `slippage_bps`
- `metrics: PerformanceMetrics`

---

## Known Limitations & Workarounds

### 1. Next-Bar Execution (LOCKED)
**Limitation:** All orders fill at bar.open; no mid-bar execution.  
**Workaround:** Run on daily+ bars only.  
**Blocker for:** Minute-level strategies (do not attempt).

### 2. Gap Fills (DESIGN)
**Limitation:** Stop orders execute even if price jumps over stop price.  
**Example:** Stop buy at 184, bar opens at 190 → fills (shouldn't).  
**Workaround:** Use limit orders instead of stops for precise entry.

### 3. Global Risk Halt (DESIGN)
**Limitation:** When max_drawdown_halt breached, entire strategy halts.  
**Workaround:** Monitor drawdown daily; restart on symbol subsets if halted.  
**Future:** Phase 6 will add per-symbol halting.

### 4. No Multi-Leg Orders (DESIGN)
**Limitation:** Can't place entry + stop-loss as single atomic unit.  
**Workaround:** Emit two separate signals (entry first, stop second).  
**Impact:** Pair strategies work fine; market impact calculated per-order.

### 5. No Intraday Data
**Limitation:** Engine expects daily (or lower frequency) bars.  
**Workaround:** None. Must use daily+.  
**Impact:** Cannot backtest minute-level strategies.

### 6. No ML Retraining
**Limitation:** Models are static (trained once at on_start()).  
**Context:** This is VALIDATION testing, not online learning.  
**Workaround:** Train externally; backtest as hold-out set.

### 7. No Fractional Shares (ACCEPTABLE)
**Limitation:** Positions are integer shares only.  
**Workaround:** Round to nearest share (acceptable slippage).

### 8. Negative Cash Allowed (IMPLICIT MARGIN)
**Limitation:** Portfolio can go negative (no margin call enforcement).  
**Context:** Research assumes credit availability; PM monitors leverage.  
**Workaround:** Researcher enforces margin calls manually via signals.

### 9. No Survivorship Adjustment (DATA RESPONSIBILITY)
**Limitation:** Engine doesn't adjust for delisting/splitting.  
**Requirement:** Researcher must provide survivorship-adjusted data.  
**Check before backtest:** "Do my symbols include only active tickers on each bar's date?"

---

## Engine Capabilities (Confirmed Ready)

✅ Momentum strategies (SMA, MACD, momentum scoring)  
✅ Mean reversion (Bollinger bands, Z-score)  
✅ Pairs/statistical arbitrage (long-short, hedged)  
✅ Factor models (equal-weight, market-cap weighting)  
✅ Machine learning (static models; validation only)  
✅ Multi-symbol portfolios (up to ~1000 symbols; untested at scale)  
✅ Long-only, long-short, market-neutral  
✅ Transaction cost analysis (visible in fills)  
✅ Risk analysis (Sharpe, Sortino, Calmar, max drawdown, profit factor)  

---

## Testing Requirements Before Deploying a Strategy

**Before first backtest:**
- [ ] Strategy is not trying to access external APIs or real-time data
- [ ] Strategy only uses `context.history()` for data (no `datetime.now()`)
- [ ] Position sizing makes sense (check order quantities vs config.max_position_pct)

**Before production/reporting:**
- [ ] Sanity check: Does baseline (buy-and-hold) produce expected return?
- [ ] Sanity check: Do Sharpe ratios scale reasonably with risk?
- [ ] Check equity curve: Smooth growth or whipsaw? (whipsaw = high turnover)
- [ ] Check trades: Do round-trip holding periods match strategy intent?
- [ ] Review fills: Are costs (commission + slippage) reasonable?

**Before large-scale backtests (10+ years, 100+ symbols):**
- [ ] Test with DuckDBDataFeed (InMemory uses RAM; won't scale)
- [ ] Monitor memory usage during backtest
- [ ] Verify performance: backtest should complete in <5 min for 10 years

---

## What NOT to Do

❌ Try to access strategy.on_bar() without StrategyContext (breaks contract)  
❌ Store state in Strategy between bars that depends on future data  
❌ Use `datetime.now()` instead of `context.now`  
❌ Import DataFeed directly in strategy (only engine touches it)  
❌ Modify portfolio state directly (use signals; engine applies fills)  
❌ Assume intraday execution (all fills at bar.open)  
❌ Assume prices never gap over stops (they do; use limits instead)  
❌ Backtest strategies with look-ahead (strategy must not know outcomes)  

---

## Reference Documents

1. **PHASE_4_PRODUCTION_REVIEW.md** — Full audit (architecture, quantitative validation, execution model)
2. **PHASE_4_MISSING_TESTS.md** — Edge cases & test checklist
3. **PHASE_5_DEVELOPER_GUIDE.md** — Complete API reference & common patterns
4. **PHASE_4_AUDIT_SUMMARY.md** — Executive summary

Read these before deploying Phase 5 strategy framework.

---

## Questions to Ask Before Feature Requests

**Before requesting new BacktestConfig field:**
- "Does this constraint exist in production execution?"
- "Can researchers work around this with config adjustments?"

**Before requesting new report metric:**
- "Is this derivable from existing fields (equity_curve, fills)?"
- "Will this block research, or is it nice-to-have?"

**Before requesting engine changes:**
- "Would this require breaking an existing Strategy interface?"
- "Is this a bug fix (correctness) or feature (nice-to-have)?"

**Approve: Bug fixes and additions that don't break existing interfaces.**  
**Defer: Changes that break Strategy, StrategyContext, or Config fields.**

---

## Escalation Path

**Bug in engine behavior?** → Create issue with minimal repro, assign to quant lead.  
**Need new cost model?** → Add to BacktestConfig, update ExecutionSimulator.  
**Research workflow blocked?** → Check PHASE_4_MISSING_TESTS.md for known gaps; escalate if not listed.  
**Want to modify Strategy interface?** → Do NOT do it. Coordinate with team first.
