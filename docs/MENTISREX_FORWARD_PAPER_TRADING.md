# Mentisrex Forward Paper-Trading Campaign (M25)

**EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED**  
**NO REAL CAPITAL DEPLOYED**  
**STRATEGY UNMODIFIED**

---

## 1. Purpose

This document describes the M25 Forward Paper-Trading Campaign layer. Its sole
purpose is to establish that:

> "MentisRex can maintain a chronological, restart-safe, idempotent,
> PIT-correct, immutable forward paper-trading experiment whose results can
> later be used as genuine out-of-sample evidence."

M25 does NOT claim:
- Profitability or alpha
- Statistical significance
- Institutional-grade data
- Live broker connectivity
- Economic validity

M25 proves only that the evidence infrastructure is sound. A successful
campaign may produce zero or negative strategy performance. That is acceptable
and expected.

---

## 2. Operating Modes

| Mode | Description | External calls |
|------|-------------|---------------|
| `SIMULATION` | Synthetic deterministic prices | None |
| `REPLAY` | Historical M20 replay | None |
| `PAPER_LIVE_FEED` | Single real-data cycle (legacy M24 name) | Yahoo Finance |
| `PAPER_FORWARD` | **Persistent, idempotent forward campaign (M25)** | Yahoo Finance |
| `LIVE` | Not implemented — no real broker | N/A |

`PAPER_FORWARD` is the only mode that maintains persistent, chronological,
sealed forward evidence across multiple executions. It is **semantically
distinct** from `SIMULATION`: PAPER_FORWARD uses only information available at
the current decision point; SIMULATION uses pre-generated synthetic prices.

---

## 3. Forward-Cycle Lifecycle

```
forward_init  →  ForwardCampaign created with clean state
                 (no SIMULATION contamination)
      ↓
forward_run(as_of)
      ├── Check if cycle_id already sealed → ALREADY_SEALED (no effect)
      ├── Restore campaign checkpoint (not SIMULATION checkpoint)
      ├── Schedule check: is strategy due?
      │     └── No → seal SKIPPED record
      ├── Fetch real market data (LiveFeedBuilder → Yahoo Finance)
      │     └── Failure → seal FAILED record
      ├── M21 → M20 → M19 → M18 pipeline (existing, unmodified)
      ├── M23 PaperTradingLoop.process_snapshot()
      ├── Collect accounting state
      ├── Write sealed ForwardCycleRecord atomically
      ├── Save campaign checkpoint
      └── SEALED (SUCCESS | FAILED | SKIPPED)
      ↓
forward_status  →  ledger.performance_summary()
```

---

## 4. Scheduler Semantics

Strategy: `rebalance_frequency = "monthly"`

| Scenario | Behavior |
|----------|----------|
| First cycle ever | Always due |
| Same month as last eval | `not_due` → SKIPPED |
| Next calendar month | Due → evaluate |
| Process was offline on intended date | Still due when process resumes |
| Data arrives late in month | Still runs (uses best available data) |
| Restart after snapshot | Restores campaign checkpoint; scheduler resumes from `last_eval_date` |
| Same date executed twice | Second call → ALREADY_SEALED |
| Previous run partially completed | Sealed record exists or not; ALREADY_SEALED or fresh run |
| Cycle `cycle_id` sealed with FAILED | Subsequent calls return ALREADY_SEALED (failed evidence locked in) |

The `not_due` issue observed in M24 (commit cbcd4d1 smoke test) was caused by
the `run_live_cycle()` function restoring the SIMULATION checkpoint, which had
`last_eval_date = 2026-12-01` (synthetic future). M25 fixes this by using a
completely separate checkpoint path for `PAPER_FORWARD` state.

---

## 5. State Isolation

**SIMULATION** state: `data/forward_runs/{RUN_ID}/checkpoint.json`  
**PAPER_FORWARD** state: `data/forward_campaign/{CAMPAIGN_ID}/campaign_checkpoint.json`

These paths are entirely separate. `forward_init` creates a fresh
`PaperTradingLoop` with `last_eval_date = None`. It never reads the SIMULATION
checkpoint. Contamination is structurally impossible.

---

## 6. Cycle Identity

Every forward evaluation has a deterministic, human-readable identity:

```
cycle_id = f"{strategy_id}__{evaluation_date.year}_{evaluation_date.month:02d}"

# Example:
# strategy_id = "ew-momentum-exp"
# evaluation_date = 2026-08-13
# cycle_id = "ew-momentum-exp__2026_08"
```

