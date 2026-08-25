"""Build a point-in-time, survivorship-aware tradable universe.

Ranking is done on a monthly grid using only information available on the
ranking date (trailing 60-session median dollar volume, price, history
length). Membership then persists for the following calendar month, so a
name is never in the universe on the strength of liquidity it only acquired
later.

Because the symbol pool comes from Alpaca's *inactive* asset list as well as
the active one, names that were liquid in 2019 and delisted in 2021 are in
the 2019 universe. They leave it when their bars stop, not when a
present-day screen drops them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path("/Users/idhantdoneria/mentisrex-capital")
DATA = ROOT / "data" / "intraday"

SQL = """
CREATE OR REPLACE TABLE daily AS
SELECT
    symbol,
    CAST(ts AT TIME ZONE 'America/New_York' AS DATE) AS d,
    open, high, low, close, volume, vwap, trades
FROM parquet_scan($glob)
WHERE close > 0 AND volume > 0;

-- trailing stats, strictly backward-looking (window ends on the row itself,
-- and the ranking grid below only ever reads a row dated <= the rank date)
CREATE OR REPLACE TABLE daily_stats AS
SELECT
    symbol, d, close, volume,
    close * volume AS dollar_volume,
    median(close * volume) OVER w60 AS addv60,
    count(*)          OVER wall AS n_hist,
    stddev_samp(ln(close / lag_close)) OVER w60 AS vol60
FROM (
    SELECT *, lag(close) OVER (PARTITION BY symbol ORDER BY d) AS lag_close
    FROM daily
)
WHERE lag_close IS NOT NULL
WINDOW
  w60  AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
  wall AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);

-- monthly ranking dates = last session of each month
CREATE OR REPLACE TABLE rank_dates AS
SELECT max(d) AS rank_date FROM daily GROUP BY date_trunc('month', d);

CREATE OR REPLACE TABLE ranked AS
SELECT
    r.rank_date,
    s.symbol,
    s.close,
    s.addv60,
    s.vol60,
    row_number() OVER (PARTITION BY r.rank_date ORDER BY s.addv60 DESC) AS liq_rank
FROM rank_dates r
JOIN daily_stats s ON s.d = r.rank_date
WHERE s.close >= $min_price
  AND s.addv60 >= $min_addv
  AND s.n_hist >= $min_hist;

-- membership spans the month FOLLOWING the ranking date
CREATE OR REPLACE TABLE universe AS
SELECT
    rank_date,
    lead(rank_date) OVER (PARTITION BY symbol ORDER BY rank_date) AS next_rank_date,
    symbol, liq_rank, addv60, vol60, close AS rank_close,
    CASE WHEN liq_rank <= $n_core THEN 'core' ELSE 'wide' END AS tier
FROM ranked
WHERE liq_rank <= $n_wide;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily-glob", default=str(DATA / "daily" / "*.parquet"))
    ap.add_argument("--min-price", type=float, default=5.0)
    ap.add_argument("--min-addv", type=float, default=5_000_000.0)
    ap.add_argument("--min-hist", type=int, default=120)
    ap.add_argument("--n-core", type=int, default=500)
    ap.add_argument("--n-wide", type=int, default=1000)
    ap.add_argument("--out", default=str(DATA / "universe.parquet"))
    args = ap.parse_args()

    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    sql = (
        SQL.replace("$glob", f"'{args.daily_glob}'")
        .replace("$min_price", str(args.min_price))
        .replace("$min_addv", str(args.min_addv))
        .replace("$min_hist", str(args.min_hist))
        .replace("$n_core", str(args.n_core))
        .replace("$n_wide", str(args.n_wide))
    )
    for stmt in [x for x in sql.split(";") if x.strip()]:
        con.execute(stmt)

    print(con.execute("SELECT count(*) AS n_rows, count(DISTINCT symbol) AS n_syms, min(d) AS d_min, max(d) AS d_max FROM daily").fetchdf().to_string())
    print()
    print("universe members per rank date (sample):")
    print(
        con.execute(
            "SELECT rank_date, tier, count(*) AS n FROM universe "
            "WHERE month(rank_date)=6 GROUP BY 1,2 ORDER BY 1,2"
        ).fetchdf().to_string()
    )
    print()
    uniq = con.execute("SELECT count(DISTINCT symbol) FROM universe").fetchone()[0]
    uniq_core = con.execute("SELECT count(DISTINCT symbol) FROM universe WHERE tier='core'").fetchone()[0]
    print(f"unique symbols ever in universe: {uniq} (core tier: {uniq_core})")

    # survivorship audit: how many universe members stop having bars before the end
    print()
    print(
        con.execute(
            """
            SELECT
              count(*) FILTER (WHERE last_bar < DATE '2026-06-01') AS died_or_delisted,
              count(*) AS total
            FROM (
              SELECT u.symbol, max(x.d) AS last_bar
              FROM (SELECT DISTINCT symbol FROM universe) u
              JOIN daily x USING (symbol) GROUP BY 1
            )
            """
        ).fetchdf().to_string()
    )

    con.execute(f"COPY universe TO '{args.out}' (FORMAT PARQUET)")
    con.execute(
        f"COPY (SELECT * FROM daily) TO '{DATA / 'daily_clean.parquet'}' (FORMAT PARQUET)"
    )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
