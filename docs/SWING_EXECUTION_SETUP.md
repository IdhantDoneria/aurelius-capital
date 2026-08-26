# Running Nightfall through paper trading

**Document version:** 1.0
**Date:** 2026-08-27
**Package:** `src/mentisrex/swing/execution.py`
**Prerequisite:** [`SWING_STRATEGY_SELECTED.md`](SWING_STRATEGY_SELECTED.md) —
read section 1 first. This wiring exists to run the cost-measurement pilot
that document recommends, not to deploy at target size.

---

## 1. The API you need

**Alpaca Markets — Paper Trading API. Free.**

This codebase already depends on Alpaca for market data (`scripts/intraday_fetch_*.py`)
and already has a hardened paper-trading broker adapter
(`src/mentisrex/paper/alpaca_broker.py`, module M28) that this swing
execution module reuses rather than reimplementing. There is no second
platform to integrate — the same account that fetched the backtest data can
place paper orders.

Why Alpaca and not another broker:

- **Free paper trading, no funding required.** Alpaca issues a simulated
  \$100k (configurable) paper account tied to any account, with no deposit,
  no minimum balance, and no fee.
- **Already in the codebase's execution architecture.** `programme/execution.py`
  (the daily-bar sleeve's live path) uses the exact same broker class, so
  this is the second, not the first, consumer of that adapter — reuse, not a
  new dependency.
- **The order type Nightfall needs is supported.** Both sleeves wired
  through `cli.py targets` enter at the closing auction; Alpaca's
  `time_in_force=cls` order type is a genuine market-on-close order, not a
  same-day market order relabelled.

### Getting the free key

1. Create an account at **alpaca.markets** (no funding needed for paper
   trading).
2. In the dashboard, switch to **Paper Trading** (not Live).
3. Generate a paper API key pair — this gives you an **API Key ID** and an
   **API Secret Key**. These are the paper-account credentials; they cannot
   place live orders or move real money, by construction of Alpaca's own
   paper endpoint.

---

## 2. Where to put the key

This repo reads Alpaca credentials from environment variables, loaded from a
git-ignored `.env.development` file at the repo root — never from a
committed file. `.env.example` at the repo root is the template; it is
checked in with placeholder values only.

```bash
cp .env.example .env.development
```

Then add these two lines to `.env.development` (create it if the copy above
didn't produce them — `.env.example` currently only lists the generic
`ALPACA_API_KEY` used by the data-fetch scripts, not the paper-trading pair):

```
ALPACA_PAPER_API_KEY=<your paper API Key ID>
ALPACA_PAPER_API_SECRET=<your paper API Secret Key>
```

**Use `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_API_SECRET`, not
`ALPACA_API_KEY` / `ALPACA_API_SECRET`.** The broker this module wraps
(`AlpacaPaperBroker`, M28) deliberately looks for the `_PAPER_` pair first so
a live-account credential pasted into the wrong variable can't accidentally
be used to submit an order — see `src/mentisrex/paper/alpaca_broker.py`'s
module docstring, point 3. If you only have a data key (`ALPACA_API_KEY`)
from setting up the backtests, it is not sufficient for this step — go back
to step 3 above and generate the separate paper-trading pair.

Never commit `.env.development` — it's already covered by `.gitignore`.

---

## 3. Running it

**Step 1 — generate today's target book** (unchanged from the reproduction
steps in `SWING_STRATEGY_SELECTED.md` section 15):

```bash
WT=/Users/idhantdoneria/mentisrex-capital/.claude/worktrees/swing-trading-strategy-d9b2f0
PY=/Users/idhantdoneria/mentisrex-capital/.venv/bin/python
PYTHONPATH="$WT/src" $PY -m mentisrex.swing.cli targets \
  --strategy nightfall --equity 100000 \
  --out /tmp/nightfall_book.csv
```

`--equity 100000` here is the notional the *book* is sized against — keep it
small and bounded, per the selected-strategy document's recommendation. It
does not need to match your Alpaca paper account's starting balance; the
`submit` step below re-sizes against the live account's actual NAV.

**Step 2 — preview the orders (dry run, default)**:

```bash
PYTHONPATH="$WT/src" $PY -m mentisrex.swing.cli submit --book /tmp/nightfall_book.csv
```

This authenticates against Alpaca (so a credential or connectivity problem
surfaces here, not mid-submission), reads current paper positions and NAV,
computes the buy/sell delta, and prints it. **Nothing is sent to Alpaca at
this step.**

**Step 3 — actually submit**, only after reviewing the preview:

```bash
PYTHONPATH="$WT/src" $PY -m mentisrex.swing.cli submit --book /tmp/nightfall_book.csv --confirm
```

This places genuine market-on-close orders (`time_in_force=cls`) in your
Alpaca **paper** account. No real money is at risk — see the safety model in
`src/mentisrex/paper/alpaca_broker.py`'s module docstring: the paper endpoint
is a hardcoded class constant, there is no live endpoint anywhere in the
class, and `MENTISREX_LIVE_TRADING=true` raises rather than enabling
anything.

You would run steps 1–3 once per session, close to 15:45 ET (the decision
time the target book's `reference_price_note` documents), for as long as the
cost-measurement pilot in the selected-strategy document runs.

---

## 4. Known limitations (see CLAUDE.md "nothing gets silently skipped")

- **No automated pre-trade shortability check.** `AlpacaSwingBroker.shortable`
  raises `NotImplementedError`. Nightfall is dollar-neutral long/short; if a
  name in the short leg isn't shortable today, Alpaca rejects that one order
  at submission (visible in `submit`'s printed count of
  `submitted N/M orders`) rather than it being filtered and the book
  re-neutralised beforehand. **Why:** the reused `AlpacaPaperBroker` has no
  asset/shortability lookup anywhere in this codebase to call.
  **Unblocked by:** wiring Alpaca's `GET /v2/assets/{symbol}` (fields
  `shortable`, `easy_to_borrow`), which would also close the identical,
  already-documented gap in `programme/execution.py`'s own broker.
- **No automated fill reconciliation.** `AlpacaSwingBroker.fills` raises
  `NotImplementedError`. After `--confirm`, check fills manually via the
  Alpaca dashboard or `AlpacaPaperBroker.get_order_status`/`get_fills` on an
  individual order id. **Why:** no fills-since-timestamp query exists
  anywhere in `mentisrex.paper`. **Unblocked by:** wiring
  `GET /v2/orders?status=closed&after=<ts>`.
- **No scheduler.** Steps 1–3 are run by hand, or by whatever cron/orchestration
  you already use for the rest of this repo's execution pipeline — this
  module only wires the strategy into the broker, matching the original
  scope ("the user already has an execution pipeline; only the strategy
  itself was needed").
