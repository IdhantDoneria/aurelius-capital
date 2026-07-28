# Hypothesis Generation Framework

**Phase 12 — Aurelius Capital**

Converts enriched research papers into structured, testable quantitative hypotheses. Output is a prioritized research queue consumed by human researchers and (eventually) the Experiment Framework. Does not run backtests, generate signals, or access market data.

---

## Architecture

```
LiteratureStore (Phase 11)
  │
  ▼ Paper (enriched)
  │
  ▼
HypothesisGenerator ──────────────────────────────►  list[HypothesisRecord]
  │  LLMClient (injected, optional)                      │
  │  Template fallback if LLM absent or fails            │
  │                                                      ▼
  │                                             QualityFilter.check()
  │                                                      │
  │                                             ┌────────┴────────┐
  │                                             │ Fail            │ Pass
  │                                             ▼                 ▼
  │                                     status=Rejected   DuplicateDetector.check()
  │                                             │                 │
  │                                             │         ┌───────┼──────────┐
  │                                             │         │       │          │
  │                                             │      UNIQUE  NEAR_DUP  DUPLICATE
  │                                             │         │       │          │
  │                                             │         │   similar_to  Rejected
  │                                             │         │   flagged        │
  │                                             └─────────┴──────────────────┘
  │                                                       │
  │                                                       ▼
  │                                              HypothesisStore.insert()
  │                                              (hypothesis.duckdb)
  │
  └──────► Draft queue → researcher review → Active / Rejected / Promoted
```

---

## Components

### `HypothesisRecord` (`models.py`)

The complete structured output. All fields are populated at generation time; enrichment fields default to empty rather than None for type safety.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | UUID4 — random, not content-derived |
| `parent_papers` | `list[str]` | Paper IDs from `LiteratureStore` |
| `research_category` | `str` | Inherited from paper or set by LLM |
| `economic_intuition` | `str` | WHY this should generate returns |
| `testable_statement` | `str` | IF [condition] THEN [outcome] AMONG [universe] OVER [horizon] |
| `expected_behavior` | `str` | Pattern to observe in the data |
| `asset_classes` | `list[str]` | |
| `required_datasets` | `list[str]` | Data sources needed to test |
| `required_features` | `list[str]` | Computed signals needed |
| `holding_period` | `str` | e.g. `1_month`, `1_week` |
| `expected_risks` | `list[str]` | Crowding, timing, macro sensitivity |
| `confidence_score` | `float` | 0.0–1.0; LLM self-assessed |
| `assumptions` | `list[str]` | Key assumptions required |
| `dependencies` | `list[str]` | Prerequisite factors or hypotheses |
| `validation_requirements` | `list[str]` | What must hold for confirmation |
| `similar_to` | `list[str]` | IDs of near-duplicate hypotheses |
| `status` | `str` | Draft → Active → Rejected / Promoted |
| `version` | `int` | Increments on every `store.update()` |
| `created_at` | `datetime` | |
| `updated_at` | `datetime` | |
| `researcher` | `str` | `"llm"`, `"template"`, or human name |
| `generation_method` | `str` | `llm \| template \| manual` |
| `rejection_reason` | `str` | Set when `status=Rejected` |

---

### `HypothesisGenerator` (`generator.py`)

Single entry point: `generate(paper, llm=None, researcher="llm") → list[HypothesisRecord]`

Two modes:

**LLM mode** (when `llm` is provided):
- Sends structured prompt to LLM requesting 1–3 hypotheses as JSON array.
- Parses response via `_extract_json_array()` (handles prose wrapping).
- On parse failure, falls back to template.
- Caps output at 3 hypotheses per paper.

**Template mode** (LLM absent or returned unparseable output):
- Generates `factor × asset_class` combinations from `paper.factors_studied × paper.asset_classes`.
- Produces IF/THEN statements in canonical form.
- Confidence score hardcoded at 0.3 (low; researcher must assess).
- Marks `generation_method="template"`.

---

### `QualityFilter` (`quality.py`)

`check_quality(h: HypothesisRecord) → QualityResult(passed, reasons)`

Eight checks applied in sequence. All run; reasons accumulate:

