# Aurelius Research Platform — Engineering Principles

The rules every milestone (M12 onward) must obey. These are inherited, not
negotiated. A milestone is not complete until it satisfies all of them. They encode
how the platform stayed correct, reproducible, and institution-grade across M1–M11.

## Correctness

1. **Point-in-time correctness.** Every read answers "what was knowable as of date
   D?". No future information may enter any computation. Availability gates
   (`filing_date`, `acceptance_datetime`, `announced_date`) are load-bearing.
2. **No look-ahead, ever.** Downstream layers add no new temporal logic that could
   bypass an upstream gate. If a new source is added, it ships with its own gate.
3. **Determinism.** Same inputs → identical outputs. No unseeded RNG. All randomness
   is seeded and injected. Hashes are order-independent.
4. **Offline reproducibility.** The research path runs offline from stored metadata.
   Any result is reproducible later from its registry entry.

## Structure

5. **Dependency Injection first.** Depend on interfaces (solvers, execution models,
   estimators, providers), never concrete engines. No hard-coded optimizer, broker,
   or data source.
6. **No hidden globals.** No module-level mutable state, no ambient singletons. State
   is explicit, passed, and owned.
7. **Immutable research results.** Results, snapshots, and reports are frozen
   dataclasses. Mutable state is confined to a single owner (e.g. `PortfolioState`)
   and never leaks.
8. **No duplicated logic.** Reuse the certified engine; never re-implement metrics,
   PIT reads, registry, or accounting. Composition over duplication.
9. **Separation of concerns.** Alpha generation, portfolio construction, simulation,
   and validation are distinct layers with one-way dependencies. A signal is not a
   portfolio; a portfolio is not a track record.

## Process

10. **Additive development.** Extend; never rewrite certified milestones. No breaking
    changes to a prior milestone's APIs, models, interfaces, or numerics without a
    proven defect.
11. **No breaking previous milestones.** The full regression suite passes with
    **zero regressions** before any milestone is certified.
12. **Validation before completion.** A milestone validates its own outputs
    (accounting reconciliation, consistency checks, and — where applicable — the M9
    quality gate) before it is considered done.
13. **Benchmark before merge.** Every milestone ships a benchmark with reported
    runtime and memory. Performance targets are stated and measured, not assumed.
14. **Documentation required.** Every milestone ships an `AIDP_Mn_*.md` deep-dive and
    updates the milestone index. Assumptions and limitations are documented, never
    hidden.
15. **Tests required.** Every milestone ships an offline, deterministic test suite
    covering its behaviour and integration points.
16. **Honest limitations.** If something cannot be built correctly with available
    data/dependencies, it is documented as a limitation with the unblocking
    requirement — never faked or silently approximated.

## Governance

17. **One milestone number line.** Milestones are `Mn`, never "Phase". Numbers never
    restart and never collide. Future work continues `M12, M13, …`.
18. **Every commit is meaningful and attributed.** Conventional-commit messages;
    each milestone is a discrete, reviewable commit.
19. **Report in the standard format.** Every milestone report uses the 11-section
    format in `docs/templates/MILESTONE_TEMPLATE.md`.

## The standard milestone report format

1. Files changed
2. Architecture decisions
3. Design overview
4. Major components
5. Integration points
6. Validation
7. Tests
8. Benchmarks
9. Limitations
10. Commit hash
11. Recommendation for next milestone
