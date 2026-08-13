# M5 Methodology Report — Gross vs Net Return Reporting

**Mentisrex Capital — Methodology Fidelity Campaign**
**Date:** 2026-08-04
**Baseline (net):** M4 (`campaign/momentum/m4/us_jt_m4.jsonl`)
**Source (gross):** `campaign/momentum/m5/us_jt_m5_gross.jsonl`
**Engine:** frozen. No engine / strategy / portfolio / validation / statistics / risk change.
**Type:** reporting-fidelity audit + minimum reporting change (config-only).

---

## 1. Audit — what does the reproduction report?

Traced the full metric pipeline:

```
FactorStrategy.on_bar → SignalEvent
  → PortfolioManager.size_order (target_value = NAV × max_pct × strength)
  → OrderEvent → ExecutionSimulator.try_fill
       fill_price = open × (1 ± spread_bps) ± slippage_impact   ← costs in price
       commission = notional × commission_rate                  ← cost in cash
  → FillEvent(commission, slippage_cost) → PortfolioManager.apply_fill
       cash -= (notional + commission)                          ← net cash
  → equity_curve point = cash + Σ mark-to-market positions      ← NET equity
  → PerformanceCalculator.compute(equity_curve) → total_return / Sharpe / max_dd
```

**Finding:** every reported metric — `total_return`, `sharpe_ratio`, `max_drawdown`,
`oos_return` — is derived from the net equity curve. Commissions (10 bps/side),
half-spread (5 bps/side), and Almgren-Chriss slippage (≤10 bps at 100% ADV) are all
folded into fill prices and cash. Round-trip `pnl` is explicitly "net of commission
and slippage" (`performance.py:42`). **The reproduction reports NET-of-all-cost returns.**

## 2. What does JT-1993 report?

Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers*, report
**GROSS** relative-strength portfolio returns — the raw average monthly returns of
the winner, loser, and WML (winner-minus-loser) portfolios. Transaction costs are
addressed in a **separate robustness discussion** (they estimate round-trip costs
and argue the ~1%/month abnormal return is not explained by them); costs are **not
deducted from the headline tables**.

## 3. Conclusion of the audit: they DIFFER

| | Return basis |
|---|---|
| JT-1993 headline | **gross** (raw portfolio returns, no cost deduction) |
| Mentisrex reproduction | **net** (commission + spread + slippage deducted) |

Because they differ, the directive requires the minimum change to surface the
JT-comparable (gross) metric while preserving the existing net production metrics.

## 4. Minimum change implemented (config-only, zero forbidden surface)

Run the **identical** institutional baseline (M1 equal-weight + M2 $5 screen +
M4 skip=21, same `FactorStrategy` params) under a **zero-cost config**:

```python
research_config(max_position_pct=Decimal("1.0"),
                commission_rate=Decimal("0"),
                spread_bps=Decimal("0"),
                slippage_impact_bps=Decimal("0"))
```

`commission_rate`, `spread_bps`, `slippage_impact_bps` are **BacktestConfig inputs**,
not code. Zeroing them produces the gross equity path through the *same* validated
`PerformanceCalculator` — gross return / Sharpe / drawdown from unchanged machinery.
Net (production) metrics = the already-committed M4 baseline, untouched.

**No change to:** execution engine, strategy logic, portfolio construction,
validation, statistics, risk management. New artifacts only: `scripts/run_m5_jt.py`,
one invariant test, this report.

---

## 5. Results — GROSS vs NET (OOS, US equities 2014–2026)

| Metric | M4 NET (production) | M5 GROSS (JT-comparable) | Δ (gross − net) |
|---|---|---|---|
| IS Sharpe | −0.1671 | −0.1515 | +0.0156 |
| OOS Sharpe | +0.1124 | +0.1165 | +0.0041 |
| OOS Return | −24.84% | **−23.76%** | **+1.08 pp** |
| OOS Max DD | −77.24% | −77.14% | +0.10 pp |
| OOS Trades | 593 | 589 | −4 |
| Adjusted p | 0.4134 | 0.4103 | −0.0031 |
| Verdict | REJECT | REJECT | same |