This identity is:
- Deterministic: same inputs → same `cycle_id`, always
- Human-readable: readable audit trail
- Month-scoped: any date within the same calendar month maps to the same cycle
- Immutable: once sealed, the file `cycles/{cycle_id}.json` is never overwritten

---

## 7. Immutable Records

Each sealed forward cycle is persisted as an individual JSON file:

```
data/forward_campaign/{CAMPAIGN_ID}/
├── campaign_manifest.json       ← created once at init; identifies campaign
├── campaign_checkpoint.json     ← M23 loop state; updated after each cycle
├── campaign_health.json         ← operational counters
└── cycles/
    ├── ew-momentum-exp__2026_08.json   ← sealed, never overwritten
    ├── ew-momentum-exp__2026_09.json
    └── ...
```

Sealing is enforced by:
1. Atomic write: `.tmp` → rename. Crash mid-write never produces a corrupt file.
2. "If file exists, never write." The store skips the write if the cycle file
   already exists, regardless of what the new execution would produce.
3. `sealed_at` timestamp in the record. Once non-empty, the record is frozen.

---

## 8. Yahoo Finance Limitations

Yahoo Finance via `yfinance` is a free/public provider. It is NOT equivalent to
Bloomberg, Refinitiv, or institutional exchange-grade data.

Known limitations:
- Retroactive split/dividend adjustments: `adj_close` may be revised after the fact
- Occasional data gaps or missing tickers
- Delayed data (not real-time)
- `adj_close / close` ratio inconsistency possible

### OBSERVED_AT_TIME vs CURRENT_PROVIDER_VALUE

M25 preserves `OBSERVED_AT_TIME` semantics:

- The `snapshot_fingerprint` in every sealed record captures exactly what data
  was used during that evaluation.
- If Yahoo later revises historical values, re-fetching produces a **different
  snapshot fingerprint** → a different cycle would be needed for a different date.
- The sealed forward record for August 2026 always reflects what Yahoo reported
  on August 13, 2026 — not what Yahoo reports today.

This is enforced by the idempotency mechanism: once `ew-momentum-exp__2026_08.json`
is sealed, no subsequent call to `forward_run(as_of=<any August 2026 date>)` will
modify it.

---

## 9. PIT Semantics

PIT (Point-in-Time) enforcement operates at two levels:

1. **M19 PITPolicy**: `reject_look_ahead=True`. Any observation with
   `observation_date > as_of` is rejected before reaching the strategy.

2. **Campaign semantics**: The strategy logic (`EqualWeightMomentumLogic`)
   reads only `snapshot.spots` — prices available at `as_of`. It makes no
   external calls and has no access to future data.

The M24 smoke test reported 0 PIT violations. The M25 real-data forward cycle
also reports 0 PIT violations (logged in `campaign_health.json`).

---

## 10. Revision Semantics

| Scenario | Behavior |
|----------|----------|
| Yahoo revises `adj_close` retroactively | Sealed record unchanged; revision only matters if a new cycle date is evaluated |
| Re-run same month with revised data | ALREADY_SEALED — original record returned |
| Provider data improves (newer source) | Migration path: evaluate next month; prior records immutable |
| Corrupted record file | Forward campaign fails explicitly; checkpoint remains valid |

---

## 11. Checkpoint / Restart

The campaign checkpoint captures:
- M23 `PaperTradingLoop` cycle counter and seen-snapshot set
- Per-strategy runtime state (`last_eval_date`, `evaluation_count`, etc.)
- Per-strategy portfolio state (cash, holdings, realized P&L)
- Per-strategy broker state (order book, fill IDs)
- Cycle records list

On restart:
1. `ForwardCampaign.resume()` loads the campaign checkpoint from `campaign_checkpoint.json`.
2. The sealed cycle files in `cycles/` are the primary evidence — if a cycle
   file exists, the cycle is ALREADY_SEALED regardless of checkpoint state.
3. If the checkpoint is corrupted, `_get_loop()` raises `RuntimeError` with an
   explicit message. Delete the checkpoint to restart with clean portfolio state.

**Warning:** deleting the checkpoint resets portfolio/accounting state to
`starting_capital`. Sealed cycle records are preserved. The resulting financial
state will be inconsistent with the sealed records if positions existed. This is
an operational decision that must be documented.

