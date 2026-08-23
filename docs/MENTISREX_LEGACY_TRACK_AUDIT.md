# Mentisrex — Legacy Track Reconciliation Audit

**Type:** Governance & architecture audit (read-only). No source, API, interface,
test, or behaviour changes. Documentation only.
**Predecessor:** Milestone Normalization (`52e94df`).
**Canonical line at audit time:** M1–M11 certified; M12+ pending. Test suite
unchanged: 213 passed, 3 skipped, 0 regressions.

---

## 1. Executive summary

The repository contains **two distinct milestone numbering systems**, born from two
distinct engineering efforts on the same codebase:

- **Platform Track ("Phase N").** The original Mentisrex build — a full research-OS
  and trading platform delivered as development milestones "Phase 1 … Phase 27"
  (risk, construction, paper trading, AI assistant, knowledge graph, research
  director, intelligence, laboratory, data-intelligence catalog, …). This track is
  **feature-frozen** per its own acceptance audit (`docs/ACCEPTANCE_TEST.md`) and
  remains live in `src/mentisrex/{risk,construction,paper,assistant,validation,
  knowledge,director,intelligence,lab,catalog,…}`.

- **Canonical AIDP Track ("Mn").** The `aidp/audit-and-pit-gaps` effort that rebuilt
  the **data and research core** to institutional point-in-time standards —
  M1 (market data) → M11 (portfolio simulation). This is the authoritative
  milestone line going forward (`MENTISREX_MILESTONE_INDEX.md`).

The two tracks **share low Phase/M numbers that mean different things** (Platform
"Phase 7" = Risk Engine; AIDP "M7" = Experiment Registry). They are not in conflict
functionally — they are two lenses on one codebase, built at different times to
different standards. The normalization (`52e94df`) correctly converted **only the
AIDP track** to `Mn` and left the Platform Track's "Phase N" labels intact, because
mechanically renaming them would fabricate duplicate milestone numbers.

This audit catalogs the Platform Track, classifies each reference, establishes its
relationship to the canonical line, and recommends a resolution: **freeze the legacy
"Phase N" terminology as historical, track the underlying capabilities by name, and
re-home each capability into the canonical M-line only as a future M-milestone
rebuilds it** (exactly as M1–M11 rebuilt the data/research core).

## 2. Historical timeline

```
   original Mentisrex platform build ("Platform Track", Phase 1 … Phase 27)
   ─────────────────────────────────────────────────────────────────────►
   P1-2  base / market data
   P3-4  backtesting engine + strategy contract + PerformanceCalculator
   P5    feature library
   P6    validation / verdict
   P7    Risk Engine            ┐
   P8    Portfolio Construction │ application layer
   P9    Paper Trading          │ (live, feature-frozen)
   P10   AI Research Assistant  ┘
   P14   Statistical Validation & Robustness
   P15   Knowledge Graph
   P16   Research Director
   P17   Research Intelligence
   P18   Research Laboratory
   P22   Institutional Data Intelligence (catalog)
   P27   (final roadmap item)

                         ┌── later, separate effort ──┐
                         ▼                             │
   AIDP audit-and-pit-gaps rebuild ("Canonical Track", M1 … M11)
   ─────────────────────────────────────────────────────────────────────►
   M1 market data · M2 identity · M3 fundamentals · M4 universe · M5 insiders
   M6 research matrix · M7 registry · M8 execution · M9 validation
   M10 portfolio construction · M11 portfolio simulation
```

The AIDP track rebuilt the **core** the Platform Track's early phases had covered
(data, features, validation), to a stricter PIT/deterministic standard, and stopped
at M11. The Platform Track's **application layer** (risk, paper, assistant, knowledge,
director, intelligence, lab, catalog) has **no AIDP equivalent yet**.

## 3. Legacy Phase inventory

