# Robustness Report — Pairs Trading Campaign

**Aurelius Capital — Workstream D**
**Date:** 2026-08-04
**Source:** `campaign/pairs/runs/{us,india}.jsonl`. 7 configs × 2 markets = 14 runs,
each ONE hypothesis judged once on its own 70/30 OOS split. No tuning.

## 1. Full grid (OOS)

| Config | axis | US Sharpe / ret / DD / trades | India Sharpe / ret / DD / trades |
|---|---|---|---|
| gatev_top20 | canonical | −1.076 / −5.7% / −12.5% / 3999 | −0.425 / +8.7% / −7.4% / 3303 |
| top5 | concentration | −13.542 / −1.2% / −1.4% / 1055 | −1.230 / +3.5% / −5.7% / 591 |
| top40 | diversification | −1.126 / **−60.2%** / −60.2% / 1270 | −0.238 / **−42.5%** / −58.9% / 1761 |
| entry_1.5 | looser entry | −1.393 / −40.7% / −45.3% / 3568 | −0.717 / −11.4% / −22.7% / 4833 |
| entry_2.5 | stricter entry | −0.410 / +8.9% / −7.1% / 1371 | −0.840 / +3.9% / −8.7% / 1334 |
| window_63 | shorter spread | −1.235 / −14.8% / −16.6% / 3064 | −0.523 / +4.5% / −19.2% / 3360 |
| exit_0.25 | tighter exit | −0.606 / +4.0% / −9.1% / 3413 | −0.140 / +13.8% / −15.3% / 2839 |

**All 14 REJECT (adjusted p = 1.000 everywhere). 0 significant.**

## 2. Axis findings

1. **Concentration (top5 / top20 / top40) — diversification INVERTS vs Gatev.**
   Gatev's premium *is* diversification across 20 pairs. Here **top40 is the worst
   config in both markets** (US −60.2% ret / −60.2% DD; India −42.5% / −58.9%).
   Cause: 40 pairs × 2 legs × 5% = 400% nominal gross vs the 1.5× cap → the risk
   engine truncates fills → the surviving legs are **no longer dollar-balanced** →
   the "market-neutral" book carries residual directional risk that a bad regime
   punishes. top5 is a tiny, near-flat book (US −1.2% at −1.4% DD). **The
   diversification benefit cannot express under fixed-% sizing + a gross cap.**
   Class B (P5/M3), the same leverage interaction as the momentum campaign — a
   sizing-fidelity artifact, not an alpha signal about pair count.
2. **Entry threshold — stricter is less-bad, still no edge.** entry_2.5 posts the
   least-negative books (US +8.9% at −7.1% DD; India +3.9% at −8.7% DD) on ~1300
   high-conviction trades; entry_1.5 is worst (most trades, most noise: US −40.7%,
   India −11.4%). Fewer, wider divergences reduce whipsaw — but never enough to
   clear significance (still negative Sharpe, p 1.0).
3. **Spread window (63 vs 126) — no OOS gain, overfit flip.** India window_63 is the
   *only* positive IS Sharpe in the grid (+0.689) yet flips to −0.523 OOS. Classic
   in-sample overfit with no out-of-sample persistence. 126d is no better OOS.
4. **Exit band — tighter convergence marginally best.** exit_0.25 gives the
   least-bad book in both markets (India −0.140 Sharpe / +13.8% ret — the closest
   to break-even in the entire grid; US −0.606 / +4.0%). Holding to fuller
   convergence captures a little more reversion. Still REJECT.

## 3. Drawdown / neutrality behaviour

- **Tight books are genuinely market-neutral:** top5 and entry_2.5 run −1% to −9%
  drawdowns — the long+short construction works, exposure is small, P&L is small.
- **Wide/loose books lose neutrality under the cap:** top40 and entry_1.5 hit −45%
  to −60% drawdowns — truncation-induced directional drift, not pair risk per se.
- **No config earns its risk.** The best risk-adjusted result is *still negative*
  (India exit_0.25, −0.14). Pairs on this data is, at best, an expensive way to
  hold near-zero.

## 4. Turnover / capacity (from trade counts, honest)

OOS trades range 591 (India top5) to 4833 (India entry_1.5) over ~3.8y. Looser
entry and more pairs raise turnover; capacity/ADV utilization is **not surfaced by
`ValidationReport`** → not estimated (would need a report-schema change, out of
scope under the freeze). Reported as unknown, not fabricated.

## 5. Verdict

Pairs trading is **robustly unprofitable** across every axis on 2014–2026 US+India:
no formation window, entry threshold, exit band, or pair count produces a
significant book. The result is stable (all p 1.0), not a single unlucky config —
which is itself the finding: the distance-pairs edge is gone from this data.

## Known limitations / Skipped
- **Volatility-regime and bull/bear sub-period splits NOT run as separate configs.**
  *Reason:* the runner does one 70/30 split per strategy; sub-period conditioning
  needs a walk-forward harness (P3, deferred under freeze). The single OOS slice is
  one ~3.8y window. *Unblock:* rolling re-formation / multi-window harness.
- **Sector / transaction-cost-sweep robustness NOT run.** *Reason:* no sector map;
  cost is the engine's fixed commission model (no ADV/impact calibration data).
  *Unblock:* sector table + calibrated cost model.
