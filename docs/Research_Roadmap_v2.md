# Research Roadmap v2 — Post-Attribution Audit

**Date:** 2026-08-06 · Planning artifact only. **No experiments run, no code modified.**
Supersedes `RESEARCH_CAMPAIGN_ROADMAP.md` (v1, 2026-07-30), which predates campaigns
M8–M14. Grounded on verified certified state, not aspiration.

---

## 0. Certified state (input to this audit)

| Item | State |
|---|---|
| Research framework | **Certified** (two-pass IS/OOS, multiple-testing-gated adj p) |
| Engine / execution | **Certified** (T+1 fills, no look-ahead, M9) |
| Portfolio construction | **Certified** (M8 bounded equal-weight) |
| Momentum (cross-sectional) | **REJECT** |
| Low-vol long-short | **REJECT** (short-leg ruin) |
| Low-vol long-only | **DEFER** (deployable, promising, statistically uncertified) |
| Factor attribution | **DEFER (data-blocked)** — alpha-vs-beta undecomposable |
| Data on hand | Yahoo OHLCV, **price+volume only**, survivorship-biased ~2015–2026, US canonical + India `.NS` |

### Central thesis: information gain is DATA-limited, not idea-limited.

Six campaigns run → 2 REJECT, 2 DEFER. **Both DEFERs are the same wall:** no factor
model (no cap-weighted market, no size, no value) because the panel is price+volume
only (M6). Every remaining OHLCV-only campaign inherits this ceiling — if its raw test
*passes*, attribution will **DEFER exactly like M13/M14**. Therefore the highest-value
move is not another factor; it is the **CRSP/Compustat data upgrade** that converts
DEFER-capped campaigns into ADOPT/REJECT-decidable ones and re-credentials the two
REJECTs (both carry an unquantified upward survivorship bias). Run cheap OHLCV screens
in parallel, but do not mistake them for the gate.

---

## 1. Audit question 1 — questions blocked ONLY by missing data

These are fully specified, engine-ready, and gated on data alone (no unknown method):

| Blocked question | Missing datum |
|---|---|
| Is the low-vol DEFER return alpha or beta? (M13/M14) | cap-weighted market → shares outstanding (CRSP) |
| Are momentum/low-vol REJECT/DEFER verdicts survivorship-inflated? | delisting returns (CRSP) |
| Does a value (HML) premium exist on this universe? | book equity / fundamentals (Compustat) |
| Does a profitability/quality premium exist? | gross profit, assets (Compustat) |
| Does the size (SMB) premium exist here? | shares outstanding → market cap (CRSP) |
| Does apparent alpha come from sector tilts? (M14 Phase 4, skipped) | sector/industry codes (GICS/SIC) |
| Post-earnings-announcement drift / SUE | earnings dates + surprises |

**All seven are method-complete and data-starved.** None needs new research technique.

## 2. Audit question 2 — campaigns requiring CRSP/Compustat

| Campaign | Needs | Why hard-blocked |
|---|---|---|
| FF3 / FF5 / Carhart attribution (the M13/M14 unblock) | CRSP shares + Compustat | no cap-weighted market, no SMB/HML |
| Value (HML, B/M, earnings yield) | Compustat | no book equity/earnings |
| Quality / profitability (Novy-Marx) | Compustat | no gross profit/assets |
| Investment / asset-growth factor | Compustat | no balance-sheet deltas |
| Size (SMB) | CRSP shares outstanding | no market cap |
| Survivorship re-certification of ALL prior verdicts | CRSP delisting returns | current panel drops dead names |
| Sector-neutral construction + sector attribution | sector codes (may ship with CRSP/Compustat) | no classification metadata |

This wing is ~**110 backlog ideas** (Value 40 + Quality 35 + Fundamental 35) — the
single largest untapped block, all behind Compustat.

## 3. Audit question 3 — campaigns runnable NOW on existing Yahoo OHLCV

Runnable with zero new data (all price/volume functions). **Ceiling:** each caps at
DEFER on attribution until §2 lands — useful for sign/robustness/orthogonality, not for
a certified alpha claim.

| Campaign | Family | Code ready? | Note |
|---|---|---|---|
| Short-term (1-month) reversal | mean-reversion | driver-adjacent (`MeanReversionStrategy`) | well-powered, orthogonal to rejected momentum |
| MAX / lottery effect (Bali 2011) | vol/lottery | new driver, OHLCV only | negatively correlated w/ low-vol (partial overlap) |
| Time-series (absolute) momentum / trend | trend | new driver | distinct construction from REJECTED cross-sectional momentum |
| Volatility-managed overlay (Moreira-Muir) | meta/overlay | wraps any sleeve | scales gross by realized vol; applies to any signal |
| Pairs / stat-arb at scale (Gatev) | mean-reversion | **driver exists** | untested at panel scale; under-powered only on toy data |
| Amihud illiquidity | liquidity | new driver, OHLCV only | **weak here** — survivorship-biased liquid panel guts the premium |

