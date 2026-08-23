# MentisRex Research-Program Audit & Roadmap (2026-08-14)

Audit of the existing repository against the institutional research-machine
target architecture. **Finding: the vast majority of the target is already
built and certified across ~30 milestones (AIDP M2–M11, MENTISREX M12–M24,
MENTISREX M26–M30).** This program is therefore *gap-closing + breadth*, not a
greenfield build. The frozen `ew-momentum-exp v1.0.0`
(`b69961b65bab226a500d71f45709945b`) is untouched.

## 1. Current capability map (built & present)

| Target layer | Where it lives | Status |
|---|---|---|
| Security master (immutable `security_id`, ticker/identity history, lifecycle) | `market_data/identity/security_master.py`, `research/market_data/identifiers.py` | Built |
| PIT data model (`as_of`, snapshot builder, revisions, provenance) | `research/market_data/pit.py`, `models.py`, `revisions.py` | Built |
| Historical universe engine (`universe_as_of`, delisting exclusions) | `market_data/universe/engine.py`, `market_data/delistings/store.py` | Built |
| Data quality | `research/forward_campaign/data_quality.py`, `research/market_data/normalization.py` | Built |
| Feature engine | `features/`, `market_data/research_matrix/` | Built |
| Hypothesis engine | `hypothesis/`, `docs/HYPOTHESIS_FRAMEWORK.md` | Built |
| Experiment registry (fingerprint, lineage, reproduce, immutable) | `research/experiment_registry/` | Built |
| Statistical engine (bootstrap, PSR, deflated Sharpe, PBO/CSCV, White RC, multiple-testing, permutation, MC) | `research/validation/` | Built |
| Signal / catalog | `catalog/`, `discovery/` | Built |
| Backtesting | `backtesting/`, `research/simulation/` | Built |
| Walk-forward / OOS | `research/validation/walkforward.py`, `legacy.py` | Built |
| Portfolio construction (EW, inv-vol, risk-parity, MV, constrained) | `research/portfolio/`, `research/portfolio_construction.py` | Built |
| Risk engine + kill switches | `research/risk/`, `research/paper_trading/risk.py` | Built |
| Execution / cost / capacity | `research/execution/`, `research/simulation/models.py`, `research/validation/capacity.py` | Built |
| Paper trading + Alpaca + forward validation | `paper/`, `research/paper_trading/`, `research/forward_validation/`, `research/forward_campaign/` | Built |
| Multi-currency / multi-asset / FX | `research/fx/`, `research/instruments/`, `research/valuation/` | Built |
| Knowledge graph, literature, AI research layer | `knowledge/`, `literature/`, `intelligence/`, `assistant/`, `director/` | Built |
| Governance / promotion / monitoring | `operations/`, `research/strategy_deployment/`, `docs/*RUNBOOK*` | Built |

## 2. Missing capability map (genuine gaps)

Confirmed by grep across `src/**/*.py`:

- **P0 — HAC / Newey-West standard errors: ABSENT.** `significance.py` uses IID
  SE (`std/√n`) and Lo-2002 Sharpe SE. Both assume no serial correlation. Momentum
  / overlapping-horizon returns are autocorrelated → **t-stats and p-values are
  overstated**, feeding the promotion gate a false-positive bias. This is a
  research-integrity correctness defect, not a feature.
- **P0 — Purged & embargoed cross-validation: ABSENT.** Only CSCV exists
  (`overfitting.py`, on a returns matrix). Panel research that builds features →
  H-day-forward labels has train/test leakage across the label horizon with plain
  K-fold/walk-forward. No `purge`/`embargo` anywhere.
- **P1 — Cross-sectional neutralization** (sector-/beta-/vol-neutral ranking,
  residualization) — no explicit implementation (`§XI`).
- **P1 — Signal redundancy detector** ("is this a disguised known factor?", `§XI`/`§XII`).
- **P2 — Research-selection / degrees-of-freedom ledger** (trials counter feeding
  deflated-Sharpe `n_trials`, `§XIII`).

## 3. Dependency graph (gap items only)

```
PIT ─┐
     ├─> purged/embargoed CV ─┐
labels(H)┘                    ├─> trustworthy OOS ─> promotion gate
HAC standard errors ──────────┘         │
                                        └─> deflated-Sharpe n_trials <- DoF ledger
neutralization ─> signal redundancy detector
```
HAC + purged CV are the roots: every downstream significance/OOS verdict depends
on them being correct.

## 4. Technical debt relevant here
- `significance.py` mixes IID CI half-width (`tcrit=1.96`) with t-based p-value —
  acceptable but should expose a HAC path.
- Two walk-forward code paths (`legacy.py` + `walkforward.py`); neither purges.

## 5. Research-integrity risks
- Overstated significance on autocorrelated returns (HAC gap) — **live now**.
- Horizon-overlap leakage in any future panel CV (purge gap).

## 6. Data gaps
None blocking milestone 1 (pure statistical layer). Broader fundamentals/estimates
coverage tracked in `docs/DATA_READINESS_REPORT.md`.

## 7. Compute/storage bottlenecks
None for milestone 1. Existing DuckDB stores scale to the current universe.

## 8. Architecture changes required
None. Milestone 1 is **additive** to `research/validation/` — no interface break,
no change to existing `significance()` fields (new fields appended only).

## 9. Recommended milestone sequence
- **M31 (this milestone, P0): Statistical-validity correctness** — HAC/Newey-West
  standard errors + purged/embargoed CV splitter. Roots of the dependency graph.
- M32 (P1): cross-sectional neutralization + signal redundancy detector.
- M33 (P1): research degrees-of-freedom ledger → wired into deflated-Sharpe.
- M34+ (P2/P3): strategy-family breadth on top of the corrected stats layer.

Rationale for ordering: §XXXVI forbids advancing while a prerequisite stage has
"unresolved correctness problems". HAC + purge are exactly that in STAGE 3/4, so
they precede all breadth work.

## 10. First milestone scope (exact) — M31
`src/mentisrex/research/validation/`:
1. `hac.py` — Newey-West long-run variance; `hac_standard_error(returns, lag=None)`
   (Bartlett kernel, auto lag = ⌊4·(n/100)^(2/9)⌋ per Newey-West 1994).
2. Extend `significance()` with additive `hac_se`, `hac_t_stat`, `hac_p_value`,
   `hac_lag` fields (existing fields unchanged → regression-safe).
3. `cross_validation.py` — `purged_kfold(n, n_splits, embargo, label_horizon)`
   yielding leak-free `(train_idx, test_idx)` with horizon purge + embargo.
4. Deterministic tests: HAC ≥ IID SE under positive autocorrelation; purged folds
   have zero train/test index within `horizon+embargo`.
5. Export both from `validation/__init__.py`.

Out of scope (explicitly deferred, per CLAUDE.md no-silent-skip rule): items in
§2 marked P1/P2 — deferred to M32/M33 as sequenced above, not skipped.
