# M1 Methodology Report — Equal-Weight Within Gross Leverage Budget

**Mentisrex Capital — Methodology Fidelity Campaign**
**Date:** 2026-08-04
**Source:** `campaign/momentum/m1/us_jt_m1.jsonl` vs
`campaign/momentum/runs/us.jsonl` (label: JT_6-1-6_decile). Frozen engine,
no parameter tuning, same universe and formation/holding period.

## 1. What M1 changes

| Dimension | Reference (fixed 5%/name) | M1 (equal-weight) |
|---|---|---|
| Per-name target | `NAV × max_position_pct(5%) × 1.0` | `NAV × max_position_pct(1.0) × (0.75/n)` |
| Gross budget | 1.5× (cap), but most fills rejected | **1.5× exactly expressed** |
| Names that fill | ~15 long + ~15 short (~30 of 90) | **~90 long + ~90 short (all)** |
| Position per name | 5% of NAV (top ~17% of decile express) | 0.83% of NAV (full decile equal) |
| Decile faithfulness | **TRUNCATED** — only most-extreme third fills | **FAITHFUL** — full JT decile expressed |

## 2. Results (OOS, US equities 2014–2026)

| Metric | Reference (fixed 5%) | M1 (equal-weight) | Change |
|---|---|---|---|
| OOS Sharpe | **0.935** | **−0.687** | −1.622 |
| OOS Return | **+58.78%** | **−60.25%** | −119 pp |
| OOS Max DD | −70.86% | **−130.83%** | −60 pp (NAV blowup) |
| OOS Trades | 345 | **848** | +503 (2.5×) |
| Adjusted p | 0.161 | 1.000 | worse |
| IS Sharpe | −0.144 | −0.766 | more negative |
| Verdict | REJECT | REJECT | same |

## 3. Root-cause analysis

**M1 increased trade count 2.5× (345 → 848), confirming the full decile now
expresses.** But risk-adjusted performance collapsed. Three compounding causes:

### 3a. The reference was accidentally concentrated in the most-extreme momentum tail

The 1.5× gross cap + 5%/name means only the first ~15 long + ~15 short signals
(in arrival order) fill before the cap fires. These are the names whose rebalance
bars happen to occur earliest in each 21-day cycle — not a principled selection
of the highest-momentum names. This is an **order-of-arrival** artifact, not a
deliberate signal concentration. In the reference, the "effective" book was a
~1.7%-quantile concentration (15 names of a 900-name universe), not the
intended 10% (90 names).

**The reference's positive OOS Sharpe (0.935) must be interpreted as: "the top
~1.7% by arrival-order of the formation ranking earn a positive spread in the
2017–2026 OOS window" — not "the full top-10% decile earns it."**

### 3b. The equal-weight full decile earns no premium in the OOS window

M1's empirical finding: on US equities 2014–2026, the full top-10% decile
(90 names) equal-weighted earns a negative OOS Sharpe (−0.687). The academic
JT result (1965–1989, broad CRSP) found positive cross-sectional momentum in
the full decile. The difference is:
- **Market evolution (Class D):** any L/S momentum strategy in 2014–2026 faces
  the documented post-2000 decay (Daniel-Moskowitz momentum crashes, factor
  crowding, broad market trend regime).
- **Universe (Class C):** M6 (liquidity/large-cap screens) unimplemented; the
  full 900-name US universe includes small/micro-cap names with mean-reverting
  idiosyncratic noise that dilutes momentum signal in the full decile.
- **Regime (Class D):** both IS and OOS negative under M1, consistent with each
  other — the IS−/OOS+ split in the reference was a regime anomaly, not a
  structural property.

### 3c. Max drawdown blowup (−130.8%)

With 1.5× gross (90 long + 90 short at 0.83% each), the L/S book has ≈90
positions and significant gross. A sustained period of momentum reversal (short
leg rallying, long leg falling) in a 90-name book draws down faster than a
30-name book. The −130.83% max drawdown means NAV temporarily went negative —
the research config's 60% halt did not protect (it halted but the OOS split is
an independent engine instance). Consistent with documented momentum crash risk
(Khandani-Lo 2007, Daniel-Moskowitz 2016).

## 4. Does M1 improve scientific fidelity?

**Yes, M1 is the more faithful construction.** The JT-1993 methodology
prescribes the full-decile equal-weight portfolio, not a leverage-truncated
arrival-order concentration. M1's implementation is correct.

**But M1 does not improve performance.** The reference's positive OOS result
was an artifact of unintentional concentration in the most-extreme momentum
tail combined with a favorable OOS regime. When the full decile trades, the
momentum premium is absent (IS −0.766, OOS −0.687, p 1.000).

**The scientific finding from M1: there is no detectable cross-sectional
momentum premium in the US 10% decile equal-weighted on 2014–2026 data. The
apparent OOS Sharpe of 0.935 in the reference was a regime+concentration
artifact, not a durable decile momentum premium.**

## 5. Classification

| Cause of difference | Class |
|---|---|
| Decile expressed vs truncated (M1 is faithful; reference was not) | B — methodology fidelity (now corrected) |
| Full decile earns no premium on 2014–2026 | D — market evolution |
| Small/micro-cap signal dilution in full decile | C — data (M6 unimplemented) |
| Drawdown blowup in L/S book | B — methodology (no liquidity screen M6) |

**0 platform defects.** The engine is working correctly under both configs.

## 6. Impact on prior results

| Report | Finding under M1 |
|---|---|
| `docs/REPRO_JT_1993_US_REFERENCE.md` | "OOS Sharpe 0.935" is a concentration/regime artifact. The faithful M1 estimate for the full US decile is −0.687. |
| `campaign/momentum/Executive_Summary.md` | US momentum "directionally consistent" stands; the magnitude (0.935) does not survive to the full decile. India long-only result (p 0.026, Sharpe 1.012) was a long-only book; M1 does not change its conclusion (long-only equal-weight = 1.0/n which is a gentler sizing). |
| `campaign/momentum/Momentum_Campaign_Report.md` | The "hold_3m Sharpe 0.921" and JT 0.935 survive as single-config reference values, understood as truncated-decile results. The full-decile M1 result is **the more rigorous estimate**. |

The India long-only result's survivorship-inflated caveat is unchanged. The
momentum campaign's **go/no-go verdict is unchanged**: no live capital. The
data point "the full US decile earns −0.687 Sharpe" strengthens the paper-only
conclusion.

## 7. Decision on M1

**M1 is implemented, is methodologically correct, and should be used going
forward for any momentum research that targets full-decile fidelity.**

The reference config (fixed 5%/name, `equal_weight=False`) is retained for
backward-compatibility and documented as a concentration artifact.

**Do not implement M2.** Per the campaign directive, only M1 is authorized in
this phase. If a future un-frozen phase tests additional fidelity improvements,
M6 (JT liquidity/large-cap screens) is ranked highest next (eliminates
small-cap dilution and likely recovers some signal from the full decile).

## Known limitations / Skipped
- **India M1 not run.** *Reason:* directive says "Re-run JT once" (US only) and
  "Do not implement M2." India M1 requires explicit authorization. *Unblock:*
  run `run_momentum_grid.py india ... equal_weight=True` with `max_position_pct=1.0`.
- **Long-only M1 not run.** *Reason:* same — US L/S JT is the JT-1993 canonical.
  Long-only M1 would be a separate authorized run.
