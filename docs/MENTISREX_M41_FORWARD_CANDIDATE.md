# M41 — Frozen Forward Candidate: mom-12-1-india-cs

**Certification report.** Registers the one net-of-cost survivor from the clean
India sweep (M40) as an **immutable forward research candidate**. This is the
research-integrity act of "starting the clock": the factor definition is
fingerprinted and locked so it cannot be tuned after seeing forward results.
Independent of, and does not touch, the frozen `ew-momentum-exp v1.0.0`.

## Candidate
- **strategy_id:** `mom-12-1-india-cs`  **version:** 1.0.0
- **Definition (frozen):** monthly cross-sectional 12-minus-1-month price momentum,
  top-300 liquid NSE names, long top quintile / short bottom quintile, equal weight.
- **Frozen fingerprint:** `823e007d57305aca21a869b3f9ee799e`
- **Spec:** `campaign/momentum_12_1_candidate/spec.json`
- **Backtest evidence (survivorship-suspect):** net LS Sharpe 0.67, net HAC t 2.30,
  turnover 0.23, half-Sharpe capacity > ₹1B (M40).

## Why frozen now
Locking the definition before forward observation is the core control against
researcher degrees of freedom (§XIII): once the fingerprint is set, any change to
the formula, universe, or quintiles produces a *different* fingerprint — you cannot
quietly retune the "same" strategy after seeing which way forward returns went.

## What "running the forward campaign" requires (NOT yet done — no fabricated cycles)
The `ForwardCampaign` harness (M23-M30) is built and ready. To accrue real forward
evidence it needs, monthly:
1. A `StrategyLogic` implementing this spec's signal (thin wrapper over the existing
   cross-sectional momentum computation).
2. A **live daily NSE data feed** delivering PIT `provider_records` each cycle
   (the operational dependency — the same feed the frozen ew-momentum-exp uses).
3. `ForwardCampaign.init(spec, logic, data_dir, universe, capital)` then a monthly
   `campaign.run(as_of=today)` (idempotent, sealed per cycle).

Until (2) runs on a schedule, there is **zero forward evidence** — and this report
claims none. The clock starts the first sealed cycle.

## Explicit status (per CLAUDE.md — no silent gaps)
- **No forward cycles exist yet.** Only the definition is frozen. Not a claim of
  live/paper performance.
- **Survivorship-suspect.** Backtest numbers will likely fall once the PIT
  universe (Priority-1 data, `DATA_ACQUISITION_BRIEF.md`) is loaded. The candidate
  should be re-backtested — and re-frozen at a new fingerprint if the definition
  changes — once that data lands.
- **Shorting feasibility unresolved.** India cash segment has no overnight short;
  the short leg needs the F&O-eligible universe or a move to a long-only variant.
  Flagged in the data brief (Priority 4).

## Next
- Data-side (you): Priority-1 survivorship data → re-validate the candidate.
- Ops-side (me, when a daily feed is available): wire StrategyLogic + init the
  ForwardCampaign to begin accruing sealed cycles.
