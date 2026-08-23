# Mentis Rex Capital — v3.0 Programme Build Report

**Date:** 2026-08-22 · **Branch:** `claude/ponytail-ultra-49cf7e` · **Package:** `mentisrex.programme`

The US Equity Systematic Programme v3.0 specification is now the executable core
of this repository. This report states what was built, how the work was run,
what broke along the way, what was found, and what is deliberately not done.

**No backtest result is reported here.** The harness was executed as an
engineering check — does it run to completion, do all ten sleeves activate, is
the structure right — and the performance numbers it produced were deliberately
not read, recorded, or acted on. That is your run to make.

---

## 1. Headline

| | |
|---|---|
| Modules built | 13, plus package init |
| Production lines | 4,504 |
| Test lines | 621 |
| New tests | 48, all passing, 0.64s, fully offline |
| Full suite after the change | 638 passed, 4 skipped |
| Commits | 9 |
| Real defects found and fixed | 5 |
| Universe materialised | 410 US names + SPY |
| Daily sequence | runs end to end on real data |

The nine-step daily sequence from specification Table 27 executes against the
live store, from panel build through quality gate, allocation, risk gate,
borrow filter, order construction and state persistence. At the `deploy` rung it
produces a 1.000× gross book, long 0.900 / short 0.100, 250 orders with 161
suppressed under the $250 floor.

---

## 2. What was built

`src/mentisrex/programme/` — one module per row of specification Table 26, so the
document and the code can be read side by side.

| Module | Lines | Responsibility | The guarantee it carries |
|---|---:|---|---|
| `config.py` | 323 | every tunable, versioned | SHA-256 fingerprint logged on every run |
| `rates.py` | 193 | policy-rate path | embedded schedule offline, FRED adapter that cannot raise |
| `data.py` | 790 | sources, panel, eligibility, quality gates | four fatal conditions halt trading before a signal is computed |
| `signals.py` | 466 | the ten signal functions | point-in-time by contract, asserted by truncation |
| `sleeves.py` | 217 | signals → weights, holding periods | turnover measured against the drifted book |
| `allocator.py` | 335 | ten sleeves → one book, cap, financing | realised gross never exceeds the cap |
| `risk.py` | 453 | thirteen breakers, three tiers | evaluated before orders are built, so a halt produces none |
| `execution.py` | 390 | orders, broker boundary, borrow filter | neutrality preserved over gross when constraints conflict |
| `state.py` | 369 | drawdown peak, ramp, sleeve health, audit | atomic writes; path-dependent controls survive a restart |
| `reconcile.py` | 212 | target versus actual, fill slippage | drift beyond 25 bp of NAV per name is flagged |
| `monitor.py` | 260 | live-versus-backtest divergence | volatility, turnover, gross, beta — deliberately not return |
| `backtest.py` | 595 | research harness | calls the same allocator and cost model as the live path |
| `cli.py` | 576 | daily runner, status, restart, backtest | fixed order of operations; risk gate precedes orders |

### The ten sleeves

Four directional sleeves trade the benchmark; six cross-sectional sleeves trade
the single-name universe dollar-neutral.

| | Sleeve | Type | Hold | Source |
|---|---|---|---|---|
| S1 | multi-horizon time-series trend | directional | 1d | Moskowitz, Ooi & Pedersen (2012) |
| S2 | volatility-managed market exposure | directional | 1d | Moreira & Muir (2017) |
| S3 | cross-sectional breadth timing | directional | 1d | — |
| S4 | volatility term-structure panic reversal | directional | 1d | Nagel (2012) |
| S5 | cross-sectional 12–1 momentum | neutral | 10d | Jegadeesh & Titman (1993) |
| S6 | residual momentum | neutral | 10d | Blitz, Huij & Martens (2011) |
| S7 | information-discreteness momentum | neutral | 10d | Da, Gurun & Warachka (2014) |
| S8 | Amihud illiquidity premium | neutral | 63d | Amihud (2002) |
| S9 | relative-volume attention | neutral | 21d | — |
| S10 | conditional short-horizon reversal | neutral | 21d | Nagel (2012); Novy-Marx & Velikov (2023) |

Architecture, implemented literally from specification section 4.2:

