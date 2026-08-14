# Mentisrex M30 — Monthly Forward Cycle Operational Checklist

**Strategy:** `ew-momentum-exp v1.0.0`  
**Fingerprint:** `b69961b65bab226a500d71f45709945b`  
**First genuine cycle:** September 2026 (run after 2026-09-01)  
**Live execution:** NO — Alpaca PAPER only  
**Real capital:** NO  

---

## When to Run

Run on or after the **first trading day of each month** (typically the 1st or
2nd business day). Data must be available for the prior month-end.

Do NOT run before September 1, 2026 for the genuine September cycle.

---

## Step 0 — Prerequisites (offline, any time before cycle day)

- [ ] Python environment active: `source .venv/bin/activate` or `uv run ...`
- [ ] `ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_API_SECRET` ready in shell  
  (do not hardcode; do not commit; rotate after use)
- [ ] Confirm today ≥ cycle date (e.g. ≥ 2026-09-01 for September cycle)
- [ ] Confirm strategy fingerprint is unchanged:
  ```bash
  uv run python -c "
  import sys; sys.path.insert(0, 'scripts/forward_run')
  from spec import SPEC
  print(SPEC.configuration_fingerprint)
  "
  # Expected: b69961b65bab226a500d71f45709945b
  ```

---

## Step 1 — System Health

```bash
uv run python scripts/forward_run/run_forward.py pre_cycle_check \
    --as-of YYYY-MM-DD \
    --data-dir data/forward_campaign/FORWARD_CAMPAIGN_ew-momentum-exp_v1.0.0_20260813
```

Expected output:
- `[OK] strategy_fingerprint : b69961b65bab226a500d71f45709945b`
- `[OK] campaign_manifest    : found`
- `[OK] cycle_id             : ew-momentum-exp__YYYY_MM` (not yet sealed)
- `OVERALL READINESS  : READY`

**If `[FAIL] strategy_fingerprint`:** STOP. The strategy has been modified.
Do not run the cycle. Investigate the change and resolve before proceeding.

---

## Step 2 — Market Data Health

The forward cycle fetches data from Yahoo Finance (yfinance) at run time.
Before running, manually verify:

```bash
uv run python -c "
import yfinance as yf
from datetime import date, timedelta
universe = ['AAPL','MSFT','GOOGL','AMZN','META','NVDA','TSLA','JPM','JNJ','V']
end = date.today()
start = end - timedelta(days=5)
for sym in universe:
    df = yf.download(sym, start=start, end=end, progress=False)
    if df.empty:
        print(f'MISSING: {sym}')
    else:
        price = float(df['Close'].iloc[-1])
        print(f'  {sym:6s}: {price:.2f}')
"
```

**Checks:**
- [ ] All 10 universe symbols return non-empty data
- [ ] No symbol has price ≤ 0
- [ ] Latest bar is within the last 3 trading days
- [ ] No obvious price anomalies (e.g. 100× normal range)

**Known data risks (inherent — not fixable with Yahoo Finance):**

| Risk | Description |
|---|---|
| `ADJUSTMENT_RETROACTIVE` | `auto_adjust=True` applies current adjustments retroactively. A pull tomorrow gives different historical prices. |
| `NO_POINT_IN_TIME_DB` | yfinance returns data as of today, not as of the exact evaluation moment. |
| `DELISTING_RISK` | A delisted symbol returns empty data → treated as MISSING in the live feed. |
| `TICKER_CHANGE_RISK` | Old tickers may silently return empty or wrong data. |
| `CORPORATE_ACTION_IN_WINDOW` | Splits/dividends in the fetch window inflate apparent returns. |
| `SURVIVORSHIP_FORWARD_ONLY` | Universe is fixed at campaign init. A future delisting becomes MISSING in the live feed (correctly recorded). |
| `PROVIDER_REVISION_POSSIBLE` | Yahoo may silently revise prior-period data at any time. |
| `CROSS_PROVIDER_DISCREPANCY` | Yahoo prices may differ from Bloomberg/Refinitiv by ±0.5% due to different adjustment methodologies. |

**If any symbol is MISSING:** note it in `missing_securities` of the cycle record
(the campaign does this automatically). The data health gate
(`min_universe_coverage=0.8`) will reject the cycle if fewer than 8/10 symbols
have data.

