# MENTISREX M28 — Alpaca Paper-Broker Integration & Live-Execution Lock

**Status:** COMPLETE  
**Date:** 2026-08-14  
**Strategy fingerprint:** `b69961b65bab226a500d71f45709945b` (unchanged)

---

## Objective

Integrate Alpaca's PAPER trading API as a drop-in broker for the Mentisrex execution stack while making live/real-money execution structurally impossible — not merely configurable-off, but unroutable.

---

## Architecture

Two execution stacks exist in this repository:

| Stack | Class | Tick model | Broker interface |
|-------|-------|------------|-----------------|
| `paper/` | `TradingEngine` | Tick-by-tick | `PaperBroker` protocol |
| `research/paper_trading/` | `PaperTradingLoop` | Snapshot/day | `Broker` ABC |

`AlpacaPaperBroker` (M28) targets the `paper/TradingEngine` stack. The `research/` stack uses `MockBroker`/`SimulatedBroker` internally (M25 `ForwardCampaign` path); wiring Alpaca there requires deeper changes to `PaperTradingLoop` and is deferred.

---

## Paper-Only Enforcement — Safety Model

The safety model is **fail-closed**: every mechanism defaults to blocking. Live execution is not an option that can be enabled; it is an outcome that has been made structurally unreachable.

### 1. Hardcoded paper endpoint

```python
class AlpacaPaperBroker:
    _BASE_URL: str = "https://paper-api.alpaca.markets"
```

No `base_url` parameter exists. There is no argument that routes to a live endpoint.

### 2. Live endpoint blocklist

```python
_LIVE_ENDPOINTS: frozenset[str] = frozenset([
    "https://api.alpaca.markets",
    "https://api.alpaca.markets/",
    "http://api.alpaca.markets",
])
```

`AlpacaBroker` (deprecated alias) checks this blocklist and raises `LiveTradingBlockedError` if any live URL is passed — even if someone tries to use the alias to route to a live endpoint.

### 3. Paper-specific credentials only

Only `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_API_SECRET` are accepted. The generic `ALPACA_API_KEY` is explicitly rejected with an error message explaining that it may be a live-account credential:

```
PaperAccountVerificationError: Missing ALPACA_PAPER_API_KEY and/or
ALPACA_PAPER_API_SECRET. Do NOT use ALPACA_API_KEY — it may be a live-account
credential. Set ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET from your
Alpaca PAPER account dashboard.
```

### 4. Account identity verification at startup

`AlpacaPaperBroker.__init__` calls `_verify_paper_account()` before any order can be placed. This performs `GET /v2/account` against `paper-api.alpaca.markets` and checks:
- HTTP 200 (live credentials fail against the paper endpoint)
- `status` in `{"ACTIVE", "ACCOUNT_UPDATED", "APPROVED"}`

Any failure raises `PaperAccountVerificationError`. No orders are possible after construction failure.

### 5. `MENTISREX_LIVE_TRADING` kill switch

Setting `MENTISREX_LIVE_TRADING=true` **blocks** (not enables) execution. Checked:
- At `AlpacaPaperBroker.__init__`
- At every `submit_order()` call
- At every `get_account()` call

Raises `LiveTradingBlockedError` immediately.

### 6. `BrokerMode` enum — no live option

```python
class BrokerMode(str, Enum):
    MOCK = "MOCK"
    SIMULATED = "SIMULATED"
    ALPACA_PAPER = "ALPACA_PAPER"
    # ALPACA_LIVE intentionally absent
```

There is no enum value that a strategy could use to request live execution.

---

## Credential Setup

**Do not store credentials in source code, config files, or commit history.**

