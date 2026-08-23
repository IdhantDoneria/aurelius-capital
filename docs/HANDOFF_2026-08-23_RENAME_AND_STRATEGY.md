# Handoff — Firm Rename, Strategy Integration, Current Strategy

**Date:** 2026-08-23
**Branch:** `aidp/audit-and-pit-gaps` (fast-forwarded to `main` and pushed — see §4)

Three things were asked for in one pass: rename every "Aurelius" reference to MENTISREX, bring the ten-sleeve strategy you built yesterday into this project and update the strategy docs, and report back on the current strategy. All three below.

---

## 1. Rename — Aurelius → MENTISREX

The `src/` package on this branch was already named `mentisrex` (renamed 2026-08-12/13, before this session). What was still outstanding: 18 doc files still carried `AURELIUS_` filenames from that same architecture track, plus scattered textual mentions.

**Renamed (git mv, history preserved):**

| Old | New |
|---|---|
| `docs/AURELIUS_ARCHITECTURE.md` | `docs/MENTISREX_ARCHITECTURE.md` |
| `docs/AURELIUS_ENGINEERING_PRINCIPLES.md` | `docs/MENTISREX_ENGINEERING_PRINCIPLES.md` |
| `docs/AURELIUS_FORWARD_PAPER_TRADING_RUNBOOK.md` | `docs/MENTISREX_FORWARD_PAPER_TRADING_RUNBOOK.md` |
| `docs/AURELIUS_LEGACY_TRACK_AUDIT.md` | `docs/MENTISREX_LEGACY_TRACK_AUDIT.md` |
| `docs/AURELIUS_M12_PAPER_TRADING.md` … `AURELIUS_M24_FORWARD_VALIDATION.md` (13 files) | `docs/MENTISREX_M12_PAPER_TRADING.md` … `MENTISREX_M24_FORWARD_VALIDATION.md` |
| `docs/AURELIUS_MILESTONE_INDEX.md` | `docs/MENTISREX_MILESTONE_INDEX.md` |
| `docs/AURELIUS_REPOSITORY_CHECKPOINT.md` | `docs/MENTISREX_REPOSITORY_CHECKPOINT.md` |
| `docs/AURELIUS_ROADMAP.md` | `docs/MENTISREX_ROADMAP.md` |

**Text replaced** (`Aurelius`/`AURELIUS`/`aurelius` → `Mentisrex`/`MENTISREX`/`mentisrex`) in: `HANDOFF.md`, `docs/RESEARCH_PROGRAM_AUDIT_2026-08-14.md`, `docs/MENTISREX_M28_ALPACA_PAPER_BROKER.md`, `docs/CODEBASE_AUDIT_2026-08-23.md`, and every file brought in from the other branch (§2).

**Confirmed clean:** `grep -rli aurelius .` (excluding `.git`, `.venv`, other worktrees) returns nothing.

**Left alone, flagged for you:**
- The GitHub remote is still `github.com/IdhantDoneria/aurelius-capital.git`. Renaming a GitHub repo is an account-level action on shared infrastructure — I didn't touch it. Run `gh repo rename mentisrex-capital` yourself if you want the remote to match, then update `git remote set-url origin`.
- Other local worktrees (`ponytail-ultra-49cf7e`, `angry-hamilton-8437d3`, etc.) still have `src/aurelius/` on their own checked-out branches. Those are separate, older snapshots — not touched, not in scope.

---

## 2. Ten-sleeve strategy — where it actually was, and what integrating it found