```
CORE      = mean(S1..S4)                        × k_core
SATELLITE = mean(vol-targeted S5..S10)          × k_satellite
RAW       = CORE + SATELLITE                    one combined weight vector
f         = min(1, cap / Σ|RAW|)                cap applied to the COMBINED book
TARGET    = clip(RAW·f, ±20% per name, ±300% on the index)
```

Both accounting corrections the specification calls its most valuable findings
are in the code and asserted by tests: the gross cap is charged against the
combined book rather than the sum of standalone sleeve exposures, and the
single-name cap does not apply to the index instrument.

Financing, from specification section 2.3, verified to 1e-12 against a hand
recomputation:

```
daily = [ max(L−1,0)·(r + margin_spread) + S·borrow_fee − S·max(r − rebate_spread, 0) ] / 252
```

This is the single largest gap the earlier audit identified in the existing
platform, which modelled no cost of carry at all.

---

## 3. How to run it

```bash
uv run --extra dev python -m mentisrex.programme.cli --help
```

The database lives in the main working tree, not in this worktree — `data/` is
gitignored — so pass `--db` or set `DUCKDB_PATH`:

```bash
export MRX_DB=/Users/idhantdoneria/mentisrex-capital/data/analytics.duckdb
```

Regenerate the universe (already committed at `config/universe_us.txt`):

```bash
uv run --extra dev python -m mentisrex.programme.cli universe --db "$MRX_DB"
```

Run the daily sequence without touching a broker:

```bash
uv run --extra dev python -m mentisrex.programme.cli run --mode dryrun --nav 1000000 --rung deploy --db "$MRX_DB"
```

The invariant suite — all of it must pass before any deployment:

```bash
uv run --extra dev pytest tests/programme/ -v
```

When you backtest, **start the panel at least three years before the window you
care about.** Breadth timing needs 704 rows before it produces anything and
residual momentum needs 483; on a shorter panel they sit dormant and drag the
equal-weighted group mean toward zero, which reads as a weak result rather than
a missing one. The harness now warns by name when this happens.

```bash
uv run --extra dev python -m mentisrex.programme.cli backtest --rung recommended --start 2017-01-01 --db "$MRX_DB"
```

---

## 4. How the work was managed

Opus read the specification end to end, audited the repository through three
parallel read-only reconnaissance agents, wrote a binding interface contract,
then dispatched and verified build agents. Sonnet wrote every module with real
logic. Haiku wrote `state.py`, which is mechanical and stdlib-only.

The single most useful decision was writing the **interface contract before
launching any agent**: every dataclass field, every function signature, the
index conventions, and — critically — the rule that the execution lag may be
applied in exactly one place. Nine agents writing interdependent modules in
parallel will otherwise produce nine slightly different opinions about what a
weight frame is. Agents were told to implement it verbatim and to record
disagreements as `# CONTRACT-NOTE:` comments rather than silently improving it.
That is how the turnover contradiction in section 5 below got caught instead of
being quietly resolved two different ways in two different modules.

No agent was allowed to commit. Parallel agents sharing one git index contend on
the lock, and a half-written file in a commit is worse than an uncommitted one.
The main thread re-verified each module independently — running the checks
itself rather than trusting the agent's report — and committed.

**A deviation from your instruction, stated plainly.** You asked that the grunt
work go to Haiku and Sonnet agents with Opus only thinking and managing. That
held for the first two thirds. Then the account hit its weekly limit and
subagents stopped being available entirely, mid-flight, taking five agents down
with them. The remaining work — the `data.py` fixes, `backtest.py`, `cli.py` and
the whole test suite — was written directly by the main thread, because the
alternative was stopping with the platform half-built the night before you
intend to backtest. Roughly 2,000 of the 4,504 production lines were written
that way.

---

## 5. Bottlenecks, and how each was resolved

**1. There was no existing strategy to make this the core of.** Every research
campaign in the repository (M1–M14, pairs) ended REJECT, ARCHIVE or DEFER.
Resolved by treating v3.0 as a new strategy core and reusing the platform
underneath it — data, config, logging, broker — rather than the research
scaffolding on top of it.

**2. The existing backtester is the wrong shape.** `mentisrex.backtesting` is an
event-driven, per-order, next-bar-open engine with an event queue. This
programme is a 600-name panel rebalanced daily and priced market-on-close, whose
cost model is an identity on turnover. Forcing one into the other would have
produced something slow and wrong. Resolved by building a vectorised layer
alongside it and documenting `mentisrex.backtesting` as explicitly not for this
path.