1. Log in to [Alpaca Markets](https://app.alpaca.markets)
2. Switch to **Paper Trading** (toggle in top bar)
3. Copy API Key ID and Secret Key
4. Export in your shell or CI secrets:
   ```bash
   export ALPACA_PAPER_API_KEY="your-paper-key-id"
   export ALPACA_PAPER_API_SECRET="your-paper-secret-key"
   ```

`AlpacaPaperBroker` reads these at construction time. They are never stored in order records, exception messages, or log output.

---

## Order Lifecycle

```
submit_order(symbol, side, qty, ...)
  ├── _assert_no_live_trading()          # kill switch check
  ├── _validate_order(...)               # pre-network validation
  ├── risk_approved check                # must be True
  ├── _make_client_order_id(...)         # deterministic idempotency key
  ├── _find_existing_by_client_id(...)   # cross-restart recovery
  │     └── if found: return existing record (no duplicate)
  ├── POST /v2/orders                    # submit to Alpaca paper
  │     └── TimeoutException → RuntimeError (check client_order_id before retry)
  └── return AlpacaOrderRecord(...)      # immutable audit trail
```

### Pre-network validation

Rejected before any network call:
- Empty or whitespace symbol
- `side` not in `{"buy", "sell"}`
- `quantity` ≤ 0
- `order_type` not in `{"market", "limit"}`
- Limit order without `limit_price`
- `limit_price` ≤ 0
- Notional (`qty × limit_price`) exceeds `max_order_notional` (default $10,000)

---

## Idempotency

Each logical order gets a deterministic `client_order_id`:

```python
raw = f"{strategy_id}:{symbol}:{side}:{cycle_id}:{seq}"
h = hashlib.blake2b(raw.encode(), digest_size=8).hexdigest()
client_order_id = f"mr-{h}"   # max 48 chars (Alpaca limit)
```

On `submit_order`, `_find_existing_by_client_id()` queries Alpaca for an order with this `client_order_id`. If found (e.g., after process restart), the existing record is returned without re-submitting. This prevents duplicate orders across restarts.

---

## Reconciliation

### Position reconciliation

```python
result = broker.reconcile_positions({"SPY": Decimal("10"), "AAPL": Decimal("5")})
result.ok            # True if all match
result.mismatches    # list of (symbol, expected, actual)
result.unexpected    # positions Alpaca has that we don't expect
result.missing       # positions we expect Alpaca doesn't have
```

### NAV reconciliation

```python
result = broker.reconcile_nav(internal_nav_float)
result.ok         # True if |delta_bps| < 100
result.delta      # absolute dollar difference
result.delta_bps  # basis points
result.alpaca_equity  # Alpaca-reported equity
```

Tolerance: 100 bps. Differences below 100 bps are considered reconciled (rounding, unrealized P&L timing).

---

## CLI Usage

```bash
# Account status (no order placed)
uv run scripts/forward_run/run_forward.py alpaca_paper_status

# Submit one controlled paper order (smoke test)
uv run scripts/forward_run/run_forward.py alpaca_paper_order \
    --symbol SPY --side buy --quantity 1 --order-type market --cycle-id smoke-test
```

Both commands require `ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_API_SECRET` to be set.

Output from `alpaca_paper_status` includes:
- Connectivity status
- Masked account ID (first 8 chars + `...`)
- Cash, equity, buying power, position count
- `live_execution: NO` and `real_capital: NO` fields

---

## Audit Trail

Every submitted order returns an `AlpacaOrderRecord` (frozen dataclass):

```python
AlpacaOrderRecord(
    mentisrex_order_id="mr-a1b2c3d4e5f6g7h8",
    alpaca_order_id="alpaca-uuid",
    client_order_id="mr-a1b2c3d4e5f6g7h8",
    strategy_id="aurelius-m22",
    strategy_fingerprint="b69961b65bab226a500d71f45709945b",
    symbol="SPY",
    side="buy",
    quantity="1",
    order_type="market",
    time_in_force="day",
    status="accepted",
    broker="ALPACA",
    environment="PAPER",
    submitted_at="2026-08-14T12:00:00Z",
    live_execution="NO",
    real_capital="NO",
    live_endpoint_supported="NO",
)
```

Credentials are **never** stored in `AlpacaOrderRecord`. The record is safe to log, write to disk, or include in reports.

---

## Test Suite

`tests/paper/test_m28_alpaca_paper_broker.py` — 80 offline tests, 20 categories:

| ID | Category | What it verifies |
|----|----------|-----------------|
| T01 | `TestLiveEndpointRejected` | No `base_url` param; class constant is paper URL |
| T02 | `TestLiveLookingConfigRejected` | Deprecated alias rejects live/custom URLs |
| T03 | `TestAccountVerificationRejected` | HTTP 401, wrong status, connection error all raise |
| T04 | `TestLiveExecutionModeRejected` | `MENTISREX_LIVE_TRADING=true` blocks all operations |
| T05 | `TestMissingCredentials` | Various bad credential combos raise with correct message |
| T06 | `TestOrderValidation` | All pre-network validation paths |
| T07 | `TestRiskGate` | `risk_approved=False` blocks before any network call |
| T08 | `TestIdempotency` | Deterministic client_order_id, no duplicate in-process |
| T09 | `TestRestartRecovery` | `_find_existing_by_client_id` recovery path |
| T10 | `TestLiveBrokerInstantiation` | No `AlpacaLiveBroker` class exists |
| T11 | `TestBrokerMode` | All valid modes present, no LIVE mode |
| T12 | `TestAuditTrailNoCredentials` | Credentials not in record; all required fields present |
| T13 | `TestClientOrderIdDeterminism` | Same inputs → same ID; different inputs → different ID |
| T14 | `TestPositionReconciliation` | Match/mismatch/unexpected/missing position cases |
| T15 | `TestNavReconciliation` | Within/outside tolerance; delta calculation |
| T16 | `TestFillRetrieval` | Filled returns fill; unfilled returns empty |
| T17 | `TestAccountMasking` | Raw account ID not in status report |
| T18 | `TestNetworkFailureHandling` | Timeout with idempotency guidance; HTTP errors |
| T19 | `TestResearchIsolation` | No train/fit/optimize/backtest methods |
| T20 | `TestAlpacaBrokerAlias` | Deprecation warning; inherits paper safety |

Run offline suite:
```bash
uv run pytest tests/paper/test_m28_alpaca_paper_broker.py -m "not real_alpaca" -v
```

Run real-network tests (requires credentials):
```bash
uv run pytest tests/paper/test_m28_alpaca_paper_broker.py -m real_alpaca -v
```

---

## Real Paper Smoke Test

**Status: NOT VERIFIED**

`ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_API_SECRET` were not set in the environment at M28 implementation time (2026-08-14). The real-network test class `TestRealAlpacaPaperConnectivity` and CLI command `alpaca_paper_status` are implemented and tested against the mock layer; they require live credentials to execute end-to-end.

**To verify:**
1. Set `ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_API_SECRET`
2. Run: `uv run scripts/forward_run/run_forward.py alpaca_paper_status`
3. Run: `uv run pytest tests/paper/test_m28_alpaca_paper_broker.py -m real_alpaca -v`
4. Update this section with results.

---

## Security Model

- Credentials read from environment; never hardcoded, never committed
- Credentials never stored in `AlpacaOrderRecord`, exceptions, or log output
- Account ID masked in all status reports (first 8 chars + `...`)
- Paper endpoint URL hardcoded as class constant — no injection path
- `_http` injection for testing uses mock; skips `_verify_paper_account()` — cannot be triggered from production code paths
- `MENTISREX_LIVE_TRADING` kill switch is defense-in-depth (primary defense is structural unroutable live endpoint)

---

## Known Limitations / Skipped

1. **`research/PaperTradingLoop` integration** (skipped): `AlpacaPaperBroker` works with `paper/TradingEngine` but not `research/paper_trading/PaperTradingLoop` (M25 `ForwardCampaign` path). The `Broker` ABC there requires `execute_order(TradeRequest)` returning `TradeExecution`. Blocked by: `PaperTradingLoop` internal architecture. Unblocked by: adding an adapter that wraps `AlpacaPaperBroker` with the `Broker` ABC interface.

2. **Real paper smoke test** (NOT VERIFIED): Credentials unavailable at implementation time. Unblocked by: setting `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_API_SECRET` and running `alpaca_paper_status`.

3. **`TradingEngine` equity curve tracking** (partial): `TradingEngine` accesses `broker.state.total_value` for equity curve. `AlpacaPaperBroker` exposes `get_account()` instead of a `PortfolioState` object. Full integration requires a lightweight `state` proxy that calls `get_account()` on demand. Unblocked by: adding a proxy class; deferred since `TradingEngine` + Alpaca integration is post-M28 scope.

---

## M28 Final Certification Report

| Item | Status |
|------|--------|
| `AlpacaPaperBroker` implemented | COMPLETE |
| Paper endpoint hardcoded, no `base_url` param | COMPLETE |
| `ALPACA_PAPER_API_KEY` / `_SECRET` only | COMPLETE |
| Account verified at construction | COMPLETE |
| `MENTISREX_LIVE_TRADING=true` blocks (not enables) | COMPLETE |
| Order validation before any network call | COMPLETE |
| Idempotent `client_order_id` (blake2b) | COMPLETE |
| Cross-restart recovery via `_find_existing_by_client_id` | COMPLETE |
| Fill reconciliation | COMPLETE |
| Position reconciliation | COMPLETE |
| NAV reconciliation (100 bps tolerance) | COMPLETE |
| `BrokerMode` enum: `MOCK\|SIMULATED\|ALPACA_PAPER`, no `ALPACA_LIVE` | COMPLETE |
| CLI: `alpaca_paper_status` | COMPLETE |
| CLI: `alpaca_paper_order` | COMPLETE |
| `AlpacaBroker` deprecated alias with live endpoint block | COMPLETE |
| Offline test suite (80 tests, 20 categories) | COMPLETE — 80/80 PASSED |
| Full regression suite | COMPLETE — 2695 passed, 0 failures |
| `real_alpaca` pytest marker registered | COMPLETE |
| Security audit: no credentials in diff | COMPLETE — CLEAN |
| Documentation | COMPLETE (this file) |
| Real Alpaca paper smoke test | NOT VERIFIED (credentials unavailable) |
| Strategy fingerprint `b69961b65bab226a500d71f45709945b` unchanged | CONFIRMED |
| Live execution | NO |
| Real capital at risk | NO |