| Check | Rejection code | Threshold |
|---|---|---|
| Statement length | `statement_too_short` | < 20 chars |
| IF/WHEN conditional | `not_testable_no_conditional` | Neither "if " nor "when " present |
| Intuition length | `intuition_missing` | < 10 chars |
| Has datasets | `missing_required_data` | `required_datasets` empty |
| Has asset class | `asset_class_unspecified` | `asset_classes` empty |
| Confidence floor | `confidence_too_low` | < 0.1 |
| Content token count | `too_vague` | < 3 unique non-stopword tokens in statement |
| Circular reasoning | `circular_reasoning` | Statement is substring of intuition |

---

### `DuplicateDetector` (`deduplication.py`)

`check_duplicates(h, existing_statements) → DuplicateResult(status, similar_ids, max_similarity)`

`existing_statements` is `list[(id, testable_statement)]` from `store.all_statements()`.

**Algorithm:** Jaccard similarity on word sets, with domain stopwords removed (including structural words: if, when, then, among, over, returns, positive, negative, high, low, top, bottom).

| Jaccard range | Status | Action |
|---|---|---|
| 1.0 | `DUPLICATE` | Blocked; stored as Rejected |
| ≥ 0.70 | `NEAR_DUPLICATE` | Stored with `similar_to` list; researcher reviews |
| 0.40–0.69 | `VARIATION` | Stored with `similar_to` list; allowed |
| < 0.40 | `UNIQUE` | Stored normally |

No ML dependencies. O(n) per hypothesis check; fast at 10k hypotheses.

---

### `HypothesisStore` (`store.py`)

DuckDB-backed repository at `data/hypothesis.duckdb`.

**Methods:**

| Method | Description |
|---|---|
| `insert(h)` | Insert new record. Returns `True` if new, `False` if ID exists. |
| `update(h)` | Increments `version`, saves snapshot to `hypothesis_versions`, updates record. |
| `get(id)` | Fetch by ID. |
| `search(query, category, status, asset_class, paper_id, method, since, limit)` | Flexible search. |
| `get_by_paper(paper_id)` | All hypotheses referencing a paper. |
| `get_versions(hypothesis_id)` | Full version history as list of dicts. |
| `all_statements()` | `(id, testable_statement)` for all non-rejected hypotheses. Used by dedup. |
| `stats()` | Counts by status, category, method. |

---

## Database Schema

File: `data/hypothesis.duckdb` (gitignored via `data/`)

```sql
CREATE TABLE hypotheses (
    id                      VARCHAR PRIMARY KEY,
    parent_papers           VARCHAR NOT NULL,   -- JSON array
    research_category       VARCHAR,
    economic_intuition      VARCHAR,
    testable_statement      VARCHAR NOT NULL,
    expected_behavior       VARCHAR,
    asset_classes           VARCHAR,            -- JSON array
    required_datasets       VARCHAR,            -- JSON array
    required_features       VARCHAR,            -- JSON array
    holding_period          VARCHAR,
    expected_risks          VARCHAR,            -- JSON array
    confidence_score        DOUBLE,
    assumptions             VARCHAR,            -- JSON array
    dependencies            VARCHAR,            -- JSON array
    validation_requirements VARCHAR,            -- JSON array
    similar_to              VARCHAR,            -- JSON array of hypothesis IDs
    status                  VARCHAR NOT NULL DEFAULT 'Draft',
    version                 INTEGER NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    researcher              VARCHAR NOT NULL,
    generation_method       VARCHAR NOT NULL,   -- llm | template | manual
    rejection_reason        VARCHAR
);

CREATE TABLE hypothesis_versions (
    hypothesis_id   VARCHAR NOT NULL,
    version         INTEGER NOT NULL,
    snapshot        VARCHAR NOT NULL,           -- JSON snapshot of key fields
    changed_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (hypothesis_id, version)
);
```

---

## Folder Structure

```
src/aurelius/hypothesis/
├── __init__.py             # Public API
├── models.py               # HypothesisRecord dataclass
├── store.py                # HypothesisStore (DuckDB)
├── generator.py            # LLM + template generation
├── quality.py              # QualityFilter
└── deduplication.py        # Jaccard-based duplicate detection

scripts/
└── generate_hypotheses.py  # CLI: generate, list, stats subcommands

tests/hypothesis/
├── test_models.py
├── test_store.py
├── test_generator.py       # Mock LLM — no API calls
├── test_quality.py
└── test_deduplication.py
```

---

## Data Flow