**3. Over half the database is unusable.** The `alpaca_iex` source — 6,162
symbols and 7.38M of 14.9M rows — is keyed by SEC CIK identifiers
(`CIK0000001750`), not tickers. No CIK-to-ticker map exists anywhere in the
repository. Those rows were silently entering the universe. Resolved by one
shared SQL predicate excluding them along with India names, so the fetch query
and the inventory query cannot drift apart.

**4. There is no index instrument in the store.** No SPY, IVV, VOO, QQQ, DIA,
IWM or `^GSPC` under any source. Four of the ten sleeves trade nothing else.
Resolved with `CompositeSource`: universe from DuckDB, fall through to Yahoo for
what is missing, cache to parquet so the second run is offline. A missing
benchmark raises rather than substituting a proxy.

**5. The contract contradicted itself on turnover** — one sentence said divide
by two, a later one said not to. The sleeves agent flagged it rather than
picking one. Resolved in favour of one-way notional, the only reading consistent
with the cost identity holding to 1e-12.

**6. Synthetic turnover came out roughly three times the specification's
figure** for the ten-day sleeves. Diagnosed rather than tuned: an i.i.d. signal
redrawn daily shares no names between consecutive rebalances, whereas real
momentum scores are strongly autocorrelated. Re-running with an AR(1) signal
brought it into range. The construction was left alone.

**7. pandas 3.0.5, not 2.x.** Copy-on-write is the default so chained assignment
silently no-ops; `applymap` and `fillna(method=...)` are gone. Every agent brief
carried the warning up front — cheap to say, expensive to debug afterwards.
`pandas`, `numpy`, `scipy` and `pyarrow` are now declared dependencies; they had
been arriving transitively through yfinance and duckdb.

**8. The session limit hit mid-build, twice.** The first reset cost about
ninety minutes and five agents. The second was the weekly cap. The cron job you
asked for fired at 00:50 exactly as designed and resumed the process; the
second is armed for 12:50. Work committed after each module rather than batched
meant nothing was lost either time.

---

## 6. Defects found and fixed

These are real bugs caught by exercising the code, not hypotheticals.

**The quality gate evaluated the wrong date.** It measured panel content
against wall-clock today rather than against the panel's most recent bar. A
perfectly healthy 411-column panel reported 100% of symbols missing, zero
eligible names, and three spurious fatals. Evaluation date and staleness
as-of are now separate: content is checked on the last bar the panel has,
staleness is measured against now.

**The risk gate was handed a hard-coded zero for the day's return**, which left
`DAILY_LOSS_WARN` and `DAILY_LOSS_HALT` permanently disarmed. Both now see the
book's realised net return.

**`effective_breadth` returned NaN whenever any sleeve was inactive.** A
zero-variance sleeve has an undefined correlation with everything, so it puts a
NaN in every other sleeve's column; filtering columns after correlating rejected
all ten. Zero-variance sleeves are now dropped before the correlation is formed.

**A dormant sleeve failed silently.** On a short panel, breadth timing produced
identically zero weights and simply diluted the core group mean. `run_backtest`
now warns by name, with the warm-up each dormant sleeve needs.

**Three of my own tests were wrong before the code was**, and are worth
recording because two of them are the kind of error that makes a green suite
meaningless. The perfect-foresight test was off by one on the lag and reported
the harness as blind to look-ahead when it was not. The neutrality test demanded
exact dollar-neutrality of a *held* book, which drifts with returns between
rebalances by construction — it now asserts exact neutrality of the weights and
bounded drift of the book.

---

## 7. Findings worth your attention

**The Deflated Sharpe Ratio in specification section 12.4 depends on an unstated
input, and the specification's own numbers are optimistic under the
conventional choice.** Table 22 reports DSR probabilities of 0.982 / 0.942 /
0.900 / 0.828 / 0.743 / 0.663 at 10 / 60 / 200 / 1,000 / 5,000 / 20,000 trials.
Those reproduce exactly — to three decimals, every row — but only when the
dispersion of trial Sharpes is set to 0.229 annualised. The specification never
states that number. Lo's standard error of the observed Sharpe for this sample
is 0.415, roughly twice as large, and under it the picture changes materially:

