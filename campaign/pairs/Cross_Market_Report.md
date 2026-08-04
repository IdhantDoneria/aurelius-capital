# Cross-Market Report — Pairs Trading (US vs India)

**Aurelius Capital — Workstream E**
**Date:** 2026-08-04
**Source:** `campaign/pairs/runs/{us,india}.jsonl`. Same frozen construction, same
7 configs, only the universe differs.

## 1. Side-by-side (OOS)

| Config | US Sharpe | India Sharpe | US ret | India ret | US DD | India DD |
|---|---|---|---|---|---|---|
| gatev_top20 | −1.076 | **−0.425** | −5.7% | **+8.7%** | −12.5% | −7.4% |
| top5 | −13.542 | −1.230 | −1.2% | +3.5% | −1.4% | −5.7% |
| top40 | −1.126 | −0.238 | −60.2% | −42.5% | −60.2% | −58.9% |
| entry_1.5 | −1.393 | −0.717 | −40.7% | −11.4% | −45.3% | −22.7% |
| entry_2.5 | −0.410 | −0.840 | +8.9% | +3.9% | −7.1% | −8.7% |
| window_63 | −1.235 | −0.523 | −14.8% | +4.5% | −16.6% | −19.2% |
| exit_0.25 | −0.606 | **−0.140** | +4.0% | +13.8% | −9.1% | −15.3% |

**Both markets: 0/7 significant, every config REJECT (p 1.0).**

## 2. India is consistently less-bad than US

On 6 of 7 configs India has the higher (less-negative) OOS Sharpe (US wins only
entry_2.5: −0.410 vs −0.840), and India keeps faint *positive* returns on 5 configs
(gatev +8.7%, exit_0.25 +13.8%, top5 +3.5%, entry_2.5 +3.9%, window_63 +4.5%) while
US is mostly negative. The single least-bad
book in the whole campaign is **India exit_0.25 (−0.14 Sharpe, +13.8% ret)** —
still a reject, still negative risk-adjusted.

**Explanation (evidence-consistent):**
- **Market efficiency.** US large-caps are the most-arbitraged universe on earth;
  Do-Faff/Khandani-Lo crowding has erased the distance-pairs edge. India's market is
  structurally less efficient over 2014–2026 → spreads revert marginally better, so
  the pairs *lose less*. Neither reverts *enough* to pay for costs + the sizing
  truncation.
- **Survivorship (caveat, not a virtue).** India's faint positive returns share the
  same survivorship bias flagged in the momentum campaign — the 2014–2026 panel is
  currently-listed names only; delisted losers absent. This *inflates* India's
  numbers, and they are *still* insignificant. De-biased they would be worse.
- **US top5 anomaly (−13.5 Sharpe).** A 5-pair US book runs near-zero volatility
  (−1.4% DD) with a tiny negative drift → the Sharpe ratio explodes when the
  denominator is near zero. It is a *degenerate small-book* artifact, not a −13× loss
  (return is only −1.2%). Reported raw; flagged as Sharpe instability at near-zero
  vol, not an economic signal.

## 3. Shared behaviour

- **Diversification inverts identically** in both markets: top40 is the worst config
  in each (US −60.2%, India −42.5% / −58.9% DD) — the leverage-cap truncation (P5)
  breaks neutrality the same way regardless of universe. Uniform → Class B, not a
  market difference.
- **Entry/exit response is the same shape:** stricter entry + tighter exit = less-bad
  in both; looser entry = worst in both.
- **Real power both markets:** 591–4833 OOS trades. The null is economic, not a
  sample-size artifact, on both sides.

## 4. What differs vs what is universal

| Dimension | US | India | Driver |
|---|---|---|---|
| Sharpe level | worse | less-bad (still <0) | market efficiency (D) |
| Return sign | mostly − | faint + on 5/7 | efficiency + survivorship |
| Drawdown shape | same | same | leverage-cap truncation (B) |
| Concentration/entry response | same | same | construction, not market |
| Significance | none | none | edge decayed both (D) |

## 5. Verdict

Cross-market validation **confirms the null is universal.** India is less-bad but
not good; US shows no edge at all. The difference is degree, not kind — pairs
trading is unprofitable in both markets on 2014–2026 data. No market-specific
deployable strategy emerges from either side.

## Known limitations / Skipped
- **Half-life / spread-stability statistics NOT computed per market.** *Reason:*
  `ValidationReport` surfaces Sharpe/return/DD/trades/p, not per-pair half-life or
  spread stationarity. *Unblock:* a pair-diagnostics report field (schema change,
  deferred under freeze). The Sharpe/return/DD/trade comparison above is the
  available cross-market evidence.