Authoritative capability↔phase mapping (from each subsystem's `__init__` tag) plus
the internal cross-reference phases.

| Legacy Reference | Location | Meaning | Status | Canonical Relationship |
|---|---|---|---|---|
| Phase 4 | `research/models.py`, `research/templates.py`, `paper/dashboard.py` | backtesting strategy contract + PerformanceCalculator | active (reused by AIDP) | superseded-in-naming; module reused by M8/M10 |
| Phase 5 | `research/templates.py`, `research/validation/legacy.py` | feature library / feature ranking | active | overlaps M6 research matrix capability |
| Phase 6 | `assistant/assistant.py` | validation verdict | active | overlaps M9 validation capability |
| Phase 7 | `risk/__init__.py`, `risk/models.py`, `construction/builder.py`, `paper/broker.py` | **Risk Engine** | active | **independent** — collides numerically with M7 (registry) |
| Phase 8 | `construction/__init__.py`, `construction/{aggregation,builder}.py`, `paper/engine.py` | **Portfolio Construction (legacy)** | active | overlaps M10 capability; collides with M8 (execution) |
| Phase 9 | `paper/__init__.py` | **Paper Trading** | active | independent; collides with M9 (validation) |
| Phase 10 | `assistant/__init__.py` | **AI Research Assistant** | active | independent; collides with M10 (portfolio) |
| Phase 14 | `validation/__init__.py`, `validation/service.py` | Statistical Validation & Robustness | active | overlaps M9 capability |
| Phase 15 | `knowledge/__init__.py` | Knowledge Graph | active | independent (future M-milestone) |
| Phase 16 | `director/__init__.py`, `director/director.py` | Research Director | active | independent (future) |
| Phase 17 | `intelligence/__init__.py`, `intelligence/api.py` | Research Intelligence | active | independent (future) |
| Phase 18 | `lab/__init__.py`, `lab/{api,monitor}.py` | Research Laboratory | active | independent (future) |
| Phase 22 | `docs/DATA_INTELLIGENCE_PLATFORM.md`, catalog | Institutional Data Intelligence (catalog) | active | overlaps M6/M7 metadata capability |
| Phase 27 | `docs/DATA_INTELLIGENCE_PLATFORM.md` | final roadmap item | roadmap/unclear | no relationship |

**Footprint:** 24 source files, 18 documents, 7 test files reference Platform-Track
"Phase N" (full lists at the end of this document).

Classification summary:
- **Superseded (naming only), module still active & reused by AIDP:** legacy Phase 4
  (backtesting/PerformanceCalculator — M8 and M10 import it), Phase 5/6/14
  (feature/validation — capability re-delivered by M6/M9).
- **Active, independent application layer, no AIDP equivalent:** Phase 7 risk, 8
  construction, 9 paper, 10 assistant, 15 knowledge, 16 director, 17 intelligence,
  18 lab, 22 catalog.
- **Unclear/roadmap:** Phase 27.

## 4. Architecture relationship

```
        CANONICAL AIDP TRACK (Mn)                 PLATFORM TRACK (Phase N)
        institutional PIT rebuild                 original full platform (frozen)
   ┌─────────────────────────────────┐        ┌──────────────────────────────────┐
   │ M1  market data                 │        │ P1-2 base / market data           │
   │ M2  identity                    │  ══╗    │ P3-4 backtesting + contract       │◄─┐ reused
   │ M3  fundamentals                │    ║    │ P5   feature library              │  │ by AIDP
   │ M4  universe                    │  rebuilds P6   validation / verdict        │  │ (M8/M10
   │ M5  insiders                    │  the ║   │ P7   Risk Engine                 │  │ import
   │ M6  research matrix             │  core║   │ P8   Portfolio Construction      │  │ backtesting
   │ M7  experiment registry         │    ║    │ P9   Paper Trading                │  │ engine +
   │ M8  execution ──────────────────┼────╨────┤ P10  AI Research Assistant        │──┘ perf calc)
   │ M9  validation                  │        │ P14  Validation & Robustness      │
   │ M10 portfolio construction      │        │ P15  Knowledge Graph              │
   │ M11 portfolio simulation        │        │ P16  Research Director            │
   │ M12+ (paper bridge, risk, …)    │◄───────┤ P17  Research Intelligence        │
   └─────────────────────────────────┘  future │ P18  Research Laboratory          │
                                        adopts  │ P22  Data-Intelligence catalog    │
                                        by name │ P27  …                            │
                                                └──────────────────────────────────┘
```

- The AIDP track **depends on** parts of the Platform track (M8's execution runs the
  Platform-track `BacktestEngine`; M10/M11 reuse its `PerformanceCalculator`). So the
  Platform track is not dead code — its lower layers are load-bearing.
- The AIDP track **re-delivers** the Platform track's data/feature/validation core at
  a higher PIT standard (M1–M9), but does **not** re-deliver the application layer
  (risk/paper/assistant/knowledge/director/intelligence/lab/catalog).
- The number **collision** is confined to low numbers (7/8/9/10) where the two tracks
  independently assigned the same integers to different capabilities.

## 5. Recommended resolution

**Options evaluated**

- **Option A — Preserve legacy numbering permanently, as-is.** Zero risk, but leaves
  two live "Phase 7…10" meanings indefinitely; future readers keep hitting the
  collision. *Insufficient on its own.*
- **Option B — Archive legacy terminology as historical.** Freeze "Phase N" as a
  historical label of the Platform track; forbid its use in new work. Preserves the
  record, removes it from the *forward* vocabulary. *Strong.*
- **Option C — Map capabilities into canonical M milestones (renumber now).** Would
  create immediate duplicate milestones (legacy Phase 7 → M7 vs registry M7), break
  historical reports/acceptance records, and imply a rebuild that hasn't happened.
  *Rejected — violates "no duplicate milestones / no historical loss".*
- **Option D — Separate capability taxonomy.** Track platform capabilities by **name**
  (Risk Engine, Paper Trading, Knowledge Graph, …) independent of any number, in the
  roadmap. *Strong, complements B.*

**Recommendation: Option B + Option D.**

1. **Freeze** the Platform-Track "Phase N" strings as historical (no edits, no
   renames). They are an accurate record of when those modules were built.
2. **Name, don't number, capabilities.** In `MENTISREX_ROADMAP.md`, the Platform-Track
   capabilities are already listed by name (Risk Engine, Paper Trading, …). Refer to
   them that way — never by their legacy Phase number — in all new writing.
3. **Adopt into the canonical line only on rebuild.** When a future M-milestone
   modernizes a capability (e.g. M12 = Paper-Trading Bridge), the new module carries
   an `Mn` tag and the superseded Platform-Track module is marked historical. This is
   exactly how M1–M11 absorbed the data/research core. No mass renumbering event.

This preserves history, eliminates the collision from forward vocabulary, keeps the
load-bearing legacy modules working, and gives M12+ a clean, unambiguous path.

## 6. Rules for future development

**When to use M-numbering**
- Every **new engineering milestone** is `Mn` (next: M12), continuing the canonical
  line. Never "Phase". Numbers never restart or collide.
- A milestone that rebuilds/absorbs a legacy capability tags its new modules `Mn` and
  marks the superseded module historical.

**When to use capability names**
- Refer to platform capabilities (Risk Engine, Portfolio Construction, Paper Trading,
  AI Assistant, Knowledge Graph, Research Director/Intelligence/Laboratory, Data-
  Intelligence Catalog) **by name** in all new docs, plans, and reviews — not by any
  legacy Phase number.

**When historical terminology stays untouched**
- Legacy "Phase N" strings in Platform-Track source, docs, and tests are **historical
  record**. Do not rename, renumber, or delete them. They document original build
  order and are referenced by acceptance/campaign reports whose integrity depends on
  stable labels.

---

### Appendix — full reference lists

**Source (24 files):** `assistant/{__init__,assistant}.py`,
`construction/{__init__,aggregation,builder}.py`, `director/{__init__,director}.py`,
`intelligence/{__init__,api}.py`, `knowledge/__init__.py`,
`lab/{__init__,api,monitor}.py`, `paper/{__init__,broker,dashboard,engine}.py`,
`research/{models,templates}.py`, `research/validation/legacy.py`,
`risk/{__init__,models}.py`, `validation/{__init__,service}.py`.

**Docs (18):** `ALPHA_DISCOVERY_ENGINE.md`, `DATA_INTELLIGENCE_PLATFORM.md`,
`DATA_READINESS_REPORT.md`, `DEPLOYMENT.md`, `HYPOTHESIS_FRAMEWORK.md`,
`KNOWLEDGE_GRAPH.md`, `LITERATURE_FRAMEWORK.md`, `PILOT_RESEARCH_CAMPAIGN.md`,
`PRODUCTION_CAMPAIGN_REPORT_2026-07-30.md`, `REPRODUCTION_SCOREBOARD.md`,
`RESEARCH_CAMPAIGN_ROADMAP.md`, `RESEARCH_CORPUS.md`, `RESEARCH_DIRECTOR.md`,
`RESEARCH_INTELLIGENCE.md`, `RESEARCH_LABORATORY.md`, `RESEARCH_OS.md`,
`Research_Roadmap_v2.md`, `VALIDATION_FRAMEWORK.md`.

**Tests (7):** `tests/{assistant,backtesting,construction,operations,paper,risk,
validation}/…`.

All references above are **preserved unchanged** by this audit.
