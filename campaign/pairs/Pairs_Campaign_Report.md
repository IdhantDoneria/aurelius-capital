# Pairs Trading Research Campaign — Master Report

**Mentisrex Capital, Quantitative Research Division. 2026-08-04.**
Frozen platform, no tuning, no architecture change. Answers: under what conditions
does statistical arbitrage through pairs trading exist, how faithfully can Mentisrex
reproduce the literature, and what strategy is justified. All figures trace to
`campaign/pairs/runs/*.jsonl`.

## Workstream status

| WS | Deliverable | Status |
|---|---|---|
| A Literature | `Literature_Map.md` (Gatev, Vidyamurthy, Avellaneda-Lee, Do-Faff, Khandani-Lo) | done |
| B Reproductions | `Canonical_Reproductions.md` (Gatev RUN → REJECT; others BLOCKED) | done |
| C Methodology | `Methodology_Fidelity.md` (gaps P1–P6, 0 defects) | done |
| D Robustness | `Robustness_Report.md` (7-config sweep × 2 markets) | done |
| E Cross-market | `Cross_Market_Report.md` (US vs India) | done |
| F Meta / KG | `Knowledge_Graph_Summary.md` | done |
| G Strategy | `Production_Strategy.md` (**NO-GO — no v1**) | done |
| H Reporting | this report + `Executive_Summary.md` | done |

## The evidence, in one table (OOS)

| Config | US Sharpe / ret / p | India Sharpe / ret / p |
|---|---|---|
| gatev_top20 (canonical) | −1.076 / −5.7% / 1.000 | −0.425 / +8.7% / 1.000 |
| top5 | −13.542 / −1.2% / 1.000 | −1.230 / +3.5% / 1.000 |
| top40 | −1.126 / −60.2% / 1.000 | −0.238 / −42.5% / 1.000 |
| entry_1.5 | −1.393 / −40.7% / 1.000 | −0.717 / −11.4% / 1.000 |
| entry_2.5 | −0.410 / +8.9% / 1.000 | −0.840 / +3.9% / 1.000 |
| window_63 | −1.235 / −14.8% / 1.000 | −0.523 / +4.5% / 1.000 |
| exit_0.25 | −0.606 / +4.0% / 1.000 | −0.140 / +13.8% / 1.000 |

**14/14 REJECT. 0 significant.**

## Findings

1. **Pairs trading does not exist as an edge on 2014–2026 US+India.** Every config,
   both markets, insignificant. A stable, well-powered null (591–4833 OOS trades),
   not an unlucky draw.
2. **The edge decayed — Class D.** Gatev's ~11%/yr (1962–2002) is gone by the modern
   era; this is Do & Faff's documented decay, confirmed empirically on Mentisrex data.
3. **Diversification inverts under the frozen sizing — Class B.** top40 is the worst
   config in both markets. Fixed 5%/leg × 40 pairs × 2 = 400% nominal gross vs a
   1.5× cap → truncation breaks dollar-neutrality → directional −60% drawdown. Gatev's
   diversification benefit cannot express without committed-capital sizing (P5).
4. **Tight books are genuinely market-neutral** (top5, entry_2.5: −1% to −9%
   drawdown) — the long/short construction works; it just earns nothing.
5. **India less-bad than US, still insignificant** — market-efficiency gradient moves
   the degree, not the sign; India's faint positive returns are survivorship-inflated.
6. **Faithful reproduction, bounded by data/sizing, not the engine.** 0 Class-A
   defects across 14 runs.

## Reproduction fidelity vs the literature

Directionally and structurally faithful to Gatev (SSD distance selection over a
12-month formation, top-N portfolio, 2-SD divergence entry, convergence exit,
leak-safe formation/trading split). **Not** magnitude-faithful: raw-price vs
normalized/cointegration spread (P1), single 70/30 split vs rolling monthly
re-formation (P3), fixed-% + gross-cap vs committed-capital sizing (P5),
price vs total-return normalization (P6, data), no wait-one-day (P4). Ranked in
`Methodology_Fidelity.md`.

## Ranked fidelity improvements (identified, NOT implemented under freeze)

1. **P5** — committed-capital / equal-weight-within-budget sizing (lets the pair
   portfolio express under the cap; fixes the top40 inversion). Highest impact.
2. **P3** — rolling monthly re-formation harness (faithful Gatev test; fixes static
   pair decay).
3. **P1** — normalized-price / cointegration (Vidyamurthy) spread selection mode.
4. **P6** — dividend-adjusted (total-return) price panel (data).
5. **Survivorship** — delisting-returns dataset to de-bias India's faint positives.

## Strategy outcome

**Pairs Trading v1 = NONE** (`Production_Strategy.md`). No config is significant, so
the only evidence-honest output is: do not deploy, do not fund further pairs
engineering, gate any revisit behind P5 + P3 + delisting data with a pre-registered
kill criterion.

## Campaign integrity

No parameters tuned to improve results. No toy data substituted. No architecture
changed (0 Class-A defects; the top40 blow-up is a documented Class-B sizing gap).
Every blocked variant reported with its exact missing dataset/selector. Every
headline number reproducible from a committed jsonl line. A well-powered negative
result, honestly reported.
