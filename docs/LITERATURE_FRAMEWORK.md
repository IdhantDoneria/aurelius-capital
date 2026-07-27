# Literature Intelligence Framework

**Phase 11 — Aurelius Capital**

Single source of truth for all external quantitative research. Ingests, stores, and enriches papers from seven academic sources. Feeds the Hypothesis Generation Framework (Phase 12).

---

## Architecture

```
External Sources          Extractors                 Store                 Consumers
─────────────────         ──────────────────         ────────────────────  ───────────────
arXiv q-fin.*    ──────►  ArxivExtractor    ──────►
NBER RSS         ──────►  NBERExtractor     ──────►  LiteratureStore       HypothesisGenerator
Journal of Fin.  ──────►                   ──────►  (literature.duckdb)   ResearchAssistant
JFE              ──────►  CrossRefExtractor ──────►                        Manual search
RFS              ──────►                   ──────►
Quantitative Fin.──────►                   ──────►
SSRN             ──────►                   ──────►

                                                ↑
                                         enrichment.enrich()
                                         (optional LLM step)
```

### Component responsibilities

| Component | File | Responsibility |
|---|---|---|
| `Paper` | `models.py` | Atomic data unit. Raw fields set by extractors; enrichment fields set by `enrich()`. |
| `LiteratureStore` | `store.py` | DuckDB CRUD. Upsert, search, dedup, enrichment-preservation. |
| `SourceExtractor` (ABC) | `extractors/base.py` | Protocol for new sources — implement `fetch()` only. |
| `ArxivExtractor` | `extractors/arxiv.py` | Parses arXiv Atom XML. All q-fin sub-categories. |
| `NBERExtractor` | `extractors/nber.py` | Parses NBER RSS feed. Authors via Dublin Core. |
| `CrossRefExtractor` | `extractors/crossref.py` | CrossRef REST API. Parameterized by journal ISSN or DOI prefix. Covers JF, JFE, RFS, QF, SSRN. |
| `enrich()` | `enrichment.py` | Optional LLM step. Injected `LLMClient = Callable[[str], str]`. Works offline (no-op). |
| `ingest_literature.py` | `scripts/` | CLI entry point. Fetch, enrich, store. |

---

## Data Model

```python
@dataclass
class Paper:
    # Identity (set by extractor)
    id: str               # sha256(source:source_id)[:32] — deterministic, immutable
    source: str           # arxiv | nber | ssrn | jf | jfe | rfs | qf
    source_id: str        # arxiv abs ID / DOI / NBER handle
    title: str
    authors: list[str]
    published_at: date | None
    abstract: str
    url: str
    ingested_at: datetime

    # Enrichment (set by enrich(), empty until then)
    keywords: list[str]
    asset_classes: list[str]      # equities, fixed_income, fx, …
    research_category: str        # factor_anomaly, macro, portfolio_construction, …
    methodology: str              # empirical, theoretical, simulation, …
    datasets: list[str]           # CRSP, Compustat, Bloomberg, …
    factors_studied: list[str]    # momentum, value, quality, …
    statistical_techniques: list[str]
    main_conclusions: str
    limitations: str
    enriched: bool                # False until enrich() runs successfully
```

### paper_id derivation

```python
sha256(f"{source}:{source_id}".encode()).hexdigest()[:32]
```

Deterministic: re-ingesting the same paper produces the same ID. No UUID randomness.

---

## Database Schema

File: `data/literature.duckdb` (gitignored via `data/`)

```sql
CREATE TABLE papers (
    id                     VARCHAR PRIMARY KEY,     -- sha256 hash
    source                 VARCHAR NOT NULL,
    source_id              VARCHAR NOT NULL,
    title                  VARCHAR NOT NULL,
    authors                VARCHAR,                 -- JSON array
    published_at           DATE,
    abstract               VARCHAR,
    url                    VARCHAR,

    -- Enriched fields (NULL until enrich() runs)
    keywords               VARCHAR,                 -- JSON array
    asset_classes          VARCHAR,                 -- JSON array
    research_category      VARCHAR,
    methodology            VARCHAR,
    datasets               VARCHAR,                 -- JSON array
    factors_studied        VARCHAR,                 -- JSON array
    statistical_techniques VARCHAR,                 -- JSON array
    main_conclusions       VARCHAR,
    limitations            VARCHAR,

    ingested_at            TIMESTAMPTZ NOT NULL,
    enriched               BOOLEAN NOT NULL DEFAULT FALSE,

    UNIQUE (source, source_id)
);
```

List fields are stored as JSON arrays (DuckDB has no native array type for VARCHAR).

---

## Folder Structure