---

## 12. Idempotency

| Event | Result |
|-------|--------|
| Run once | 1 sealed record, 1 financial effect |
| Run again (same month) | ALREADY_SEALED, 0 additional financial effect |
| Restart after checkpoint | Resume from checkpoint; sealed records detected |
| Restart after partial write | `.tmp` file removed by OS; next run executes cleanly |
| Restart after full seal | cycle file exists → ALREADY_SEALED |
| Provider returns revised data for same month | cycle file exists → ALREADY_SEALED |

---

## 13. Failure States

| Status | Meaning | Next run behavior |
|--------|---------|-------------------|
| `SUCCESS` | Cycle completed and sealed | ALREADY_SEALED |
| `SKIPPED` | Strategy not due (monthly scheduler) | ALREADY_SEALED |
| `FAILED` | Provider failure, snapshot empty, or loop error | ALREADY_SEALED (failed evidence is locked) |
| `ALREADY_SEALED` | Previous run already completed this cycle | Returns existing record |
| `PARTIAL` | In-memory only; never persisted (write is atomic) | — |

Critical rule: Do not silently convert failure into success. A FAILED record
is evidence of a failure. It counts as the evaluation for that month.

---

## 14. Performance Ledger

```python
from mentisrex.research.forward_campaign import ForwardLedger
ledger = ForwardLedger(campaign_dir)

ledger.list_cycles()           # all sealed cycles, chronological
ledger.get_cycle(cycle_id)     # specific cycle by id
ledger.latest_cycle()          # most recent SUCCESS
ledger.current_nav()           # NAV from latest SUCCESS
ledger.current_positions()     # positions from latest SUCCESS
ledger.performance_summary()   # ForwardPerformanceSummary
```

Insufficient-sample labelling:
- `sharpe_label = "INSUFFICIENT_SAMPLE"` when < 24 observations
- `annualized_return_label = "INSUFFICIENT_SAMPLE"` when < 12 observations
- `volatility_label = "INSUFFICIENT_SAMPLE"` when < 2 observations

Never annualize or compute Sharpe from fewer than the required observations.
Label explicitly rather than fabricate.

---

## 15. Monitoring

Each campaign run produces/updates `campaign_health.json`:

```json
{
  "campaign_id": "...",
  "strategy_fingerprint": "b69961b65bab226a500d71f45709945b",
  "mode": "PAPER_FORWARD",
  "cycle_count": 1,
  "successful_cycles": 1,
  "failed_cycles": 0,
  "skipped_cycles": 0,
  "already_sealed_skips": 0,
  "data_errors": 0,
  "last_nav": 1000000.0,
  "last_evaluation_date": "2026-08-13"
}
```

Feed metrics (per-cycle) are embedded in the `ForwardCycleRecord`:
- `observations_accepted` / `observations_rejected`
- `pit_violations`, `stale_observations`, `missing_securities`
- `fetch_latency_s`, `processing_latency_s`

---

## 16. Research-Data Isolation

Forward campaign data lives in `data/forward_campaign/`. It must not be used as:
- Training data for strategy parameter optimization
- Backtesting inputs
- Feature fitting

The `ForwardLedger` is read-only and is restricted to the campaign directory.
Importing forward results into research requires explicit, documented manual
steps — not an automatic pipeline connection.

The `mode = "PAPER_FORWARD"` field in every sealed record makes the origin
traceable and prevents silent mixing with SIMULATION or BACKTEST data.

---

## 17. Operational Procedure

### Initialize (first time):
```bash
python scripts/forward_run/run_forward.py forward_init
```

### Run monthly evaluation:
```bash
# Auto-detect today's date:
python scripts/forward_run/run_forward.py forward_run

# Or specify date:
python scripts/forward_run/run_forward.py forward_run --as-of 2026-09-01
```

### Show status:
```bash
python scripts/forward_run/run_forward.py forward_status
```

### Resume after restart:
```bash
python scripts/forward_run/run_forward.py forward_resume --as-of 2026-09-01
```

### Long-run operation:
Run `forward_run` once per month (or more frequently — idempotency guarantees
no duplicates). A simple cron job suffices:

```
0 9 1 * * cd /path/to/mentisrex-capital && source .venv/bin/activate && \
  python scripts/forward_run/run_forward.py forward_run
```

---

## 18. Limitations

