# Market-Data Ingestion Spec — CSVLoader → DuckDBStore

Canonical schema the batch loader (`market_data/adapters/csv_loader.py`) accepts,
and where the data lands. Drop a vendor CSV matching this and the momentum
experiment runs unchanged.

## Required columns

`CSVLoader` requires these six (case-insensitive; aliases accepted). `symbol`
is required in-file **or** passed as `default_symbol`.

| Field | Required | Aliases | Notes |
|---|---|---|---|
| `symbol` | yes* | `ticker` | uppercased on load |
| `timestamp` | yes | `date`, `datetime`, `time` | see formats below |
| `open` | yes | `o` | Decimal |
| `high` | yes | `h` | Decimal |
| `low` | yes | `l` | Decimal |
| `close` | yes | `c`, `adj close`, `adjusted_close` | **adjusted** close preferred |
| `volume` | yes | `vol`, `v` | Decimal |
| `vwap` | no | — | optional |
| `trade_count` | no | `trades`, `n` | optional int |

\* required in-file unless `default_symbol` supplied to `load_file()`.

## File format

- UTF-8 (BOM tolerated), standard CSV, header row required.
- One row per (symbol, bar). Daily bars = `frequency="1d"` (passed to loader; not
  inferable from the file).
- Non-numeric / unparseable rows are skipped and counted, not fatal.

## Directory

- Sample: `data/market_data/sample_momentum_universe.csv`
- Analytical store (destination): `data/analytics.duckdb`, table `ohlcv`,
  PK `(symbol, timestamp, frequency)`, `INSERT OR REPLACE` (idempotent re-load).
- Write path is bulk (DataFrame register + `INSERT OR REPLACE ... SELECT`),
  ~256k rows/sec measured — 37.8M rows (5000×30y) loads in ~2.5min. Benchmark +
  scale/validation evidence: `docs/DATA_READINESS_REPORT.md`.

## Date format

Accepted `timestamp` formats (`csv_loader._TS_FORMATS`):
`YYYY-MM-DDTHH:MM:SS±ZZ`, `...Z`, `...`, `YYYY-MM-DD HH:MM:SS`, **`YYYY-MM-DD`**,
`MM/DD/YYYY`, `DD/MM/YYYY`. Naive timestamps are assumed **UTC**.

## Ticker format

Free-form in-file; normalized to **UPPERCASE**. Must match the strategy universe.

## Corporate-action expectations

- Loader/store apply **no** corporate-action adjustment; `adjustment_factor`
  defaults to `1.0`. Supply **already-adjusted** close (split + dividend) so
  momentum returns are not corrupted by raw-price jumps.
- Ingestion validates OHLC relationships and positive prices; a raw (unadjusted)
  split day can trip validation or inject a false momentum signal.

## Known limitations / Skipped

**Data source is synthetic.**
- *Reason (impossibility):* real vendor history (CRSP/Compustat/Yahoo) is
  network/paywall-blocked from this environment — confirmed in
  `docs/paper_ingestion_2026-07-30.md`. No live adapter can reach it here.
- *Unblock:* replace `sample_momentum_universe.csv` with a real adjusted-OHLCV
  CSV of the schema above (or restore network for the `yahoo`/`alpaca` adapter).
  Loader → store → experiment path needs no change.
