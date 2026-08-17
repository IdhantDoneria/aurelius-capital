#!/bin/bash
set -e
PROJ=/Users/idhantdoneria/mentisrex-capital
PY=$PROJ/.venv/bin/python
LOG=$PROJ/logs/post_ingest_merge.log

echo "[$(date)] Starting post-ingest merge" >> "$LOG"

# 1. Merge NSE staging into analytics
echo "[$(date)] Merging NSE staging into analytics.duckdb..." >> "$LOG"
$PY -c "
import duckdb
con = duckdb.connect('$PROJ/data/analytics.duckdb')
con.execute(\"ATTACH '$PROJ/data/nse_staging.duckdb' AS nse\")
con.execute('INSERT OR IGNORE INTO ohlcv SELECT * FROM nse.ohlcv')
n = con.execute('SELECT changes()').fetchone()[0]
con.execute('DETACH nse')
con.close()
print(f'Merged {n} NSE rows into analytics.duckdb')
" >> "$LOG" 2>&1

# 2. Load EDGAR Form 15 delistings into store + apply to SecurityMaster
echo "[$(date)] Loading EDGAR delistings..." >> "$LOG"
$PY $PROJ/scripts/backfill_delistings.py \
  --file $PROJ/data/edgar_delistings.csv \
  --vendor sec_edgar \
  --apply \
  --db $PROJ/data/delistings.duckdb \
  --identity-db $PROJ/data/identity.duckdb >> "$LOG" 2>&1

echo "[$(date)] Post-ingest merge complete." >> "$LOG"