---

## Step 3 — Alpaca PAPER Environment Verification

```bash
export ALPACA_PAPER_API_KEY=<your paper key>
export ALPACA_PAPER_API_SECRET=<your paper secret>

uv run python scripts/forward_run/run_forward.py alpaca_paper_status
```

**Checks:**
- [ ] Account status: `ACTIVE`
- [ ] Account type: `margin` or `cash` (paper)
- [ ] `live_trading_blocked: True` confirmed in output
- [ ] `environment: PAPER` confirmed
- [ ] No `LiveTradingBlockedError`

**If INACTIVE or error:** Check Alpaca paper dashboard at
`https://app.alpaca.markets/paper-trading`. Verify credentials and account status
before proceeding.

---

## Step 4 — Forward Cycle Execution (M25/M26)

```bash
uv run python scripts/forward_run/run_forward.py forward_run \
    --as-of YYYY-MM-DD \
    --data-dir data/forward_campaign/FORWARD_CAMPAIGN_ew-momentum-exp_v1.0.0_20260813
```

**Checks:**
- [ ] `status: SUCCESS` (or `ALREADY_SEALED` if run twice — idempotent)
- [ ] `cycle_id: ew-momentum-exp__YYYY_MM`
- [ ] `risk_ok: True`
- [ ] `ending_nav` reasonable (no 100× jump)
- [ ] `sealed_at` populated
- [ ] Record saved: `data/forward_campaign/.../cycles/ew-momentum-exp__YYYY_MM.json`

**If `status: FAILED`:**
- Check `error_message` in the cycle JSON
- Check data health gate (coverage below 80%?)
- Delete the FAILED record if appropriate and re-run after fixing the issue
  (sealed FAILED records are idempotent — re-running returns ALREADY_SEALED)

---

## Step 5 — Alpaca Paper Order Submission & Fill Handling (M29)

```bash
uv run python scripts/forward_run/run_forward.py forward_alpaca_cycle \
    --as-of YYYY-MM-DD \
    --data-dir data/forward_campaign/FORWARD_CAMPAIGN_ew-momentum-exp_v1.0.0_20260813
```

**Checks:**
- [ ] `orders_submitted` > 0 (unless weights unchanged — zero-trade cycle)
- [ ] `fill_rate` = 1.0 or near 1.0 (Alpaca paper fills market orders immediately)
- [ ] `reconciliation_status: PASS`
- [ ] `positions_reconciled: True`
- [ ] `nav_reconciled: True`
- [ ] `nav_delta_bps` < 100 bps (within expected slippage range)
- [ ] `status: SUCCESS`
- [ ] Record saved: `data/forward_campaign/.../alpaca_executions/ew-momentum-exp__YYYY_MM.json`

**If any order is rejected:**
- Check `rejection_reason` in the execution record
- Verify Alpaca paper account has sufficient buying power
- Alpaca paper accounts reset periodically; verify balance at dashboard

**If `fill_rate` < 1.0:**
- Check for partial fills in `orders[*].order_status`
- Partial fills are recorded accurately with `UNAVAILABLE` slippage where computable

**Idempotency:** Running `forward_alpaca_cycle` twice for the same `as_of` month
returns the existing sealed record — no duplicate orders, fills, or NAV changes.

---

## Step 6 — Execution Quality Report (M29)

```bash
uv run python scripts/forward_run/run_forward.py forward_execution_quality \
    --data-dir data/forward_campaign/FORWARD_CAMPAIGN_ew-momentum-exp_v1.0.0_20260813
```

**Checks:**
- [ ] `alpaca_execution_cycles` matches expected count
- [ ] `overall_fill_rate` ≥ 0.9
- [ ] `avg_slippage_bps` within expected range (< 20 bps for market orders)
- [ ] `reconciliation_pass_rate` = 1.0
- [ ] Forward vs. backtest comparison printed (INSUFFICIENT_SAMPLE until n=12)

**Note on statistical validity:** The forward vs. backtest comparison requires
n ≥ 12 forward cycles for any statistical inference. Until then, all forward
metrics display as INSUFFICIENT_SAMPLE. This is correct behaviour — no
premature inference.

---

## Step 7 — Benchmark Comparison (M27)