**You were right that it exists in this project — just not on the branch I was on.** It was built in full on a sibling branch, `claude/ponytail-ultra-49cf7e`, forked from the same point as this branch, as `aurelius.programme` (4,504 production lines, 48 tests, real backtest run against this firm's own `data/analytics.duckdb`). It never made it onto `aidp/audit-and-pit-gaps` or `main`. Separately, a copy of the original spec (`sysq_handoff.md`) and a standalone version of the same package existed at `~/Downloads/prod/sysq` — an earlier, less-developed draft of the same thing. The in-repo version on `ponytail-ultra-49cf7e` is the one that matters: it's newer, backtested on real data, and already has 27 more tests than the standalone draft.

**What I did:**
1. Pulled `src/aurelius/programme/*.py`, `tests/programme/*.py`, `scripts/run_validation.py`, `config/universe_us.txt`, `backtest_strategy.py`, and the three `PROGRAMME_V3_*`/`V3_SPEC_COMPARISON_*` docs across from that branch — not the rest of its `src/aurelius/*` tree, which is a pre-rename mirror of what this branch already has under `mentisrex/*` and would have been pure duplication.
2. Renamed every `aurelius` reference in the incoming files to `mentisrex`, landing the package at `src/mentisrex/programme/`.
3. Found and fixed one real integration break: `programme/execution.py` imported a `BASE_URL` constant and a 3-positional-arg constructor from `mentisrex.paper.alpaca_broker` that no longer exist on this branch — the broker was hardened (M28) after the two branches diverged. Fixed to use the current `ALPACA_PAPER_BASE_URL` constant and keyword-only constructor. This is a genuine "full integration" fix, not a copy-paste: the programme's own broker class already documented that it reuses the firm's certified Alpaca paper broker rather than re-implementing one (`ADDENDUM A.6`) — it just needed to catch up to that broker's current shape.
4. Added `pandas`, `numpy`, `scipy`, `pyarrow` to `pyproject.toml` (they were used transitively but undeclared) and a `mrx` CLI entry point.
5. **Verified, not asserted:** ran `tests/programme/` (48/48 pass), ran the full repo suite (`2893 passed, 0 failed` — no regressions), and ran an actual end-to-end backtest against the live DuckDB store. Output matched the `deploy`-rung numbers in `PROGRAMME_V3_BACKTEST_RESULTS_2026-08-22.md` exactly, including the config fingerprint (`40feb9795aba9ea0`). Nothing here is claimed working without having been run.

**Strategy docs updated:**
- `docs/TRADING_STRATEGY_FORMAL.md` (the long-only volume-momentum book, v1.0) marked superseded with a pointer at the top — kept intact as the historical record, not deleted.
- `docs/TRADING_STRATEGY_FORMAL_V2.md` written as the new canonical strategy doc — full sleeve table, deployment ladder, backtest results, risk/circuit-breaker summary, and every known limitation carried forward from the original build report with its stated unblock condition.

**One operational bug found, not fixed:** a crontab entry already exists on this machine meant to run the programme in paper mode daily at 19:00 IST. Its working directory has a typo (`ponytai-ultra-49cf7e`, missing the `l`) and points at a path that doesn't exist — it has silently failed every weekday since 2026-08-22 (no log file was ever produced). I didn't touch your crontab without asking; say the word and I'll fix the path.

---

## 3. Current strategy — the answer to "what are we running"

**Mentisrex Programme v3.0** — `src/mentisrex/programme/`, config fingerprint `5252d1fc94eca6e2` at the `recommended` rung.

A daily-rebalanced core-satellite systematic US-equity programme: four directional sleeves trading SPY exposure (trend, vol-managed beta, breadth timing, panic reversal) plus six market-neutral cross-sectional sleeves (12-1 momentum, residual momentum, information-discreteness momentum, illiquidity premium, relative volume, conditional reversal), combined into one book under a hard gross cap and a real financing model (margin interest, borrow fee, short rebate — the single biggest gap the earlier audit found in every prior strategy on this repo, which modeled no cost of carry at all).

**Backtest, this firm's own data, 2017–2026, `recommended` rung:** CAGR 28.80%, Sharpe 1.10, max drawdown -28.6%, deflated Sharpe 0.996 (10,000-path bootstrap). **`deploy` rung (the recommended starting point):** CAGR 13.07%, Sharpe 1.18, max drawdown -15.0% — lower leverage, and Sharpe is *higher* than at full size, because cost and financing drag scale faster than return as gross rises.

**Not yet true, stated plainly:** paper mode has never actually executed (the broken cron job above is why), no order has been placed by this code, and two structural gaps are unresolved — no point-in-time/delisting data (same $500/year CRSP-or-equivalent gap the rest of the firm's research is blocked on) and no live short-borrow lookup, so the short legs currently assume every name is borrowable, which flatters drawdown over what's realistic.

**Recommended next step:** fix the cron typo (or run manually) to actually start the `deploy`-rung paper cycle — that's the fastest way to get real forward evidence, and the deployment ladder in `TRADING_STRATEGY_FORMAL_V2.md` §2.3 already specifies a four-quarter ramp from there to full size.

---

## 4. Commits and push

All of the above is committed on `aidp/audit-and-pit-gaps`; local `main` was fast-forwarded to it and pushed to `origin/main`.
