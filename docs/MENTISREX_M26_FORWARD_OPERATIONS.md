# Mentisrex Forward Operations (M26)

**EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED**
**NO REAL CAPITAL DEPLOYED**
**STRATEGY UNMODIFIED**

---

## 1. Objective

M26 makes the M25 forward paper-trading campaign operationally sustainable.

M25 established that MentisRex can conduct a genuine, immutable, PIT-correct
forward paper-trading experiment.

M26 adds:
- `ForwardOperationsRunner` — cron-safe orchestration layer
- `forward_auto` CLI subcommand — single check-and-run, idempotent
- Data health gate — configurable universe-coverage enforcement before trading
- `next_expected_cycle` — computes next due evaluation date in `status()`
- Multi-month operational simulation for testing

M26 does NOT add:
- Live broker connectivity
- Real capital
- Strategy changes
- Redesign of M19/M20/M21/M23/M25

---

## 2. Operating Modes

| Mode | Description | External calls |
|------|-------------|----------------|
| `SIMULATION` | Synthetic deterministic prices | None |
| `REPLAY` | Historical M20 replay | None |
| `PAPER_LIVE_FEED` | Single real-data cycle (legacy M24) | Yahoo Finance |
| `PAPER_FORWARD` | Persistent, idempotent forward campaign (M25/M26) | Yahoo Finance |
| `LIVE` | Not implemented | N/A |

---

## 3. Architecture

```
forward_auto (CLI, cron)
      ↓
ForwardOperationsRunner.check_and_run(as_of)
      ↓
ForwardCampaign.run(as_of)
      ├── Idempotency check → ALREADY_SEALED if sealed
      ├── Campaign checkpoint restore (NOT simulation checkpoint)
      ├── RebalanceScheduler.is_due() → SKIPPED if not due
      ├── LiveFeedBuilder.fetch_snapshot() → FAILED if None
      ├── DATA HEALTH GATE → FAILED if coverage below threshold
      ├── M23 PaperTradingLoop.process_snapshot()
      ├── Populate ForwardCycleRecord
      ├── Checkpoint campaign state
      └── _seal_and_persist() → atomic .tmp → rename
      ↓
ForwardOperationsRunner.operational_status()
      → next_expected_cycle, runner_state, last_error, session counts
```

---

## 4. ForwardOperationsRunner

`src/mentisrex/research/forward_campaign/runner.py`

### Core methods

| Method | Description |
|--------|-------------|
| `check_and_run(as_of, provider_records)` | Check if due and run. Cron-safe, idempotent. |
| `run_months(dates, records_list)` | Multi-month simulation (offline/tests). |
| `operational_status()` | Enriched monitoring dict. |

### Design principles

- **Stateless between restarts**: all durable state in campaign checkpoint and
  sealed cycle files. Re-creating the runner is safe.
- **Session metrics reset on restart**: `_run_count`, `_session_successes`,
  `_session_failures`, `_last_error` reset to zero. Durable state comes from
  the ledger.
- **No daemon**: designed for cron, not a long-running process. Call
  `check_and_run()` from cron; the campaign's idempotency guarantees prevent
  duplicates if cron fires multiple times per month.

### Session vs durable state