| Limitation | Severity | Upgrade path |
|-----------|---------|-------------|
| Yahoo Finance data quality | HIGH | Bloomberg / Refinitiv / Polygon.io adapter |
| No real-time data | HIGH | Institutional data provider |
| Monthly rebalancing only (as designed) | MEDIUM | Extend spec.rebalance_frequency |
| Single strategy / account | MEDIUM | Multi-strategy loop already supported in M23 |
| No cross-sectional momentum lookback | MEDIUM | Strategy v2 with historical price window |
| Sharpe requires 24 months (~2 years) | INFORMATIONAL | Accumulate observations |
| No benchmark comparison | INFORMATIONAL | Add SPY benchmark portfolio |
| No transaction cost model beyond slippage_bps | LOW | Wire M14 execution models |

---

## 19. Future Institutional-Data Migration

When switching from Yahoo Finance to an institutional provider:

1. Implement a new M21 adapter for the new provider.
2. The existing M20/M19/M18/M23 pipeline remains unchanged.
3. Prior sealed forward records remain immutable — they reflect Yahoo data.
4. Start a new campaign (`forward_init`) for the new provider. Do not overwrite
   the Yahoo campaign's sealed records.
5. Document the provider transition explicitly as a new campaign identifier.

---

## 20. Requirements Before Live Capital

The following must be satisfied before any live capital deployment:

- [ ] Institutional-grade data provider (Bloomberg / Refinitiv / exchange)
- [ ] Real broker connectivity (M-future: broker adapter)
- [ ] Order management system integration
- [ ] Pre-trade risk limits reviewed by risk management
- [ ] Compliance review
- [ ] Statistical significance: minimum 3–5 years of forward evidence
- [ ] Drawdown analysis: maximum tolerable drawdown confirmed
- [ ] Capacity analysis: strategy capacity vs intended AUM
- [ ] Tax / legal entity review
- [ ] Operational runbook approved
- [ ] Disaster recovery tested

**None of the above are satisfied today. NO LIVE CAPITAL IS AUTHORIZED.**

---

## 21. Implementation Status

| Component | Status |
|-----------|--------|
| `ForwardCampaign` orchestrator | IMPLEMENTED, TESTED |
| `ForwardCycleRecord` sealed records | IMPLEMENTED, TESTED |
| `ForwardLedger` performance ledger | IMPLEMENTED, TESTED |
| `forward_init / run / resume / status` CLI | IMPLEMENTED, TESTED |
| PAPER_FORWARD state isolation from SIMULATION | IMPLEMENTED, TESTED |
| Deterministic cycle identity | IMPLEMENTED, TESTED |
| Idempotency / duplicate prevention | IMPLEMENTED, TESTED |
| Immutable sealing with atomic write | IMPLEMENTED, TESTED |
| Provider revision safety | IMPLEMENTED, TESTED |
| PIT enforcement (M19 PITPolicy) | IMPLEMENTED, TESTED (M19/M24) |
| Restart / resume | IMPLEMENTED, TESTED |
| Corrupted checkpoint detection | IMPLEMENTED, TESTED |
| Failure states (FAILED / SKIPPED) | IMPLEMENTED, TESTED |
| Insufficient-sample performance labels | IMPLEMENTED, TESTED |
| Research-data isolation | IMPLEMENTED, TESTED |
| Real-data forward cycle (Yahoo Finance) | REAL-DATA VERIFIED (2026-08-13) |
| Live broker connectivity | NOT IMPLEMENTED |
| Institutional data provider | NOT IMPLEMENTED |
| Bloomberg / Refinitiv adapter | NOT IMPLEMENTED |

---

## 22. M25 Real-Data Forward Test Result (2026-08-13)

```
strategy_id          : ew-momentum-exp
strategy_version     : 1.0.0
strategy_fingerprint : b69961b65bab226a500d71f45709945b
cycle_id             : ew-momentum-exp__2026_08
as_of                : 2026-08-13
status               : SUCCESS
ending_nav           : 1,000,000.00 USD
fills                : 10
risk_approved        : True

REAL MARKET DATA:      YES
FORWARD PAPER EVAL:    YES
PAPER EXECUTION:       YES
LIVE EXECUTION:        NO
STRATEGY MODIFIED:     NO

Second run (idempotency):
  status             : ALREADY_SEALED
  no duplicate financial effect
```

---

*Generated by M25 Forward Campaign implementation. Evidence integrity over
impressive output.*