```
src/aurelius/literature/
├── __init__.py                 # Public API: Paper, LiteratureStore, LLMClient, enrich
├── models.py                   # Paper dataclass + paper_id()
├── store.py                    # LiteratureStore (DuckDB)
├── enrichment.py               # LLM enrichment (injected client)
└── extractors/
    ├── __init__.py             # Registry: SOURCES, get_extractor()
    ├── base.py                 # SourceExtractor ABC
    ├── arxiv.py                # arXiv Atom API
    ├── nber.py                 # NBER RSS feed
    └── crossref.py             # CrossRef REST API (JF/JFE/RFS/QF/SSRN)

scripts/
└── ingest_literature.py        # CLI ingestion tool

tests/literature/
├── test_models.py
├── test_store.py
├── test_extractors.py          # Offline — tests parsers with fixture XML/JSON
└── test_enrichment.py          # Mock LLM — no API calls
```

---

## Ingestion Workflow

```
1. CLI calls get_extractor(source).fetch(limit, since)
   └─ Returns list[Paper] with enrichment fields empty

2. For each Paper:
   a. store.exists(source, source_id) → skip if already known
   b. enrich(paper, llm) if --enrich flag set (optional)
   c. store.upsert(paper) → INSERT new record

3. Re-ingest semantics:
   - Existing enriched paper + unenriched ingest → enrichment preserved (metadata-only UPDATE)
   - Existing enriched paper + enriched ingest → full overwrite (re-enrichment)
```

---

## Source Coverage

| Source | Key | API / Feed | Auth | Full-text |
|---|---|---|---|---|
| arXiv q-fin.* | `arxiv` | Atom REST | None | Abstract |
| NBER Working Papers | `nber` | RSS | None | Abstract |
| Journal of Finance | `jf` | CrossRef REST (ISSN 0022-1082) | None | Abstract (when deposited) |
| Journal of Financial Economics | `jfe` | CrossRef REST (ISSN 0304-405X) | None | Abstract |
| Review of Financial Studies | `rfs` | CrossRef REST (ISSN 0893-9454) | None | Abstract |
| Quantitative Finance | `qf` | CrossRef REST (ISSN 1469-7688) | None | Abstract |
| SSRN | `ssrn` | CrossRef REST (prefix 10.2139) | None | Abstract |

arXiv and NBER return recent papers only (RSS/API window). CrossRef returns full journal history filterable by date.

---

## LLM Enrichment

The `enrich()` function follows the same `LLMClient = Callable[[str], str]` pattern as `aurelius.assistant`.

```python
# Offline (no LLM)
store.upsert(paper)                     # enriched=False

# With any LLM
from aurelius.literature import enrich
paper = enrich(paper, llm=my_llm_client)
store.upsert(paper)                     # enriched=True, all fields populated
```

To wire Claude via the Anthropic SDK:

```python
import anthropic
client = anthropic.Anthropic()
llm = lambda prompt: client.messages.create(
    model="claude-haiku-4-5-20251001", max_tokens=1024,
    messages=[{"role": "user", "content": prompt}]
).content[0].text
```

The prompt requests JSON. `_extract_json()` strips prose wrapping. On parse failure, `enrich()` returns the paper unchanged (`enriched=False`).

---

## Error Handling

| Error type | Behavior |
|---|---|
| HTTP error on fetch | `raise_for_status()` propagates; CLI prints and continues next source |
| Malformed XML/JSON item | Logged as warning; item skipped; rest of batch proceeds |
| LLM returns non-JSON | `enrich()` returns paper unchanged; `enriched` stays False |
| DB write error | DuckDB exception propagates to caller |
| Missing `data/` directory | `LiteratureStore.__init__` creates it via `Path.mkdir(parents=True)` |

---

## CLI Reference

```bash
# Ingest 100 latest arXiv q-fin papers
python scripts/ingest_literature.py --source arxiv --limit 100

# Ingest all sources since Jan 2024
python scripts/ingest_literature.py --source all --since 2024-01-01

# Ingest top journals and enrich with LLM
ANTHROPIC_API_KEY=sk-... python scripts/ingest_literature.py \
    --source jf jfe rfs --limit 50 --enrich

# Print DB stats
python scripts/ingest_literature.py --stats
```

---

## Extension Points

**Adding a new source:**

1. Create `src/aurelius/literature/extractors/newjournal.py`
2. Subclass `SourceExtractor`, set `source = "newjournal"`, implement `fetch()`
3. Add to `extractors/__init__.py` registry (`SOURCES` list and `get_extractor` match)
4. No other files change.

**Alternative enrichment backends:**

The `LLMClient = Callable[[str], str]` seam accepts any callable. Wire GPT-4, Llama, or a local model without touching `enrich()`:

```python
# OpenAI
import openai
client = openai.OpenAI()
llm = lambda p: client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": p}]
).choices[0].message.content

enrich(paper, llm)
```

**Scheduled ingestion:**

Not built (YAGNI). When needed: wrap `ingest_literature.py` in a cron job or `CronCreate` task.

**Full-text indexing:**

Current: abstract-only. When PDF volume justifies: replace `abstract` population in extractors with a PDF fetcher + text extractor. `Paper.abstract` field stays the same; downstream consumers see no change.