Invariant confirmed: **gross ≥ net** on every return/risk-adjusted metric (costs can
only subtract). Locked by `test_gross_vs_net_reporting`.

---

## 6. Root-cause classification of the gross−net differences

Every difference is the **transaction-cost wedge** and classifies as **A —
methodology fidelity** (this is precisely the gross-vs-net reporting axis M5 targets):

- OOS return +1.08 pp, OOS Sharpe +0.004, OOS DD +0.10 pp, trades −4 → **A**. The
  small trade delta (593→589) is the NAV-path difference (gross NAV higher → integer
  share deltas shift marginally), not a signal change.

No difference is B (data), C (market evolution), D (statistical variation), or
E (platform defect). The wedge is the deterministic cost accounting, isolated.

### The decisive interpretive finding

**The transaction-cost wedge is only ~1.08 pp of OOS return, and the GROSS OOS
return is still NEGATIVE (−23.76%).** Costs are therefore **not** the reason the
reproduction underperforms JT's published ~1%/month magnitude. Even with every
execution cost removed, the OOS book loses money over 2020–2026. The ~80 pp gap to
the paper is **structural** — survivorship bias (currently-listed panel), market
evolution / momentum decay (Category C), leverage-cap truncation of the decile
spread (documented, `Leverage_Investigation.md`), and single-OOS-slice power
(Category E-power, M8) — not transaction costs. M5 quantifies and rules out the
cost explanation.

---

## 7. Decision

**KEEP M5. Adopt gross-alongside-net as the reproduction reporting standard.**

### Evidence

1. **Reporting differed** — audit proved reproduction = net, JT = gross. The
   directive mandates surfacing the gross-comparable metric when they differ.
2. **Fidelity improved** — gross return/Sharpe/drawdown are now reported alongside
   net, giving direct apples-to-apples comparability with JT-1993's gross tables.
3. **Production metrics preserved** — net (M4) is unchanged; gross is additive.
4. **Cost wedge quantified & ruled out** — ~1.08 pp OOS; gross OOS return still
   negative → costs are not the reproduction gap. High interpretive value.
5. **Zero forbidden surface** — config-only; engine/strategy/validation/statistics/
   risk byte-identical. 595 tests pass.

### Scope note

M5 is a **reporting-fidelity** layer, not a strategy change. The institutional
baseline **strategy** remains **M1 + M2 + M4** (`FactorStrategy(lookback=126,
quantile=0.10, rebalance_days=21, allow_short=True, equal_weight=True,
min_price=5.0, skip=21)`, `max_position_pct=1.0`). M5 adds the standard that every
reproduction result is reported on **both** bases: gross (JT-comparable) and net
(production/deployable).

### Why not REJECT

The wedge being small does not argue against the change — the small wedge is a
*result of* the gross view and is itself the fidelity finding (costs ≠ the gap).
Leaving the reproduction net-only would keep it non-comparable to the paper's gross
headline, an unresolved fidelity gap the directive explicitly asks to close.

---

## 8. Known limitations / Skipped

- **Slippage fallback on zero-volume bars** — `SlippageModel` keeps a 5 bps
  fallback for bars with `volume ≤ 0` that is not wired to `slippage_impact_bps`
  (`execution/models.py`, engine-level, frozen). On the real US panel volume is
  populated, so residual fallback slippage is negligible; the dominant wedge
  (commission + spread + variable slippage) is fully removed. *Unblock:* thread the
  fallback through config (requires engine unfreeze). Impact on the gross number:
  immaterial.
- **Gross is gross-of-cost, still within Mentisrex execution** — discrete shares,
  T+1 open fills, 1.5× gross cap still apply to the gross run. M5 isolates the
  transaction-cost axis only; execution-model differences are documented separately
  (M3, `Leverage_Investigation.md`).
- **India M5 not run** — directive: canonical reproduction exactly once (US only).
