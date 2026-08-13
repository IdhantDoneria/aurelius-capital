# Phase 21: Autonomous Alpha Discovery Engine — Technical Specification

## Overview

The **Autonomous Alpha Discovery Engine** (`src/mentisrex/discovery/`) is an AI-driven, continuous research discovery subsystem that proposes novel, testable trading hypotheses using institutional knowledge across all platform repositories rather than relying solely on external papers.

---

## Architectural Lifecycle (Parts 1–6)

```
[ Knowledge Graph + Corpus + Literature + Experiments + Features + Validation Reports ]
                                          │
                                          ▼
                         [ Part 1: KnowledgeSynthesizer ]
                           Extracts Gaps, Untested Pairs, Trends
                                          │
                                          ▼
                      [ Part 2: AlphaHypothesisGenerator ]
                        Generates Candidates via 12 Rules
                                          │
                                          ▼
                          [ Part 3: NoveltyScorer ]
                        Scores Novelty, Similarity, Value, Cost
                                          │
                                          ▼
                         [ Part 5: SelfCritiqueEngine ]
                        Applies Falsification & Counter-Arguments
                                          │
                               ┌──────────┴──────────┐
                               ▼                     ▼
                      [ Part 6: Approved ]  [ Part 6: Rejected ]
                               │                     │
                               ▼                     ▼
                         HypothesisStore        Rejection Log
```

---

## Component Specifications

### 1. Knowledge Synthesizer (`synthesis.py`)
- Reads graph structure from `KnowledgeGraph` (`./data/knowledge_graph.duckdb`), documents from `CorpusStore` (`./data/corpus.duckdb`), and historical outcomes from `ResearchStore` (`./data/research.duckdb`).
- Produces a `SynthesisReport` containing:
  - Common themes across validated strategies.
  - Untested factor combinations (e.g. `Momentum` $\times$ `Quality`).
  - Missing feature pairs (e.g. `12-1m Momentum` $\times$ `30d Realized Volatility`).
  - Contradictory findings and emerging quantitative finance research trends.

### 2. Hypothesis Generator (`generator.py`)
- Implements 12 novel generation rules:
  1. **Factor Combination** (`Value` + `Momentum`)
  2. **Cross-Asset Reasoning** (`Yield Curve Slope` + `FX Carry`)
  3. **Alternative Data + Macro Interaction** (`Web Search Trends` + `PEAD`)
  4. **Microstructure Horizon Shifts** (`LOB Queue Imbalance` + `VPIN`)
  5. **Behavioral Regime Shifts** (`Panic Sell-Off Reversal`)
  6. **Multi-Horizon Frequency Scaling**
  7. **Universe Expansion**
  8. **Non-Linear Factor Transforms**
  9. **Unrelated Paper Fusion**
  10. **Unrelated Feature Cross-Products**
  11. **Macro Interaction Conditioning**
  12. **Holding Period Adjustments**

### 3. Novelty Scorer (`scorer.py`)
- Evaluates candidate hypotheses against `HypothesisStore` and `KnowledgeGraph`.
- Output: `NoveltyScore`
  - `novelty`: Rating from 1 (derivative) to 5 (highly novel).
  - `similarity_to_previous`: Jaccard text & graph distance metric (0.0 to 1.0).
  - `research_value`: Score from 0.0 to 100.0.
  - `economic_rationale`: Rating 1 to 5.
  - `testability`: Rating 1 to 5.
  - `expected_compute_cost`: Rating 1 to 5.
  - `potential_impact`: Score 0.0 to 100.0.

### 4. Comprehensive Research Explanation (`models.py`)
- Every candidate `DiscoveryHypothesis` includes:
  - Economic intuition & rationale.
  - Testable IF-THEN statement & expected behavior.
  - Why it exists & why it might fail.
  - Supporting and contradicting literature citations.
  - Required datasets and feature dependencies.
  - Validation plan & expected weaknesses.

### 5. Self-Critique & Falsification Engine (`critique.py`)
- Performs simulated adversarial peer review:
  - Generates top counter-arguments (e.g. statistical artifact, turnover friction, regime instability).
  - Formulates explicit falsification criteria (e.g., OOS Sharpe < 0.50, Bonferroni p-value > 0.05, breakeven TC < 5bps).
  - Proposes competing explanations (Risk compensation vs Microstructure drag vs Liquidity premium).
  - Filters out candidates failing testability or similarity thresholds.

### 6. Orchestration Framework Integration (`engine.py`)
- Converts approved candidate hypotheses into `HypothesisRecord` instances and inserts them directly into `HypothesisStore` (`./data/hypothesis.duckdb`).
- Submits active hypotheses to `ResearchDirector` for automated prioritization.
- Logs rejected hypotheses with detailed rationale.

---

## REST API Reference (`api.py`)

- `POST /discovery/run`: Executes an autonomous Alpha Discovery cycle.
  - Request: `{"candidate_limit": 5}`
  - Response: `DiscoveryCycleResult` (synthesis, approved, rejected hypotheses).
- `GET /discovery/synthesize`: Retrieves current knowledge synthesis & research gaps.
  - Response: `SynthesisReport`.
- `GET /discovery/hypotheses`: Lists all active hypotheses generated by the Discovery Engine.
