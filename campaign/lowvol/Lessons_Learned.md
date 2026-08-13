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

- **L9 — 0 significant L/S equity factors on 2014–2026 Mentisrex data.** Momentum
  (0/14 as L/S), pairs (0/14), low-vol (0/8). The consistent survivor pattern is
  **long-only, single-market** (momentum India long-only was the lone p<0.05).
  Prioritize long-only construction and the CRSP/Compustat data unblock over more
  L/S factor engineering.

---

## M13 addendum — Long-only low-vol (2026-08-06, DEFER)

- **L10 — The M12 short-leg diagnosis was correct: kill the short, kill the ruin.**
  Long-only (allow_short=False, else frozen) continuous DD −36% vs L/S −103%; no ruin
  in any of 6 variants. Confirms L2/L5 — the short high-vol leg was the entire failure.
  *Evidence:* `lowvol_longonly/shards/canonical.jsonl`.
- **L11 — Deployable ≠ significant ≠ alpha.** Long-only is deployable (₹12 cr, no ruin)
  and sign-robust (4/5), yet adjusted p = 0.118 fails the gate and the return is
  beta-dominated. Three separate bars — clear each before ADOPT. DEFER is the honest
  verdict when deployment passes but significance and alpha-attribution do not.
- **L12 — A regime-concentrated OOS inflates OOS Sharpe but not the p-value.** IS Sharpe
  0.017 vs OOS 0.609: the framework refuses to certify an edge living in the recent
  third. Read IS and OOS *together*; a great OOS with a flat IS is non-stationarity, not
  alpha (compare L3).
- **L13 — Long-only equity factors are beta-confounded; alpha needs a factor model.**
  8.3% CAGR trails passive equity; without CRSP/Compustat the low-vol premium can't be
  separated from market beta. The M6 data unblock is the gate to *certifying* (not just
  deploying) any long-only equity factor. Reinforces L9's priority ordering.

## M14 addendum — factor attribution (2026-08-06)

- **L14 — A mis-specified benchmark can fake a zero beta; rolling beta is the tell.**
  Full-sample market β = 0.011 (R² 1.5%) looked like "no market exposure," but rolling
  126d β averaged 0.49. An equal-weight proxy dominated by micro-caps the book excludes
  collapses covariance on its highest-variance days → pooled β ≈ 0. Never trust a single
  pooled beta against a proxy of unknown weighting; check rolling stability first.
  *Evidence:* `lowvol_longonly/m14/attribution.json`.
- **L15 — "Attribution incomplete" is a real DEFER, not an escape hatch.** The decision
  rule's ADOPT (significant residual α) and REJECT (return vanishes under β) both assume
  a *valid* benchmark. With size/value/cap-weighted-market unavailable (M6) and the one
  proxy mis-specified, neither branch is reachable on evidence — α insignificant (t 1.16)
  AND β explains ~nothing. That is data-blocked DEFER. Reinforces L13: alpha-vs-beta for
  a long-only equity factor is un-decidable without CRSP/Compustat.
