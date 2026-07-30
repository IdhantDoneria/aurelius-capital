# Research Corpus & Institutional Knowledge Acquisition System — Phase 19

The Aurelius Capital Research Corpus Management System continuously acquires, classifies, versions, and indexes quantitative finance literature, serving as the firm's permanent institutional research library.

---

## 1. System Architecture

```
Academic Papers / Books / Preprints / Blogs
                      │
                      ▼
            [ Automated Classifier ]  ──▶ 9-Dimension Classification
                      │
                      ▼
            [ Multi-Version Store ]  ──▶ Original, Knowledge, Summary, Hypothesis, Feature, Experiment
                      │
                      ▼
            [ Citation Graph ]        ──▶ Literature ──▶ Hypothesis ──▶ Experiment ──▶ Production Strategy
                      │
                      ▼
            [ DuckDB Corpus Store ]   ──▶ ./data/corpus.duckdb + KnowledgeGraph Sync
                      │
                      ▼
            [ Semantic Hybrid Search] ──▶ Vector Embeddings (MiniLM) + BM25 Natural Language Search
                      │
                      ▼
            [ FastAPI Router ]        ──▶ /corpus/* REST Endpoints
```

---

## 2. Hierarchical Taxonomy

The quantitative finance taxonomy (`taxonomy.py`) covers 16+ core research domains:

1. **Market Microstructure**: Order book dynamics, LOB modeling, bid-ask spread, Almgren-Chriss market impact, VPIN flow toxicity, dark pools, high-frequency alpha.
2. **Statistical Methodology**: Time series, cointegration, Kalman filtering, GARCH, copulas, extreme value theory, change-point detection.
3. **Econometrics**: Panel data, structural break detection, VAR/VECM, multi-factor models, instrumental variables, Markov switching.
4. **Machine Learning & AI**: Deep learning, reinforcement learning, NLP sentiment, gradient boosting (XGBoost/LightGBM), feature selection, autoencoders.
5. **Optimization**: Convex optimization, quadratic programming, stochastic control, mean-variance-skewness, genetic algorithms, robust optimization.
6. **Portfolio Theory**: Mean-variance, Black-Litterman, risk parity/budgeting, factor tilting, target volatility, dynamic asset allocation.
7. **Risk Management**: VaR, Expected Shortfall (CVaR), stress testing, drawdown control, liquidity risk, model risk validation.
8. **Alternative Data**: Satellite imagery, web scraping, credit card transactions, supply chain logistics, patent analytics, social media sentiment.
9. **Economic & Macro Research**: Macroeconomic indicators, monetary policy, yield curve (Nelson-Siegel), inflation forecasting, nowcasting.
10. **Behavioral Finance**: Prospect theory, disposition effect, investor sentiment, herding, market anomalies.
11. **Execution Research**: Optimal execution, TWAP/VWAP optimization, smart order routing (SOR), transaction cost analysis (TCA).
12. **Academic Papers**: Peer-reviewed literature (Journal of Finance, Review of Financial Studies, JFE).
13. **Books & Manuscripts**: Monograph and textbook quantitative finance references.
14. **Conference Proceedings**: QWAFAFEW, ICAIF, NeurIPS Finance, SIAM.
15. **Working Papers**: Preprints from SSRN, NBER, arXiv.
16. **Research Blogs**: Practitioner research from AQR, Man Group, Quantpedia.

---

## 3. Storage & Database Schema (`./data/corpus.duckdb`)

### `corpus_documents`

| Column | Type | Description |
|---|---|---|
| `id` | VARCHAR PK | Document identifier (`doc_...`) |
| `title` | VARCHAR | Document title |
| `doc_type` | VARCHAR | Document type from taxonomy |
| `authors` | VARCHAR | JSON array of author names |
| `publication_date` | VARCHAR | Publication date |
| `venue` | VARCHAR | Journal, publisher, or venue |
| `doi` | VARCHAR | Digital Object Identifier |
| `abstract` | VARCHAR | Summary abstract |
| `full_text_url` | VARCHAR | URL or file link |
| `classification` | JSON | 9-dimension classification payload |
| `current_version` | INTEGER | Active version number |
| `metadata` | JSON | Arbitrary document metadata |
| `created_at` | TIMESTAMPTZ | Ingestion timestamp |
| `updated_at` | TIMESTAMPTZ | Modification timestamp |

### `corpus_versions`

