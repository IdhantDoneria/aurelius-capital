# Production Strategy — Pairs Trading v1

**Date:** 2026-08-04. Justified by campaign evidence only (`us.jsonl`,
`india.jsonl`, `Robustness_Report.md`, `Cross_Market_Report.md`,
`Canonical_Reproductions.md`). No intuition, no parameters chosen to flatter a
backtest. **Recommendation: NO-GO. No pairs strategy is deployable — not to live
capital, not to paper trading as a standalone alpha.**

## 1. What the evidence supports

Across 14 backtests (7 configs × US/India), **zero** cleared significance — every
config is REJECT at adjusted p = 1.000, every OOS Sharpe is negative. This is a
stronger null than the momentum campaign (which had exactly one significant
config). The distance-pairs edge Gatev documented (1962–2002) **does not exist** in
Aurelius's 2014–2026 US+India equity panel. There is therefore **no
evidence-justified production pairs strategy.**

## 2. Why there is no v1 (unlike momentum)

The momentum campaign produced a paper-tradeable v1 because one config was
statistically significant. Pairs produces none. Naming a "best" config would be
**tuning to a backtest** — forbidden by campaign governance. The least-bad book
(India, exit_0.25: −0.14 Sharpe, +13.8% return) is still a losing, insignificant,
survivorship-inflated book. Deploying it would be deploying noise.

## 3. What a *research* pairs program would need first (NOT a strategy)

If Aurelius chooses to keep investigating pairs (a research decision, not an
evidence conclusion), the campaign identifies the two changes most likely to give
the method a *fair* test — both **unbuilt under the freeze**, neither authorized
here:

1. **Committed-capital / equal-weight-within-budget sizing (P5).** Fixed 5%/leg +
   the 1.5× gross cap truncates every book and breaks dollar-neutrality (top40
   drawdowns −60%). A budgeted sizing that keeps legs balanced under the cap is
   the prerequisite for pairs to express *at all*.
2. **Rolling monthly re-formation (P3).** Static top-N held 11 years is a
   pessimistic bound; Gatev re-forms every month. A walk-forward re-formation
   harness is required for a faithful test.

Secondary (each **BLOCKED** on data/selector): cointegration selection (Vidyamurthy),
PCA/ETF residual OU (Avellaneda-Lee), sector-matched pairs (Do-Faff),
dividend-adjusted (total-return) distances.

**Even with all of the above, the Do-Faff prior says the modern net edge is thin.**
The honest expected value of a pairs research program is low.

## 4. Recommendation

- **Do NOT deploy any pairs strategy** — no live capital, no paper trading.
- **Do NOT allocate further engineering to pairs** under the current data/platform:
  no Class-A defect exists; the null is economic (market evolution), not fixable by
  code. Redirect the research budget to where the momentum campaign found signal
  (long-only trend, bias-corrected) or to acquiring the data that unblocks the
  richer stat-arb variants.
- **If pairs is revisited later,** gate it behind P5 sizing + P3 re-formation and a
  delisting-returns dataset — and pre-register a kill criterion (net Sharpe > 0.5
  on walk-forward, both markets) so it is not kept alive by hindsight.

## 5. Decision

**Pairs Trading v1 = NONE.** The evidence supports no production pairs strategy.
The campaign's value is the *negative* result: a faithful, well-powered
demonstration (14 configs, 3000+ trades each on the canonical) that distance pairs
do not pay on 2014–2026 US+India data — Class D (market evolution, per Do-Faff)
plus Class B (sizing/leverage truncation). Go/no-go rationale in
`Executive_Summary.md`.

## Known limitations / Skipped
- **No production spec is emitted.** *Reason:* this is not a skip — it is the
  evidence-mandated conclusion (0/14 significant; naming a config would be tuning).
  *Unblock to reconsider:* a significant, bias-corrected, walk-forward result after
  the P5/P3 research additions. Recorded, not silently omitted.