Degraded-but-tempting (do NOT prioritise): idiosyncratic-vol (Ang) and low-beta/BAB
both need a market residual/beta — the equal-weight proxy is **mis-specified** (M14 §7:
pooled β 0.01 vs rolling 0.49). Running them on the bad proxy reproduces the M14 defect.
Defer to CRSP cap-weighted market.

## 4. Audit question 4 — expected research value per remaining factor

`EIG` = expected information gain (0–10). `P(pub)` = probability of publication-quality
evidence **on the achievable data**. `Data-cap` = best verdict reachable before §2.

| Factor / campaign | EIG | Impl cost | Data needed | P(pub) | Data-cap now |
|---|---|---|---|---|---|
| **FF/Carhart attribution infra** | **9.5** | Med | CRSP+Compustat | 0.85 | — (unblocks others) |
| **Survivorship re-certification** | **9.0** | Low | CRSP delisting | 0.80 | — (fixes all priors) |
| Value (HML) | 8.5 | Med | Compustat | 0.75 | blocked |
| Quality / profitability | 8.0 | Med | Compustat | 0.70 | blocked |
| Short-term reversal | 7.5 | Low | none (Yahoo) | 0.55 | **DEFER** |
| Vol-managed overlay | 7.0 | Low | none (Yahoo) | 0.55 | DEFER |
| Pairs / stat-arb at scale | 6.8 | Low (code exists) | none (Yahoo) | 0.50 | DEFER |
| Time-series momentum | 6.5 | Low | none (Yahoo) | 0.50 | DEFER |
| Size (SMB) | 6.0 | Low | CRSP shares | 0.55 | blocked |
| MAX / lottery | 6.0 | Low | none (Yahoo) | 0.45 | DEFER (overlaps low-vol) |
| Investment / asset-growth | 5.5 | Med | Compustat | 0.55 | blocked |
| Sector attribution | 5.5 | Low | sector codes | 0.60 | blocked |
| Idio-vol / low-beta | 5.0 | Low | CRSP mkt (proxy fails) | 0.35 | degraded → defer |
| Amihud illiquidity | 4.0 | Low | none (Yahoo) | 0.30 | DEFER (survivorship guts it) |

**Read:** the two highest-EIG items are *infrastructure/data* (attribution +
survivorship), not new factors. The highest-EIG *new factor* (value, 8.5) is blocked.
The best *runnable* factor (short-term reversal, 7.5) is DEFER-capped at 0.55 P(pub).

## 5. Audit question 5 — dependency graph (DAG, not a sequence)

```
                         ┌─────────────────────────────┐
   HAVE: Yahoo OHLCV ───▶│ Immediate OHLCV campaigns:  │
   (price+volume)        │  short-term reversal, MAX,  │──▶ sign/robustness only
        │                │  TS-momentum, vol-overlay,  │    (all CAP at DEFER-attribution)
        │                │  pairs-at-scale             │
        │                └─────────────────────────────┘
        └─▶ equal-weight market proxy ──X mis-specified (M14) ──X quality-blocked

   ┌──────────────── DATA UPGRADES ────────────────┐        ┌──── INFRA ────┐
   │ CRSP:shares outstanding ─┬─▶ cap-weight mkt module ─┬─▶ FF/Carhart      │
   │                          └─▶ Size (SMB)             │   attribution ────┼─▶ RE-CERTIFY
   │ CRSP:delisting returns ────▶ survivorship correction┘   (certified)     │   low-vol DEFER
   │ Compustat fundamentals ──▶ fundamentals feature ───┬─▶ Value (HML)      │   → ADOPT/REJECT
   │                            family (cat-C infra)     ├─▶ Quality         │   + re-test
   │ Sector codes ────────────▶ sector-neutral construct │   └─▶ Investment  │   momentum/low-vol
   │                            + sector attribution      │                  │   REJECTs
   │ Earnings/analyst feed ───▶ PEAD / SUE / revisions    │                  │
   └──────────────────────────────────────────────────────┘                  └───────────────┘

  Critical path to a CERTIFIABLE alpha:
     CRSP(shares) ─▶ cap-weight mkt ─▶ FF attribution ─▶ resolves M13/M14 DEFER
  Widest unblock (most new campaigns):
     Compustat ─▶ fundamentals feature family ─▶ Value + Quality + Investment (~110 ideas)
  Highest credibility-per-effort:
     CRSP(delisting) ─▶ survivorship correction ─▶ re-credentials EVERY prior verdict
```