| Trials | DSR at σ=0.229 (spec) | DSR at Lo's σ=0.415 |
|---:|---:|---:|
| 10 | 0.982 | 0.890 |
| 200 | 0.900 | 0.403 |
| 1,000 | 0.828 | 0.197 |
| 20,000 | 0.663 | 0.036 |

The specification's closing claim that the result "survives a deflated-Sharpe
correction assuming twenty thousand trials" rests entirely on the smaller
dispersion. `deflated_sharpe()` defaults to Lo's standard error and documents
both; pass `sharpe_std=0.229` to reproduce the published table. This is a
disagreement about an unstated assumption, not an arithmetic error, and it is
worth resolving before this number is used to justify anything.

**Effective breadth on our data is 4.27, against the 4.05 the specification
reports on its own.** Independent corroboration of its central structural
claim: this is roughly four independent bets wearing ten labels, and that —
not signal quality — is what caps the achievable Sharpe.

**Our universe is 410 names against the specification's 657** (median 593
eligible). The specification's own universe-shrinkage stress says a smaller
universe *raises* return and *worsens* drawdown, because the book concentrates.
Expect that direction in your results and do not read the higher return as an
improvement.

---

## 8. Known limitations and skipped items

Recorded per the project's hard rule: what was skipped, why it is impossible
right now, and what would unblock it.

**Point-in-time universe membership and delisting returns.**
*Impossible now:* no vendor feed exists in this repository. The store is
survivor-constituted; the `delistings.duckdb` file on disk (954 rows) has no
reader and no schema link to the price table. `PointInTimeSource` is a stub that
raises and names the remedy rather than faking it.
*Unblocked by:* a Norgate Premium Data, Sharadar via Nasdaq Data Link, or CRSP
subscription — roughly $500/year. The specification calls this the highest-value
expenditure available to the programme, and the earlier audit reached the same
conclusion independently. It should be bought before capital is committed.

**Live borrow availability.** `AlpacaProgrammeBroker.shortable()` raises
`NotImplementedError`.
*Impossible now:* the existing `mentisrex.paper.alpaca_broker.AlpacaBroker` has
no asset-shortability lookup, and inventing one without a live account to test
against would produce untested code on a path where being wrong means running an
unintended directional bet.
*Unblocked by:* wiring Alpaca's `/v2/assets` endpoint and testing against a real
paper account. Until then `cli run` warns loudly and assumes every short is
borrowable, which is optimistic — the specification's stress table shows blocked
shorts *raise* return and *worsen* drawdown, so this assumption flatters
drawdown rather than return.

**Fill history from the broker.** `AlpacaProgrammeBroker.fills()` raises for the
same reason. Consequence: `realised_cost_bps` cannot be measured live yet, and
`COST_DIVERGENCE` cannot fire against real fills. The specification is emphatic
that costs must be measured rather than inferred, so this needs closing before
the first paper quarter is taken seriously.

**Corporate-action adjustment is unverified.** Every row in the store has
`adjustment_factor = 1.0` and `quality_score IS NULL`. Upstream fetches
requested adjusted prices, so closes are *believed* adjusted, but nothing proves
it. Stated in the `data.py` docstring rather than assumed away.
*Unblocked by:* the same vendor feed, or a spot reconciliation of a few known
splits against an independent source.

**US price data is 24 days stale.** The store's last US bar is 2026-07-29. A
`paper` or `live` run will correctly refuse to trade on it. Re-ingest before
running anything but a dryrun.

**No trading-calendar library.** The programme's calendar is the set of dates
the benchmark has a bar. This is a deliberate simplification, not an oversight,
and it is documented where it matters: staleness against a date the panel does
not contain is measured in calendar days rather than exchange sessions.

**`--mode paper` and `--mode live` have never been executed.** Wired, never
run. No order has been placed by this code.

---

## 9. What I would do next, in order

1. Buy the point-in-time data. Everything else on this list is smaller.
2. Re-ingest US prices so the panel reaches today.
3. Run your backtest from 2017-01-01 at the `deploy` rung first, not
   `recommended` — compare the sleeve table against specification Table 3 and
   the correlation matrix against Table 5. If a sleeve you cannot reproduce
   within about 0.1 of Sharpe appears, the discrepancy is information.
4. Resolve the deflated-Sharpe dispersion question in section 7 before quoting
   any significance claim.
5. Close the broker gaps — shortability and fills — before the first paper
   quarter, because without them you cannot measure your real cost rate, and
   the specification is right that cost is the binding operational risk.
