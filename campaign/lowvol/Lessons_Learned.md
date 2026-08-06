# Lessons Learned — Low-Volatility Campaign (M12)

**Date:** 2026-08-06. Each lesson traceable to M12 evidence.

## Research lessons

- **L1 — Low-vol L/S has no risk-adjusted edge on this panel.** Canonical adjusted
  p = 0.366, OOS Sharpe 0.176; 0/8 variants clean-positive. The shape of the anomaly
  shows (positive OOS return, low turnover) but not the significance. *Evidence:*
  `shards/canonical.jsonl`.
- **L2 — The short high-vol leg is a ruin machine, exactly like momentum's short
  leg.** Continuous DD −103% at zero cost; NAV-proportional sizing under the 1.5×
  gross cap compounds the short-leg loss through zero equity. Third L/S equity family
  (momentum, pairs, low-vol) to die the same way. *Evidence:* cost_gross DD −102.5%.
- **L3 — Positive OOS slice ≠ deployable.** IS/OOS reset capital each pass and never
  reach the cumulative ruin the single-capital continuous run hits. Always read BOTH
  bases before certifying. *Evidence:* OOS +20.9% vs continuous −103%.
- **L4 — Costs are never the killer here; construction is.** Gross-to-high cost swing
  moves return ~4pp against a −100%+ DD. Stop blaming transaction cost for L/S
  failure. *Evidence:* cost_gross +87.4% vs cost_high +83.4%.
- **L5 — High-vol names are the illiquid micro-caps.** Short leg capacity floor
  ₹0.27 cr vs long leg ₹16 cr. Any low-vol book must be long-biased to be deployable.
  *Evidence:* `capacity_india.json`.
- **L6 — Raw return is not alpha.** rb_63 (quarterly) posts +125% return but −88.5%
  DD and Sharpe 0.23 — a drawdown-driven number, not a risk-adjusted edge. Never let
  a headline return override the risk-adjusted read.

## Operational lessons

- **L7 — Long warm-ups starve short panels.** `lookback=504` → 0 trades on the
  ~12-year survivorship-trimmed panel. Warm-up must be « series length after trimming;
  report starvation as a finding, not a silent skip.
- **L8 — Guard complex-valued metrics at the reporting boundary.** Books breaching
  100% DD (equity ≤ 0) produce complex sortino/vol; the `sr()` safe-round keeps
  outputs real. The `degenerate` flag tracks the complex case; **economic ruin is
  marked by DD < −100%**, independent of that flag — do not conflate them.

## Cross-campaign

- **L9 — 0 significant L/S equity factors on 2014–2026 Aurelius data.** Momentum
  (0/14 as L/S), pairs (0/14), low-vol (0/8). The consistent survivor pattern is
  **long-only, single-market** (momentum India long-only was the lone p<0.05).
  Prioritize long-only construction and the CRSP/Compustat data unblock over more
  L/S factor engineering.
