"""Backfill the Security Master from existing price stores (AIDP Phase 2 migration).

Non-breaking: reads distinct tickers (and their first observed date) from an
existing DuckDB store and registers one security per (ticker, exchange), opening
an identity interval from the first date. Idempotent — safe to re-run.

Existing ticker-keyed research keeps working; it can now resolve ticker→security_id
as-of any date via SecurityMaster. Enrichment with ISIN/CUSIP/FIGI from the
Postgres Symbol table is optional and skipped if that DB is unreachable.

Usage:
    python scripts/backfill_security_master.py --source data/analytics.duckdb --table raw_ohlcv
    python scripts/backfill_security_master.py --source data/analytics.duckdb --table ohlcv --exchange XNAS
"""

from __future__ import annotations

import argparse
from datetime import date

import duckdb

from aurelius.market_data.identity import Security, SecurityMaster, make_security_id


def backfill(source_db: str, table: str, identity_db: str, exchange: str) -> int:
    conn = duckdb.connect(source_db, read_only=True)
    try:
        rows = conn.execute(
            f"SELECT symbol, MIN(CAST(timestamp AS DATE)) FROM {table} GROUP BY symbol"
        ).fetchall()
    finally:
        conn.close()

    sm = SecurityMaster(identity_db)
    n = 0
    try:
        for ticker, first in rows:
            first = first or date(1970, 1, 1)
            sid = make_security_id(isin=None, figi=None, ticker=ticker, exchange=exchange, first_date=first)
            sm.register(
                Security(security_id=sid, ticker=ticker.upper(), exchange=exchange,
                         asset_type="equity", status="active"),
                valid_from=first, reason="backfill", source=f"{source_db}:{table}",
            )
            n += 1
    finally:
        sm.close()
    return n


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, help="existing DuckDB store")
    p.add_argument("--table", default="raw_ohlcv")
    p.add_argument("--identity-db", default="./data/identity.duckdb")
    p.add_argument("--exchange", default="XNAS", help="default listing exchange for backfilled symbols")
    args = p.parse_args()
    count = backfill(args.source, args.table, args.identity_db, args.exchange)
    print(f"registered {count} securities into {args.identity_db}")


if __name__ == "__main__":
    main()
