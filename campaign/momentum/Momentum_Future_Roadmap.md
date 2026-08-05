# Future Alpha Roadmap (post-momentum)

**Aurelius Capital — Momentum Campaign, Phase-6 (M11)**
**Date:** 2026-08-05. Ranking + justification only — **nothing implemented**. M12
selects from this after M11 certification.

## Framing

The binding constraint is **data** (M6): the panel is price+volume only, 2014–2026,
survivorship-biased. So each family is scored on **data availability now** as heavily
as on expected value. The single highest-leverage action is acquiring
**CRSP + Compustat** (point-in-time membership, delisting returns, fundamentals),
which unblocks the orthogonal-to-momentum winners.

## Scorecard (1–5; 5 = best)

| Rank | Alpha family | Research value | Data available now | Simplicity | P(success) | Orthogonality to momentum | Notes |
|---|---|---|---|---|---|---|---|
| 1 | **Value (HML)** | 5 | 1 (needs Compustat) | 4 | 4 | **5** | Classic, robust, negatively correlated with momentum → best diversifier. Flagship of the CRSP/Compustat unblock. |
| 2 | **Quality / Profitability** (Novy-Marx gross profitability) | 5 | 1 (needs Compustat) | 4 | 4 | 4 | Robust, orthogonal, low-turnover (capacity-friendly). Bundle with Value under one data buy. |
| 3 | **Low volatility / BAB** | 4 | **5** (price+volume) | 4 | 3 | 4 | **Runnable now.** Well-documented anomaly, orthogonal to momentum, lower turnover than momentum → better on the M10 capacity/cost axis. Best immediate test. |
| 4 | **Residual momentum** | 3 | 4 (price + market/size proxy) | 3 | 3 | 3 | Momentum with market beta removed — directly targets the beta contamination that sank plain momentum's L/S legs. Runnable with a panel-built factor proxy; a fair "second look" at momentum without refunding the failed version. |
| 5 | **Short-term mean reversion** | 3 | **5** (price only) | 4 | 3 | 4 | Runnable now; opposite horizon to momentum (orthogonal). BUT high turnover → cost/capacity-sensitive (M10 lesson); needs the M8 construction + realistic-cost gate from day one. |
| 6 | **Statistical arbitrage** (PCA/OU residuals) | 4 | 3 (price only, but needs selector infra) | 2 | 3 | 4 | High ceiling, higher build cost; needs residual-portfolio + OU machinery absent today. Medium-term. |
| 7 | **Fundamental factors (broad multi-factor)** | 4 | 1 (needs Compustat) | 2 | 3 | 4 | Subsumes Value/Quality/Profitability into a combined book; do *after* the single factors are validated. |
| 8 | **Pairs trading** | 2 | 5 (price only) | 4 | 1 | 3 | **Already tested: 0/14 REJECT** (Gatev decayed to 2014–2026). Do not refund without sector-matched selectors + delisting data. Lowest priority. |
| 9 | **Alternative data** | 5 | 1 (not held) | 1 | 2 | **5** | Highest orthogonality and ceiling, highest cost/complexity, fully blocked. Long-horizon strategic bet, not a next step. |

## Recommended sequence

1. **Now (price-only, no new data):** **Low volatility** first (best runnable
   risk/orthogonality/capacity profile), then **Residual momentum** as the disciplined
   re-test of the momentum idea with beta removed, then **short-term mean reversion**
   (gated on cost/turnover from the outset).
2. **Acquire CRSP + Compustat** (the M6 unblock) — the single highest-leverage move.
3. **Post-data flagship:** **Value**, then **Quality/Profitability**, then a combined
   **fundamental multi-factor** book — the orthogonal-to-momentum winners that also
   fix the survivorship/PIT ceiling.
4. **Medium-term:** statistical arbitrage infrastructure.
5. **Do not refund pairs** without new selectors/data. **Alternative data** is a
   separate strategic decision.

## Guardrails carried from momentum (apply to every family above)

- Gross-first accounting (M5): kill early if gross OOS is absent.
- M8 bounded construction mandatory for any universe-reducing step.
- Realistic-cost + capacity gate (M10) before any deployability claim; watch
  return + max-DD, never a ratio alone.
- Byte-identical reproduction + config-switch forensics (M9) before trusting a result.
- Name the data ceiling honestly (M6); survivorship-corrected numbers only, once data
  allows.
