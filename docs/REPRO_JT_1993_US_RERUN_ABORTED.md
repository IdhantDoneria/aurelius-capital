# JT 1993 Post-Remediation Rerun — ABORTED at Pre-Run Check

**Date:** 2026-07-31
**Decision:** run NOT executed. Aborted per mandate ("Abort if any condition fails").
**Verdict:** IMPLEMENTATION DEFECT — G2 remediation ineffective against the real
contamination signature.

## Pre-run check result

| Condition | Status |
|---|---|
| Production DuckDB only (`analytics.duckdb`) | PASS |
| Independent IS/OOS engine (G1) | PASS — `train_test` runs two independent backtests (`is_bars`/`oos_bars`), verified by tests |
| Same strategy / params / universe logic | PASS |
| Validated universe filter active | PASS (wired) |
| **No toy contamination in run universe** | **FAIL** |

## Evidence

`validated_universe_filter` admits all 9 toy tickers; run universe = **1016**, not
the clean **1007**.

- Toy series (`GE JPM KO META MSFT NVDA PG T XOM`): **520 bars** each, 2022-01-03
  → 2023-12-29, synthetic prices.
- Gate: `MIN_VALIDATED_BARS = 504`. **520 > 504 → toy passes.**
- Real US names: **≥ 2201 bars** (median 3162). Wide clean gap (520 vs 2201+);
  the threshold was simply set below the toy bar count.

## Why this is a re-opened defect, not a new one

The committed G2 fix (`isolation.py`) has two parts:
1. `assert_not_production` — write-side guard. **Effective** (prevents future
   toy writes).
2. `validated_universe_filter` — read-side gate. **Ineffective** — threshold
   504 is below the 520-bar toy series, so pre-existing contamination still
   enters a reproduction universe.

The G2 regression test used a 10-bar toy stub (`10 << 504`), which passed and
gave false confidence; it did not exercise the real 520-bar signature.

## Skip record (per CLAUDE.md)

- **Skipped:** the post-remediation JT reproduction run.
- **Reason:** pre-run check failed — the validated filter does not exclude the
  9 toy tickers (520 bars > 504-bar threshold), so any run would blend synthetic
  mega-cap series into the 2022–2023 window (which straddles the 2022-10-25
  IS/OOS boundary), invalidating the result.
- **What unblocks it (NOT implemented — no engineering authorized):**
  1. Raise `MIN_VALIDATED_BARS` above 520 (any value in (520, 2201] separates
     cleanly; e.g. 756 ≈ 3y). 2. Update the G2 regression test to use a 520-bar
     toy series so the real signature is covered. After that, re-run pre-run
     check and execute once.

## G1 status

G1 (independent IS/OOS) is in place and passes its regression tests; it was not
exercised end-to-end here because the run was correctly aborted before execution.
No G1 evidence is claimed from this attempt.