```
1. LiteratureStore.search(enriched_only=True)
   └─ Returns Papers with keywords, factors, asset_classes, conclusions populated

2. generate(paper, llm=llm_client)
   ├─ [LLM path] Prompt → JSON array → list[HypothesisRecord]
   └─ [Template path] factors × asset_classes → list[HypothesisRecord]

3. For each candidate:
   a. check_quality(h)
      ├─ Fail → h.status="Rejected", h.rejection_reason set → store.insert(h)
      └─ Pass → continue

   b. check_duplicates(h, store.all_statements())
      ├─ DUPLICATE → h.status="Rejected" → store.insert(h)
      ├─ NEAR_DUPLICATE → h.similar_to=[...] → store.insert(h)
      └─ UNIQUE/VARIATION → store.insert(h)

4. Draft queue accumulates in hypothesis.duckdb
   └─ Researcher reviews, promotes Draft → Active or rejects
```

---

## AI Model Swap — How It Works

The only AI seam is:

```python
LLMClient = Callable[[str], str]   # prompt → completion string
```

The generator, quality filter, and store have zero imports from any AI SDK. Swap the model by passing a different callable:

```python
# Claude (via Anthropic SDK)
import anthropic
client = anthropic.Anthropic()
llm = lambda p: client.messages.create(
    model="claude-haiku-4-5-20251001", max_tokens=2048,
    messages=[{"role": "user", "content": p}]
).content[0].text

# Claude (via raw HTTP — no SDK needed)
import httpx
llm = lambda p: httpx.post("https://api.anthropic.com/v1/messages",
    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2048,
          "messages": [{"role": "user", "content": p}]}
).json()["content"][0]["text"]

# OpenAI
import openai
client = openai.OpenAI()
llm = lambda p: client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": p}]
).choices[0].message.content

# Local Ollama
import httpx
llm = lambda p: httpx.post(
    "http://localhost:11434/api/generate",
    json={"model": "llama3.2", "prompt": p, "stream": False}
).json()["response"]

# No-op (template fallback only)
llm = None
```

Pass `llm=None` to use the template fallback exclusively. The generate function handles all cases.

---

## Lifecycle and Status Transitions

```
                    generate()
                        │
                        ▼
                      Draft ──── quality/dedup fail ──► Rejected
                        │
                   researcher review
                        │
               ┌────────┴────────┐
               │                 │
             Active           Rejected
               │
          run experiment
               │
            Promoted  (links to ResearchStore hypothesis ID)
```

**Promotion to Experiment Framework:**

When a researcher promotes a hypothesis from Draft → Active and decides to run an experiment:

1. Call `ResearchStore.record_hypothesis(h.testable_statement, h.economic_intuition, researcher_name)` — creates entry in `research.duckdb`.
2. Store the returned `Hypothesis.id` in `HypothesisRecord.rejection_reason` (repurposed as `promoted_id`) or add a dedicated field when needed.
3. Set `HypothesisRecord.status = "Promoted"` and call `HypothesisStore.update(h)`.

The two stores remain loosely coupled — no shared schema, no foreign key constraints.

---

## CLI Reference

```bash
# Generate from all enriched arXiv papers (template fallback)
python scripts/generate_hypotheses.py generate --source arxiv --limit 50

# Generate with LLM enrichment
ANTHROPIC_API_KEY=sk-... python scripts/generate_hypotheses.py generate \
    --source arxiv --limit 50

# Generate from a specific paper
python scripts/generate_hypotheses.py generate --paper <paper_id>

# List Draft hypotheses
python scripts/generate_hypotheses.py list --status Draft --limit 20

# List by category
python scripts/generate_hypotheses.py list --category factor_anomaly

# Search by keyword
python scripts/generate_hypotheses.py list --query momentum

# Print repository stats
python scripts/generate_hypotheses.py stats
```

---

## Extension Points

**Custom quality checks:** Add a function to `quality.py` matching signature `(h: HypothesisRecord) -> str | None` (returns rejection code or None), and call it inside `check_quality()`. No other files change.

**Alternative deduplication:** Replace `_jaccard()` with TF-IDF cosine similarity or embedding-based similarity without changing the `check_duplicates()` interface — callers only see `DuplicateResult`.

**Bulk import (manual hypotheses):** Create a `HypothesisRecord` with `generation_method="manual"`, set `researcher` to the human name, call `store.insert()`. Same pipeline.

**Hypothesis ranking:** Add a `priority_score` column to `hypotheses` table (DuckDB ALTER TABLE) and populate via a scoring function on `confidence_score × asset_class_coverage × novelty`. No interface changes needed.
