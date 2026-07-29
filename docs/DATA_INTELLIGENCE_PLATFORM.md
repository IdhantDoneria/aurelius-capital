# Phase 22: Institutional Data Intelligence Platform

## Overview

The Data Intelligence Platform treats every dataset used by the research organization as a first-class institutional asset. It manages the complete data lifecycle: discovery, ingestion registration, quality validation, versioning, lineage tracking, governance, and monitoring.

**Core guarantee:** Every research result can be traced to the exact dataset version that produced it.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Data Intelligence Platform                      │
│                   src/aurelius/catalog/                          │
├──────────────┬──────────────┬──────────────┬────────────────────┤
│  CatalogStore│ QualityEngine│LineageTracker│  VersionManager    │
│  (DuckDB)    │  (6 checks)  │ (edge graph) │  (content hash)    │
├──────────────┴──────────────┴──────────────┴────────────────────┤
│          GovernanceManager          HealthMonitor                │
│        (access/retention/audit)   (fleet dashboard)             │
├─────────────────────────────────────────────────────────────────┤
│                    FastAPI /catalog/* router                     │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
   data/catalog.duckdb  (5 tables, auto-created on startup)
```

**Storage:** Single DuckDB file `data/catalog.duckdb`. Path configurable via `CATALOG_PATH` env var (default `./data/catalog.duckdb`).

**Startup:** `CatalogStore.bootstrap()` is called on application startup (in `main.py` lifespan). It registers 7 built-in datasets representing the existing DuckDB stores if they are not already present.

---

## Module Structure

```
src/aurelius/catalog/
├── __init__.py       — public exports
├── models.py         — Pydantic models (DatasetRecord, DataVersion, LineageEdge, QualityReport, GovernanceRecord, DatasetHealth)
├── store.py          — DuckDB persistence layer (CatalogStore)
├── quality.py        — QualityEngine (6 validation dimensions)
├── lineage.py        — LineageTracker (provenance graph)
├── versioning.py     — VersionManager (content snapshots)
├── governance.py     — GovernanceManager (audit trail, retention, deprecation)
├── monitor.py        — HealthMonitor (fleet health reports)
└── api.py            — FastAPI router (catalog_router, prefix /catalog)
```

---

## Database Schemas (catalog.duckdb)

### `datasets` — Data Catalog

| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR PK | Unique dataset identifier (e.g. `ohlcv_daily_us_equity`) |
| name | VARCHAR | Human-readable name |
| source | VARCHAR | Data source (yahoo, alpaca, nber, internal, ...) |
| asset_class | VARCHAR | equity, fixed_income, macro, all, ... |
| frequency | VARCHAR | daily, 1min, tick, on-demand |
| coverage | JSON | `{start, end, symbols}` |
| schema_def | JSON | `{col_name: type}` — registered schema for drift detection |
| update_freq | VARCHAR | Expected update cadence |
| license | VARCHAR | Data license or terms |
| quality_score | DOUBLE | 0–100, updated after each quality run |
| owner | VARCHAR | Responsible team or researcher |
| dependencies | JSON | List of dataset IDs this dataset depends on |
| tags | JSON | Free-form tags for discovery |
| description | TEXT | Description |
| created_at | TIMESTAMPTZ | Registration timestamp |
| updated_at | TIMESTAMPTZ | Last modification timestamp |
| status | VARCHAR | active \| deprecated \| replaced |

### `dataset_versions` — Version Control

| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR PK | Version record ID |
| dataset_id | VARCHAR | FK → datasets.id |
| version | VARCHAR | Timestamp-based version string (YYYYMMDD_HHMMSS) |
| snapshot_meta | JSON | row_count, schema, coverage_start, coverage_end |
| row_hash | VARCHAR | SHA-256 of 1000-row sample — content fingerprint |
| created_at | TIMESTAMPTZ | Snapshot timestamp |
| created_by | VARCHAR | Actor who triggered snapshot |
| notes | TEXT | Optional snapshot notes |

### `lineage_edges` — Data Lineage

| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR PK | Edge ID |
| source_id | VARCHAR | Source entity ID |
| source_type | VARCHAR | dataset \| feature \| experiment \| strategy \| paper |
| target_id | VARCHAR | Target entity ID |
| target_type | VARCHAR | dataset \| feature \| experiment \| strategy \| paper |
| rel_type | VARCHAR | feeds \| used_by \| produces \| referenced_by |
| metadata | JSON | Optional context |
| created_at | TIMESTAMPTZ | Edge creation time |

### `quality_reports` — Quality History

| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR PK | Report ID |
| dataset_id | VARCHAR | FK → datasets.id |
| checked_at | TIMESTAMPTZ | Check timestamp |
| missing_pct | DOUBLE | Average null % across value columns |
| duplicate_count | INTEGER | Duplicate (symbol, date) pairs |
| timestamp_gaps | INTEGER | Gaps > 4 calendar days in date sequence |
| outlier_count | INTEGER | Z-score > 5 outliers across up to 3 columns |
| schema_drift | BOOLEAN | True if current schema missing registered columns |
| feed_delayed | BOOLEAN | True if max(date) older than freshness threshold |
| overall_score | DOUBLE | 0–100 composite score |
| details | JSON | Per-check detail values |
| passed | BOOLEAN | overall_score >= 70 |

### `governance_log` — Audit Trail

| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR PK | Log entry ID |
| dataset_id | VARCHAR | FK → datasets.id |
| action | VARCHAR | access \| deprecate \| replace \| policy_change |
| actor | VARCHAR | User or system that performed the action |
| details | JSON | Action-specific context |
| retention_days | INTEGER | Retention policy (for policy_change actions) |
| logged_at | TIMESTAMPTZ | Event timestamp |

---

## Part 1 — Data Catalog (CatalogStore)

Searchable registry of every dataset. All research systems register their datasets here.

**Key operations:**
```python
from aurelius.catalog import CatalogStore, DatasetRecord

store = CatalogStore()
store.register(DatasetRecord(
    id="ohlcv_daily_us_equity",
    name="OHLCV Daily US Equity",
    source="yahoo",
    asset_class="equity",
    frequency="daily",
    schema_def={"symbol": "VARCHAR", "timestamp": "TIMESTAMPTZ", "close": "DECIMAL"},
    owner="data-team",
    tags=["market-data", "ohlcv"],
))

ds = store.get("ohlcv_daily_us_equity")
results = store.search("equity")
all_yahoo = store.list_datasets(source="yahoo")
```

---

## Part 2 — Data Lineage (LineageTracker)

Records provenance edges between datasets, features, experiments, strategies, and papers.

**Edge types:**

| rel_type | Meaning |
|----------|---------|
| feeds | dataset → feature (raw data used to compute feature) |
| used_by | feature → experiment (feature consumed by experiment) |
| produces | experiment → strategy (experiment validates a strategy) |
| referenced_by | paper → dataset (paper cites dataset) |

**Usage:**
```python
from aurelius.catalog import LineageTracker, CatalogStore

tracker = LineageTracker(CatalogStore())

# Record that OHLCV data feeds into momentum feature
tracker.dataset_feeds_feature("ohlcv_daily_us_equity", "momentum_12_1")

# Record that momentum feature is used by experiment 001
tracker.feature_used_by_experiment("momentum_12_1", "exp_2026_001")

# Impact analysis: what breaks if ohlcv_daily_us_equity changes?
impact = tracker.impact_analysis("ohlcv_daily_us_equity")
# → {"downstream": [{"id": "momentum_12_1", "type": "feature", ...}], ...}
```

---

## Part 3 — Data Quality Engine (QualityEngine)

Validates any DuckDB-backed table across 6 dimensions. Saves reports and updates the dataset quality score.

**Quality dimensions and penalty weights:**

| Check | Max Penalty | Logic |
|-------|-------------|-------|
| Missing values | 30 pts | `avg_null_pct * 0.3` |
| Duplicates | 20 pts | `log(1 + dupe_count) * 2` |
| Timestamp gaps | 20 pts | `gap_count * 2` (gaps > 4 calendar days) |
| Outliers | 10 pts | `log(1 + outlier_count)` (Z-score > 5) |
| Schema drift | 10 pts | Binary: missing registered columns |
| Feed delay | 10 pts | Binary: max(date) older than freshness threshold |

**Score:** `max(0, 100 - total_penalty)`. `passed = score >= 70`.

**Usage:**
```python
from aurelius.catalog import QualityEngine, CatalogStore

engine = QualityEngine(CatalogStore())
report = engine.run(
    dataset,
    db_path="./data/analytics.duckdb",
    table="ohlcv",
    date_col="timestamp",
    symbol_col="symbol",
    freshness_days=1,
)
# report.overall_score, report.passed, report.details
```

---

## Part 4 — Version Control (VersionManager)

Snapshots dataset state: row count, schema, coverage dates, and SHA-256 content fingerprint.

**Reproducibility protocol:** Before each experiment, call `VersionManager.snapshot()`. Store the version ID in the experiment record. To reproduce, call `find_by_hash()` with the stored hash to locate the exact version.

```python
from aurelius.catalog import VersionManager, CatalogStore

vm = VersionManager(CatalogStore())
v = vm.snapshot(
    "ohlcv_daily_us_equity",
    db_path="./data/analytics.duckdb",
    table="ohlcv",
    created_by="experiment_runner",
    notes="Pre-experiment snapshot for exp_2026_001",
)
# v.row_hash → store this in ExperimentRecord

# Later: reproduce by looking up the version
version = vm.find_by_hash("ohlcv_daily_us_equity", stored_hash)
```

---

## Part 5 — Data Governance (GovernanceManager)

Immutable audit log for every dataset event.

```python
from aurelius.catalog import GovernanceManager, CatalogStore

gov = GovernanceManager(CatalogStore())

# Log access
gov.log_access("ohlcv_daily_us_equity", actor="researcher_a", purpose="backtest")

# Set retention policy
gov.set_retention("ohlcv_daily_us_equity", actor="admin", retention_days=2555)  # 7 years

# Deprecate and replace
gov.deprecate("ohlcv_v1", actor="admin", reason="Adjusted prices supersede raw", replaced_by="ohlcv_v2")
```

---

## Part 6 — Monitoring (HealthMonitor)

Fleet-level health aggregation across all registered datasets.

```python
from aurelius.catalog import HealthMonitor, CatalogStore

monitor = HealthMonitor(CatalogStore())
report = monitor.generate_report()
# {
#   "generated_at": "...",
#   "total_datasets": 7,
#   "active": 7,
#   "deprecated": 0,
#   "delayed_feeds": 1,
#   "avg_quality_score": 82.3,
#   "datasets_below_70": 0,
#   "datasets": [...]
# }
```

---

## Part 7 — API Endpoints

All endpoints are under `/catalog`. Mounted automatically on startup.

### Dataset Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/catalog/datasets` | List datasets (filter: source, asset_class, status) |
| POST | `/catalog/datasets` | Register new dataset |
| GET | `/catalog/datasets/{id}` | Get dataset by ID |
| PUT | `/catalog/datasets/{id}` | Update dataset metadata |

### Lineage

| Method | Path | Description |
|--------|------|-------------|
| GET | `/catalog/datasets/{id}/lineage` | Full impact analysis for dataset |
| POST | `/catalog/lineage` | Record a new lineage edge |

### Versions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/catalog/datasets/{id}/versions` | Version history |
| POST | `/catalog/datasets/{id}/snapshot` | Trigger a version snapshot |

### Quality

| Method | Path | Description |
|--------|------|-------------|
| POST | `/catalog/datasets/{id}/quality` | Run quality check against a DuckDB table |

### Governance

| Method | Path | Description |
|--------|------|-------------|
| GET | `/catalog/datasets/{id}/governance` | Audit log |
| POST | `/catalog/datasets/{id}/deprecate` | Deprecate dataset |

### Monitoring

| Method | Path | Description |
|--------|------|-------------|
| GET | `/catalog/health` | Fleet health report |
| GET | `/catalog/search?q=` | Full-text search across catalog |

---

## Built-in Datasets (Auto-Registered on Startup)

| ID | Name | Source |
|----|------|--------|
| `corpus_papers` | Research Corpus | internal |
| `hypothesis_store` | Hypothesis Store | internal |
| `knowledge_graph` | Knowledge Graph | internal |
| `literature_papers` | Literature Store | arxiv/nber/crossref |
| `research_experiments` | Research Experiments | internal |
| `paper_trading_outcomes` | Paper Trading Outcomes | internal |
| `ohlcv_daily_market` | OHLCV Daily Market Data | yahoo/alpaca |

---

## Extension Points

1. **New quality checks:** Add a `_check_*` static method to `QualityEngine` and include its penalty in `_score()`.
2. **New lineage edge types:** Add a helper method to `LineageTracker` (e.g. `feature_produces_factor`).
3. **New built-in datasets:** Add `DatasetRecord` entries to `_BUILTIN_DATASETS` in `store.py`.
4. **External catalog sync:** Implement an adapter that calls `CatalogStore.register()` for entries discovered via external data catalogs.

## Known Limitations

- **Version content hash uses sampling (1000 rows):** For exact byte-for-byte reproducibility, set `_SAMPLE_ROWS` in `versioning.py` to a full scan (`SELECT *`). Skipped because sampling is sufficient for detecting data changes and avoids OOM on large tables.
- **Quality outlier check capped at 3 columns:** Performance. Extend `_check_outliers` to accept `max_cols` parameter if full-table outlier coverage is required.
- **No automatic quality scheduling:** Quality checks are triggered on-demand via API or caller code. Add a cron job or lab supervisor hook if continuous automated monitoring is needed.
