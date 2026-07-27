# Session Handoff — Aurelius Capital

**Read this, then delete it.** Ephemeral. It exists only to warm-start a fresh Claude session. All durable content lives in the docs/scripts it points to.

Repo: `/Users/idhantdoneria/aurelius-capital` (git). Branch `main`. Python venv at `.venv` — **use `.venv/bin/python`, not `python`**.

---

## What this project is

`aurelius-capital` = a systematic quant research platform (event-driven backtester, portfolio/risk engines, paper-trading loop, AI research assistant, DuckDB research store). Engineering is **feature-frozen**. Work has shifted from *building the platform* to *running research on it*.

## Active operating modes (both ON, persist across session)

- **Ponytail (full)** — lazy/reuse-first. Climb the ladder: does it need to exist → already in repo → stdlib → one line → minimal code. Bug fix = root cause, not symptom. One runnable check per non-trivial logic. `# ponytail:` comments mark deliberate ceilings.
- **Caveman (full)** — terse chat prose. Drop articles/filler/hedging. **Code, commits, docs = normal English.** Security/irreversible = normal English.

**Hard rule:** NEVER commit from the HOME repo `/Users/idhantdoneria/.git` (would stage the entire home dir + dotfiles). Only ever commit inside `/Users/idhantdoneria/aurelius-capital/.git`.

## AI assistant constraint (structural)

`aurelius.assistant` reads papers, generates hypotheses, reviews code, detects bias, writes reports — it **cannot trade**. Enforced structurally. Do not add a trading path to it.

---

## What was delivered this session (all done, verified)

Three role-play deliverables, then the ROS + dashboard:

1. **CTO acceptance test** → `docs/ACCEPTANCE_TEST.md`. Audited 13 subsystems; ran 5 benchmark strategies through the REAL engine on seeded multi-symbol data. **Found + fixed a critical bug** (see below). Verdict: single-asset research trustworthy now; cross-sectional not yet (data-side blockers). Scores: overall 72, prod 73, research 70. Conditional freeze.

2. **Director research program** → `docs/RESEARCH_PROGRAM.md` (constitution: 8 alpha lanes, validation pipeline, rejection rules, promotion, roadmap+KPIs), `docs/ALPHA_TAXONOMY.md` (15-category taxonomy + 11-stage Hypothesis Factory + 10-axis scorecard), `docs/HYPOTHESIS_BACKLOG.md` (500 ranked hypotheses H001–H500, tiered S/A/B/C).

3. **Research Operating System** → `docs/RESEARCH_OS.md`. The operating manual. 5 parts: (1) repo structure — binds git artifacts to `research.duckdb` by ID, no third store; (2) 9 templates mapped to real `research.models` fields; (3) 9-stage lifecycle with gates + exit criteria; (4) dashboard as SQL panels; (5) KPIs with formulas. Lifecycle stage rides `hypotheses.status` at zero migration.

4. **Dashboard CLI** → `scripts/research_dashboard.py`. Read-only Part-4 panels over `research.duckdb`, reuses `ResearchStore._query`/`rejected_ideas()`. `--selftest` seeds in-memory + asserts (passes). Live DB currently empty → clean `n/a`.

## The critical bug (fixed, keep in mind)

**Cross-symbol fill bug.** `ExecutionSimulator.try_fill` never matched `order.symbol == bar.symbol`, and `engine._process_bar` tried every pending order against the current bar. In a single-symbol universe (every pre-existing test) invisible. Multi-symbol: an `AAA` order filled against the next chronological bar of a *different* instrument — wrong price, wrong symbol, same day (broke T+1). **Fix:** one-line symbol guard in `src/aurelius/backtesting/engine.py` `_process_bar` (skip non-matching bars, keep order pending). Regression test: `test_multi_symbol_fills_against_own_bar` in `tests/backtesting/test_engine.py`.

## Uncommitted state (nothing committed yet this session)

```
 M src/aurelius/backtesting/engine.py        # the cross-symbol fill fix
 M tests/backtesting/test_engine.py          # regression test
?? docs/ACCEPTANCE_TEST.md ALPHA_TAXONOMY.md HYPOTHESIS_BACKLOG.md RESEARCH_OS.md RESEARCH_PROGRAM.md
?? scripts/acceptance_validation.py scripts/research_dashboard.py
?? data/                                      # local research.duckdb — likely gitignore, do NOT commit
```

Tests: full non-integration suite **217 passed** after the fix. Verify with `.venv/bin/python -m pytest -m "not integration" -q`.

## Known open items (reported, NOT fixed — do not start unprompted)

From `ACCEPTANCE_TEST.md` Phase 3/4, gating cross-sectional research:
1. **Equity sampled per bar-event, not per calendar day** → Sharpe/vol mis-annualized on multi-symbol. (Critical, Small.)
2. Point-in-time / bitemporal fundamentals. (Critical, Large.)
3. Survivorship-free universe. (Critical, Medium.)
4. Corporate-action golden-case test. (High, Small.)
5. Immutable dataset+config snapshot lock per run. (High, Small.)

## Likely next moves (only if user asks)

- Commit: engine fix + tests as one `fix:` commit, docs + scripts as `docs:`/`feat:` — inside the project repo only.
- Knock out acceptance fixes #1 + #4 (both Small) to unlock the single-asset freeze.
- Start populating `research.duckdb` from the 500-hypothesis backlog per the ROS lifecycle.