```bash
uv run python scripts/forward_run/run_forward.py forward_benchmark \
    --as-of YYYY-MM-DD \
    --data-dir data/forward_campaign/FORWARD_CAMPAIGN_ew-momentum-exp_v1.0.0_20260813
```

**Checks:**
- [ ] SPY benchmark cycle recorded for the month
- [ ] `benchmark_nav` updated
- [ ] No crash or fetch error (SPY is very unlikely to be missing from Yahoo)

---

## Step 8 — Evidence Report (M27)

```bash
uv run python scripts/forward_run/run_forward.py forward_evidence_report \
    --data-dir data/forward_campaign/FORWARD_CAMPAIGN_ew-momentum-exp_v1.0.0_20260813
```

**Checks:**
- [ ] `sealed_cycles` count incremented
- [ ] `execution_quality_label: HAS_ALPACA_EXECUTION` (after first M29 cycle)
- [ ] No `STRATEGY_MODIFIED: YES`
- [ ] `LIVE_EXECUTION: NO`
- [ ] `REAL_CAPITAL: NO`

---

## Step 9 — Archival

After all checks pass:

1. **Commit cycle records** (do NOT commit credentials):
   ```bash
   git add data/forward_campaign/FORWARD_CAMPAIGN_ew-momentum-exp_v1.0.0_20260813/
   git commit -m "data(forward): seal YYYY-MM forward cycle — strategy fingerprint unchanged"
   ```

2. **Note the cycle outcome** in your research log or issue tracker:
   - Cycle ID
   - NAV before / after
   - Fill rate
   - Reconciliation status
   - Any anomalies

---

## Step 10 — Failure Handling

| Symptom | Action |
|---|---|
| `strategy_fingerprint` mismatch | STOP — do not run. Investigate strategy change. |
| Data health gate FAILED (coverage < 80%) | Investigate missing symbols. Check for delistings or ticker changes. Do not force through. |
| Alpaca account INACTIVE | Check paper dashboard. Verify credentials. |
| `fill_rate = 0` (all orders rejected) | Check buying power, position limits, Alpaca paper account state. |
| `reconciliation_status: FAIL` | Record it accurately. Do not re-run to hide it. Document in research log. |
| `status: FAILED` on ForwardCycleRecord | The record is sealed as FAILED (correct). Investigate error_message. Fix root cause before next cycle. |
| Crash mid-write (leftover .tmp file) | Safe to retry — `_persist()` checks for sealed file and `.tmp` is not a sealed record. |
| Cannot import credentials | Do not hardcode. Pass via environment variables only. |

---

## Quick-Reference: Governance Tags

Every sealed record in `cycles/*.json` and `alpaca_executions/*.json` must show:

```
mode            : PAPER_FORWARD
broker          : ALPACA  (or SIMULATED for pre-M29 records)
environment     : PAPER
live_execution  : NO
real_capital    : NO
strategy_modified: (implicit in fingerprint match)
```

If any of these are wrong, stop and investigate before proceeding.

---

## Credentials Policy

- Use `ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_API_SECRET` only (never generic `ALPACA_API_KEY`)
- Never commit credentials to git
- Never print or log credential values
- Rotate keys after any unintended exposure
- Keys never appear in `AlpacaOrderExecution`, `AlpacaCycleExecutionRecord`, or any sealed record

---

## September 2026 Cycle Readiness

| Item | Status |
|---|---|
| Today's date | 2026-08-14 |
| September gate | CLOSED — open after 2026-09-01 |
| Campaign directory | Initialized |
| Strategy fingerprint | `b69961b65bab226a500d71f45709945b` |
| AlpacaCycleExecutor | Wired and tested (60/60 offline tests) |
| Dry-run tests | 33/33 passed |
| Pre-cycle check CLI | `pre_cycle_check` subcommand available |
| September execution records | 0 (correctly zero) |
| First cycle day | ~2026-09-02 (first trading day of September 2026) |

**Action required on cycle day:**
1. Run `pre_cycle_check --as-of 2026-09-01`
2. Run `forward_alpaca_cycle --as-of 2026-09-01`
3. Follow Steps 5–9 above
4. Record outcome

---

*Generated 2026-08-14 | M30 pre-cycle readiness | Co-Authored-By: Claude Opus 4.8*