Edges are `requires`. Note two nodes gate almost everything downstream: **CRSP shares**
(→ market model → attribution) and **Compustat** (→ the entire fundamental wing). They
are independent of each other and can be procured in parallel.

---

## 6. Ranked campaign register

Composite priority = EIG × P(pub) ÷ cost, adjusted for whether it unblocks others.

### Immediate campaigns (runnable now, Yahoo OHLCV, DEFER-capped)
1. **Short-term reversal** — highest immediate EIG (7.5), low cost, orthogonal to the
   rejected momentum, well-powered. Best pure-strategy screen available today.
2. **Pairs / stat-arb at scale** — driver already exists; cheapest to run; opens the
   untested mean-reversion family at panel scale.
3. **Volatility-managed overlay** — meta-campaign; wraps the low-vol DEFER book and any
   future sleeve; tests whether vol-scaling lifts the modest Sharpe.
4. **Time-series momentum** — distinct construction from the rejected cross-sectional
   momentum; cheap; closes the "is *any* momentum here" question.

   *(MAX, Amihud, idio-vol/BAB explicitly deprioritised — overlap, survivorship, or the
   mis-specified proxy. Documented, not silently dropped.)*

### Blocked campaigns (need §7 data first)
Value, Quality/profitability, Investment, Size, FF/Carhart attribution, sector
attribution, survivorship re-certification, PEAD/SUE. Highest-EIG block in the program;
all data-gated, none method-gated.

### Data upgrades (ranked by unblock leverage)
1. **CRSP — delisting returns** (survivorship correction; re-credentials ALL priors) —
   *highest credibility-per-dollar.*
2. **CRSP — shares outstanding** (cap-weighted market → FF attribution → resolves the
   two DEFERs; + Size) — *critical path to a certifiable alpha.*
3. **Compustat fundamentals** (Value + Quality + Investment; ~110 backlog ideas) —
   *widest campaign unblock.*
4. **Sector / industry codes** (sector-neutral construction + M14 Phase 4).
5. **Earnings / analyst feed** (event wing: PEAD, SUE, revisions).
6. **Real risk-free term series** (small; replaces the flat 5% approximation; tightens
   Sharpe/attribution precision).

### Infrastructure upgrades (build just-in-time before the consuming campaign)
1. **Cap-weighted market factor module** — consumes CRSP shares; prerequisite for FF.
2. **FF/Carhart attribution as a first-class certified module** — M14 built this ad-hoc;
   productionise + test it.
3. **Fundamentals feature family (category C)** — consumes Compustat; prerequisite for
   Value/Quality. Build only when a fundamentals dataset is actually in hand (v1 rule).
4. **Sector-neutralization in portfolio construction** — consumes sector codes.
5. **Point-in-time / as-of dating layer** — look-ahead guard for fundamentals (M9-style).

---

## 7. Recommended execution order (two parallel tracks)

**The recommendation is not a single next campaign — it is a parallel plan, because the
binding constraint (data) and the cheap screens are independent.**

**Track A — procure data (the real gate, start immediately, off critical compute):**
1. Acquire **CRSP** (delisting + shares) → build cap-weighted market module → stand up
   the FF/Carhart attribution module → **re-run M14 attribution** (resolves M13/M14
   DEFER to ADOPT/REJECT) and **survivorship-correct M11/M12/M13** (re-credentials the
   momentum + low-vol verdicts).
2. In parallel acquire **Compustat** → fundamentals feature family → **Value** then
   **Quality** campaigns (largest untapped EIG block).
3. Then **sector codes** → sector-neutral construction + M14 Phase 4.

**Track B — cheap OHLCV screens now (keep the pipeline warm, map orthogonality):**
Run **short-term reversal** first (top immediate EIG), then **pairs-at-scale** (code
ready). Treat outputs as sign/robustness/orthogonality probes only — each will DEFER on
attribution by construction until Track A lands. Do **not** run idio-vol/BAB on the
mis-specified proxy.

**One-line call:** the highest-value next campaign is the **CRSP upgrade + FF-attribution
infrastructure** — it is the only move that converts DEFER into a verdict and audits the
two REJECTs. If a strategy campaign must run on today's data, it is **short-term
reversal**, understood upfront as DEFER-capped.

## 8. Limitations of this roadmap (CLAUDE.md)

- **Value scores are pre-test priors,** not measured edges (consistent with
  `HYPOTHESIS_BACKLOG.md`); they rank the queue, not the alpha.
- **P(pub) figures are judgment,** anchored to literature strength × achievable data
  quality — not computed.
- **Data-acquisition feasibility/cost of CRSP/Compustat is out of scope** here (licensing
  is a procurement question, not a research one); this audit ranks *value if acquired*.