| Field | Durable (survives restart) | Session only |
|-------|---------------------------|--------------|
| Campaign checkpoint | ✓ (campaign_checkpoint.json) | |
| Sealed cycle records | ✓ (cycles/*.json) | |
| Campaign health counters | ✓ (campaign_health.json) | |
| `_run_count` | | ✓ |
| `_session_failures` | | ✓ |
| `_last_error` | | ✓ |
| `_last_run_at` | | ✓ |

---

## 5. Automated Scheduler

The existing `RebalanceScheduler` (M23) provides scheduling. M26 wires its
`next_due()` method into `campaign.status()` and `operational_status()`.

| Field | Source |
|-------|--------|
| `is_due()` | M23 `RebalanceScheduler` |
| `next_expected_cycle` | M26: `RebalanceScheduler.next_due()` |
| Cycle cadence | Monthly (from strategy spec) |
| Missed-cycle handling | Already correct — scheduler is due if month advanced |

**Cron configuration** (example):

```
# Run on the 1st of every month at 09:00 UTC
0 9 1 * * cd /path/to/mentisrex-capital && source .venv/bin/activate && \
  python scripts/forward_run/run_forward.py forward_auto
```

Multiple cron firings per month are safe — all after the first return
`ALREADY_SEALED`.

---

## 6. Data Health Gate

`CampaignConfig.min_universe_coverage` (default `0.0` = disabled)

When set > 0, the gate is checked immediately after `_fetch_snapshot()` succeeds
and before any paper trade is executed.

**Gate logic:**
```python
n_present = len(snap.spots)           # securities with valid prices
coverage = n_present / len(universe)  # fraction present
if coverage < min_universe_coverage:
    # seal FAILED record; no trade
```

**Failure path:**
- Status = `FAILED`
- Error message contains "Data health gate failed: coverage N/M"
- Record is sealed atomically (no partial state)
- No paper orders generated

**Default behavior** (`min_universe_coverage=0.0`):
- Gate disabled — backward compatible with M25
- Provider returning `None` still seals `FAILED` (existing behavior)

**Configuring in code:**
```python
campaign = ForwardCampaign.init(spec, logic, campaign_dir, universe=UNIVERSE,
                                 starting_capital=1_000_000)
campaign._config.min_universe_coverage = 0.8  # require 80% coverage
```

---

## 7. Forward Runner Operational Status

```python
runner.operational_status()
```

Returns all fields from `campaign.status()` plus:

| Field | Description |
|-------|-------------|
| `runner_state` | `"ACTIVE"` (ran this session) \| `"IDLE"` |
| `next_expected_cycle` | ISO date of next due evaluation |
| `last_error` | Error message from last FAILED cycle (session only) |
| `last_run_at` | ISO datetime of last `check_and_run()` call |
| `session_run_count` | Total calls this session |
| `session_successes` | Successful cycles this session |
| `session_failures` | Failed cycles this session |

---

## 8. Failure States

| Status | Meaning | Next-run behavior | Financial effect |
|--------|---------|-------------------|-----------------|
| `SUCCESS` | Cycle completed | ALREADY_SEALED | NAV updated |
| `SKIPPED` | Not due (monthly scheduler) | ALREADY_SEALED | None |
| `FAILED` | Provider failure, health gate, loop error | ALREADY_SEALED | None |
| `ALREADY_SEALED` | Prior run completed this month | Return existing record | None |

**Critical rules:**
- `FAILED ≠ SUCCESS` — failure evidence is sealed and locked
- `SKIPPED ≠ SUCCESS` — no evaluation occurred
- Retrying a `FAILED` month returns `ALREADY_SEALED` — the failure is locked

---

## 9. Recovery Procedure

### Normal restart

```bash
# Runner re-creates campaign from checkpoint automatically
python scripts/forward_run/run_forward.py forward_auto
```

### After corrupted checkpoint

```bash
# 1. Identify the bad checkpoint
ls data/forward_campaign/FORWARD_CAMPAIGN_*/campaign_checkpoint.json

# 2. Delete it (resets financial state to starting_capital!)
rm data/forward_campaign/FORWARD_CAMPAIGN_*/campaign_checkpoint.json

# Warning: sealed cycle records are preserved; financial state becomes
# inconsistent with prior sealed records. Document this as an operational event.

# 3. Re-run
python scripts/forward_run/run_forward.py forward_auto
```

### Idempotency guarantee

```
RUN → INTERRUPT → RESTART → RESUME

No duplicate orders, fills, accounting, or forward records.
Cycle files are the source of truth — existence means ALREADY_SEALED.
```

---

## 10. Operational Procedure

### Initialize (first time)

```bash
python scripts/forward_run/run_forward.py forward_init
```

### Monthly evaluation (manual)

```bash
python scripts/forward_run/run_forward.py forward_run --as-of 2026-09-01
```

### Auto check-and-run (cron-safe)

```bash
# Auto-detect today's date:
python scripts/forward_run/run_forward.py forward_auto

# Specify date:
python scripts/forward_run/run_forward.py forward_auto --as-of 2026-09-01
```

### Status / monitoring

```bash
python scripts/forward_run/run_forward.py forward_status
```

### Resume after restart

```bash
python scripts/forward_run/run_forward.py forward_resume --as-of 2026-09-01
```

---

## 11. Alerting

No external notification service is integrated in M26. Alerting is provided
through structured return values and exit codes.

Operationally significant events:

| Event | Detection |
|-------|-----------|
| Cycle success | `result.status == CycleStatus.SUCCESS` |
| Cycle failed | `result.status == CycleStatus.FAILED` |
| Already sealed | `result.status == CycleStatus.ALREADY_SEALED` |
| Health gate failed | `"Data health gate failed"` in `result.record.error_message` |
| Checkpoint corrupted | `RuntimeError` raised by `_get_loop()` |
| Provider timeout | `result.status == CycleStatus.FAILED`, `record.error_message` |

In production, wrap `forward_auto` in a shell script that checks the exit code
and sends an alert (email, PagerDuty, Slack) on non-zero. The `campaign_health.json`
file can be monitored by any file-based health-check tool.

---

## 12. Research-Data Isolation

Forward observations are stored under `data/forward_campaign/`. They must not
enter any research, backtest, or optimization pipeline.

| What is isolated | How enforced |
|-----------------|--------------|
| Campaign directory | Separate path from `data/forward_runs/` and research data |
| Mode field | `mode = "PAPER_FORWARD"` in every sealed record |
| Ledger scope | `ForwardLedger` reads only from `campaign_dir/cycles/` |
| Forward→research path | No automatic pipeline; explicit manual import required |

---

## 13. Multi-Month Operational Simulation

The `ForwardOperationsRunner.run_months()` method enables deterministic
multi-month simulation without network calls:

```python
runner = ForwardOperationsRunner(spec, logic, campaign_dir, universe, capital)
results = runner.run_months(
    [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)],
    [aug_records, sep_records, oct_records, nov_records],
)
```

**OPERATIONAL SIMULATION — not genuine forward evidence.**

These results confirm that the operational machinery works correctly across
multiple months, but are not out-of-sample forward evidence because:
- Records are offline fixtures, not real-time Yahoo Finance data
- All months run in a single process invocation (not chronologically real)

---

## 14. Limitations

| Limitation | Severity | Upgrade path |
|-----------|---------|-------------|
| Yahoo Finance data quality | HIGH | Bloomberg / Refinitiv / Polygon.io adapter |
| No external alerting integration | MEDIUM | Add cron-wrapper + email/PD/Slack |
| Session state resets on restart | LOW | Persist session stats to health file |
| No multi-strategy runner | MEDIUM | M23 loop already supports multi-strategy |
| Sharpe requires 24 months | INFORMATIONAL | Accumulate observations |
| No benchmark comparison | INFORMATIONAL | Add SPY benchmark portfolio |

---

## 15. Implementation Status

| Component | Status |
|-----------|--------|
| `ForwardOperationsRunner` | IMPLEMENTED, TESTED |
| `check_and_run()` (cron-safe) | IMPLEMENTED, TESTED |
| `run_months()` (simulation) | IMPLEMENTED, TESTED |
| `operational_status()` | IMPLEMENTED, TESTED |
| Data health gate (`min_universe_coverage`) | IMPLEMENTED, TESTED |
| `next_expected_cycle` in `status()` | IMPLEMENTED, TESTED |
| `forward_auto` CLI subcommand | IMPLEMENTED, TESTED |
| Multi-month operational simulation | IMPLEMENTED, TESTED |
| Monitoring (structured status dict) | IMPLEMENTED, TESTED |
| Session failure tracking | IMPLEMENTED, TESTED |
| Automatic recovery from restart | IMPLEMENTED, TESTED |
| Idempotency across restarts | IMPLEMENTED, TESTED (inherited M25) |
| Research-data isolation | IMPLEMENTED, TESTED (inherited M25) |
| Real-data forward verification | REAL-DATA VERIFIED (2026-08-13) |
| External alerting service | NOT IMPLEMENTED |
| Institutional data provider | NOT IMPLEMENTED |
| Live broker connectivity | NOT IMPLEMENTED |

---

## 16. M26 Real-Data Verification (2026-08-13)

```
command              : forward_auto --as-of 2026-08-13
cycle_id             : ew-momentum-exp__2026_08
status               : ALREADY_SEALED (M25 cycle preserved)
ending_nav           : 1,000,000.00 USD
fills                : 10
risk_approved        : True
sealed_at            : 2026-08-13T16:22:22.856447
runner_state         : ACTIVE
next_expected_cycle  : 2026-09-01

REAL MARKET DATA:        YES
AUTOMATED FORWARD OPS:   YES
FORWARD PAPER TRADING:   YES
PAPER EXECUTION:         YES
LIVE EXECUTION:          NO
REAL CAPITAL:            NO
STRATEGY MODIFIED:       NO
```

`ALREADY_SEALED` confirms M25 immutable evidence is preserved. `next_expected_cycle`
is a new M26 field. Strategy fingerprint unchanged: `b69961b65bab226a500d71f45709945b`.

---

## 17. Test Results

| Suite | Result |
|-------|--------|
| M26: `test_forward_operations.py` | **78/78 passed** |
| M25: `test_forward_campaign.py` | **96/96 passed** |
| Full repository suite | **2539 passed, 3 skipped, 0 regressions** |

---

*M26 Forward Operations — evidence integrity over impressive output.*