| Column | Type | Description |
|---|---|---|
| `id` | VARCHAR | Version ID (`ver_...`) |
| `doc_id` | VARCHAR | FK $\to$ `corpus_documents.id` |
| `version_num` | INTEGER | Incremental version number (1, 2, ...) |
| `version_type` | VARCHAR | `original`, `extracted_knowledge`, `summary`, `generated_hypothesis`, `derived_feature`, `experiment_reference` |
| `title` | VARCHAR | Version title |
| `content` | VARCHAR | Text payload |
| `metadata` | JSON | Version metadata |
| `created_at` | TIMESTAMPTZ | Timestamp |
| `created_by` | VARCHAR | Author/system |
| `parent_version_id` | VARCHAR | Parent version for diff lineage |
| `diff_summary` | VARCHAR | Summary of changes |

*PRIMARY KEY*: `(doc_id, version_num)`

### `corpus_citations`

| Column | Type | Description |
|---|---|---|
| `id` | VARCHAR PK | Edge ID (`cite_...`) |
| `source_id` | VARCHAR | Source entity ID |
| `target_id` | VARCHAR | Target cited entity ID |
| `edge_type` | VARCHAR | `hypothesis_origin`, `experiment_cite`, `strategy_support`, `paper_reference` |
| `description` | VARCHAR | Edge description |
| `created_at` | TIMESTAMPTZ | Timestamp |

---

## 4. Multi-Dimensional Automated Classifier

Every document is automatically scored across 9 dimensions:
- **Research domain**: Matched against 16 core domains via keyword density.
- **Asset class**: Equity, FX, Fixed Income, Commodity, Crypto, Derivative, Multi-Asset.
- **Methodology**: Theoretical, Empirical, Simulation, Backtest, Machine Learning.
- **Statistical methods**: OLS, GARCH, Kalman Filter, Cointegration, Copula, XGBoost, etc.
- **Markets**: US Equities, Global FX, Treasuries, Crypto Perpetuals, Volatility, High Frequency.
- **Factors**: Value, Momentum, Quality, Low Volatility, Size, Carry, Liquidity, Trend, Growth, Reversal.
- **Difficulty**: Scale 1 (introductory) to 5 (stochastic calculus, proof-heavy).
- **Novelty**: Scale 1 (standard benchmark) to 5 (groundbreaking methodology).
- **Research Quality Score**: Scale 0–100 calculated from venue prestige, empirical rigor, and stat method density.

---

## 5. Document Versioning

Supports 6 version artifact types:
1. `ORIGINAL`: Raw paper text or original manuscript.
2. `EXTRACTED_KNOWLEDGE`: Structured facts, parameters, and equations.
3. `SUMMARY`: Concise executive summary.
4. `GENERATED_HYPOTHESIS`: Concrete testable trading hypothesis derived from the literature.
5. `DERIVED_FEATURE`: Mathematical feature/alpha formula definition.
6. `EXPERIMENT_REFERENCE`: Empirical validation test result link.

---

## 6. Citation Tracking & Provenance

The platform tracks complete intellectual lineage:
- **Hypothesis Origin**: `get_hypothesis_origin(hypothesis_id)` $\to$ returns originating paper(s).
- **Experiment Citations**: `get_experiment_citations(experiment_id)` $\to$ returns cited literature.
- **Strategy Support**: `get_strategy_supporting_literature(strategy_id)` $\to$ traces backward from production strategy $\to$ experiment $\to$ hypothesis $\to$ academic literature.

---

## 7. Search APIs & Endpoints (`/corpus/*`)

- `GET /corpus/taxonomy` — Retrieve taxonomy tree, factors, and statistical methods.
- `POST /corpus/documents` — Acquire document into corpus with auto-classification.
- `GET /corpus/documents` — List corpus documents (supports domain filter).
- `GET /corpus/documents/{doc_id}` — Get document with full version history.
- `POST /corpus/documents/{doc_id}/versions` — Append new version artifact.
- `POST /corpus/documents/classify` — Classify text without storing.
- `POST /corpus/citations` — Add citation edge.
- `GET /corpus/provenance/{target_id}` — Retrieve full literature provenance report.
- `GET /corpus/search` — Natural language semantic & hybrid search (`query`, `domain`, `asset_class`, `min_quality`).

---

## 8. Extension Points

- **External Extractor Hooks**: Wire automated fetchers (arXiv, SSRN, CrossRef, NBER) directly into `store.add_document()`.
- **Knowledge Graph Integration**: Automatically syncs every corpus node and citation edge to `KnowledgeGraph` (`./data/knowledge_graph.duckdb`).
- **Embedding Models**: Soft dependency on `sentence-transformers` (`all-MiniLM-L6-v2`) with graceful fallback to term frequency vector representations.
