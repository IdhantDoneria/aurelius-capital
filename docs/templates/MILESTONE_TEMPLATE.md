# M{N} — {Official Milestone Name}

> Template for all milestones **M12 onward**. Copy to `docs/AIDP_M{N}_{SLUG}.md`,
> fill every section, and add the milestone to `AURELIUS_MILESTONE_INDEX.md`.
> Obey `AURELIUS_ENGINEERING_PRINCIPLES.md` — additive, PIT-safe, deterministic,
> dependency-injected, zero regressions.

**Milestone:** M{N}
**Capability:** {which capability in AURELIUS_ROADMAP.md this delivers/extends}
**Depends on:** M{…}
**Status:** DRAFT → CERTIFIED
**Branch:** `{branch}`

---

## Summary

One paragraph: what this milestone adds and why. State explicitly that it is
additive and does not modify certified milestones.

## Architecture

Design decisions, module responsibilities, dependency-injection seams, and how it
composes with existing layers. Include a dependency/data-flow sketch if useful.

## Design overview

The core idea and the key interfaces/dataclasses introduced.

## Major components

| Module | Responsibility |
|---|---|
| `…` | … |

## Integration points

How it integrates with the research matrix (M6), registry (M7), execution (M8),
validation (M9), portfolio (M10), simulation (M11) — without rerunning or modifying
them.

## Point-in-time / determinism

State the PIT guarantee and how determinism is preserved (seeds, injected providers,
immutable results).

## Validation

Accounting/consistency checks and, where applicable, the M9 quality-gate integration.

## Tests

`tests/…/test_{slug}.py` — list the covered cases. Full suite result:
**{X} passed, {Y} skipped, zero regressions.**

## Benchmarks

`scripts/benchmark_{slug}.py` — runtime, memory, throughput, targets vs actuals.

## Limitations / Known gaps

Honest limitations with the unblocking requirement for each. Never fake a result.

## Commit hash

`{hash}` (branch `{branch}`).

## Recommendation for next milestone

M{N+1}: {proposed capability}, and why it is the natural successor.

---

### Standard final-report format (return exactly these 11 sections)

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
