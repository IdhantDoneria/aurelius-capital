# Phase 5 Quick Reference: Backtesting Engine Rules

**TL;DR:** Engine is production-ready. Don't break Strategy interface. Ask for clarification on design changes.

---

## Execution Model

```
Bar T close → Order placed (pending)
Bar T+1 open → Order fills at open + spread + slippage
Next bar → Strategy sees result
```

NO intraday execution. NO look-ahead. NO gap handling (stop orders jump over).

---

## Strategy Must Not

- Import DataFeed or external APIs
- Use `datetime.now()` (use `context.now`)
- Assume fills happen in same bar as order
- Store state that depends on future data
- Modify portfolio directly (emit signals; engine applies fills)

---

## Strategy CAN

- Use `context.history(symbol, lookback)` for past bars
- Check `context.portfolio.position(symbol)` for current holdings
- Emit multiple signals per bar (if needed)
- Go long, short, or flat
- Track state between bars (e.g., signal counter, model cache)

---

## Execution Costs (Configurable)

Default realistic for US equities:
- **Commission:** 10 bps per side (institutional)
- **Spread:** 5 bps half (10 bps round-trip)
- **Slippage:** Almgren-Chriss sqrt model, 10 bps @ 100% ADV
- **Max fill:** 20% ADV per bar (partial fills persist)

---

## Constraints (Configurable)

Default conservative:
- **Max position:** 10% NAV per name
- **Max leverage:** 1.5x gross
- **Drawdown halt:** 20% from peak (entire strategy halts)

---

## Known Limits (Can't Fix Without Major Redesign)

| Limit | Current | Workaround |
|-------|---------|-----------|
| Execution timing | Bar.open only | Use daily+ bars |
| Gap handling | Stops jump over | Use limit orders |
| Halt scope | Global strategy | Monitor + restart |
| Multi-leg orders | Not atomic | Emit 2 signals |
| Intraday | Not supported | Use daily+ only |

---

## Before Deploying Strategy

1. Does it only use `context.history()` and signals?
2. Would it make sense with next-bar execution?
3. Do cost assumptions match your asset class?
4. Have you tested on 1 year of data first?
5. Do equity curve and Sharpe make sense?

---

## Interfaces You Can't Change

- `Strategy.on_bar(context, bar) → list[SignalEvent]`
- `StrategyContext.history()`, `.close_series()`, `.portfolio`, `.now`
- `BacktestConfig` field list (can add, not remove)
- `BacktestReport` field list (can add, not remove)

---

## Interfaces You CAN Extend

- Add new methods to Strategy (e.g., `on_signal_rejected()`)
- Add new fields to BacktestConfig (e.g., `margin_rate`)
- Add new convenience methods to StrategyContext (e.g., `high_series()`)
- Add new metrics to BacktestReport (e.g., `transaction_costs`)

---

## Red Flags in Strategy Code

🚩 `import duckdb` (direct data access)  
🚩 `datetime.now()` (should be `context.now`)  
🚩 `self._yesterday_close = ...` stored without timestamp  
🚩 Accessing `bar.close` from prior bar (use history)  
🚩 Assuming order fills same bar as placement  
🚩 Position sizing that assumes intraday fills  

---

## Test Checklist

- [ ] Strategy runs without errors on 1 year of data
- [ ] Equity curve is sensible (not flat, not crashing every bar)
- [ ] Sharpe ratio scales with config changes (tighter stops → lower Sharpe)
- [ ] Trades make sense (holding period, win rate, profit factor)
- [ ] Costs are reasonable (commission + slippage ≈ expected)
- [ ] Drawdown never exceeds `max_drawdown_halt` config

---

## Common Pitfalls

**Pitfall 1:** Forget that orders take N+1 bars to execute.  
*Fix:* Use `context.history()` to see what strategy could have known.

**Pitfall 2:** Use limit price that never gets touched.  
*Fix:* Check `bar.low ≤ limit_buy_price` before signaling.

**Pitfall 3:** Assume position filled when it might be partial.  
*Fix:* Check `context.portfolio.position(symbol).quantity` matches expected.

**Pitfall 4:** Try to trade illiquid names without testing fill assumptions.  
*Fix:* Adjust `spread_bps` and `slippage_impact_bps` for illiquid assets.

**Pitfall 5:** Backtest on survivorship-biased data.  
*Fix:* Provide only symbols that were active on each date.

---

## Quick Grep Commands

```bash
# Find all Strategy implementations
grep -r "class.*Strategy" src/aurelius

# Find test examples
find tests/backtesting -name "*.py" -exec grep "class.*Strategy" {} \;

# Check what strategies already exist
ls src/aurelius/backtesting/strategy/
```

---

## Handoff Documents (Read These First)

1. `PHASE_5_CONSTRAINTS.md` — What can't change
2. `PHASE_4_PRODUCTION_REVIEW.md` — Full audit
3. `PHASE_5_DEVELOPER_GUIDE.md` — Complete reference
4. `PHASE_4_MISSING_TESTS.md` — Known gaps

---

## When to Escalate

| Situation | Action |
|-----------|--------|
| Strategy crashes during backtest | Check exception handler; report bug if engine doesn't catch it |
| Results don't match expectations | Verify no look-ahead; check position sizing; review fills |
| Need new order type (e.g., OCO) | Document requirement; add to Phase 6 roadmap |
| Want to change Strategy interface | DO NOT DO IT. Coordinate with team. |
| Execution costs don't match reality | Adjust BacktestConfig; recalibrate cost models if systematic |
| Backtest is slow (>10 min for 10y) | Switch to DuckDBDataFeed; profile code |

---

## Key Numbers to Remember

- **Next-bar execution:** All fills at T+1 open
- **20% ADV limit:** Max fill per bar before partial
- **10% max position:** Default allocation per name
- **1.5x max leverage:** Default gross constraint
- **20% drawdown halt:** Default circuit breaker
- **5 bps spread:** Default half-spread (institutional)
- **10 bps slippage:** Default market impact @ 100% ADV
- **10 bps commission:** Default per-side cost

---

**Last updated:** 2026-07-25  
**Status:** Phase 4 production-ready; Phase 5 can proceed
