"""Collapse intraday bars into one row per symbol-day of session structure.

Everything a strategy is allowed to see at a given clock time is materialised
here as a named column, so that no downstream signal can accidentally read a
price from later in the same session. Anchor columns are named for the ET
wall-clock time at which the quantity is *known*: `p_1000` is a price you
could have traded at 10:00, taken from the close of the bar that ends there.

Bar interval is a parameter. At a 15-minute interval a bar stamped 09:30
covers 09:30-09:45, so the price known at 10:00 is the close of the bar
stamped 09:45 -- i.e. `anchor_minute - interval`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")

RTH_OPEN, RTH_CLOSE = 9 * 60 + 30, 16 * 60

ANCHOR_MINUTES = {
    "0945": 9 * 60 + 45,
    "1000": 10 * 60,
    "1030": 10 * 60 + 30,
    "1100": 11 * 60,
    "1200": 12 * 60,
    "1300": 13 * 60,
    "1400": 14 * 60,
    "1500": 15 * 60,
    "1530": 15 * 60 + 30,
    "1545": 15 * 60 + 45,
}
OR_WINDOWS = {"15": 15, "30": 30, "60": 60}


def build_sql(glob: str, interval: int) -> str:
    rth_bars = (RTH_CLOSE - RTH_OPEN) // interval
    anchors = {k: v for k, v in ANCHOR_MINUTES.items() if (v - RTH_OPEN) % interval == 0}
    anchor_cols = ",\n        ".join(
        f"max(close) FILTER (WHERE mod = {m - interval}) AS p_{name}"
        for name, m in anchors.items()
    )
    or_cols = ",\n        ".join(
        f"max(high) FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_OPEN + w}) AS or{n}_hi,\n        "
        f"min(low)  FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_OPEN + w}) AS or{n}_lo,\n        "
        f"sum(volume) FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_OPEN + w}) AS or{n}_vol"
        for n, w in OR_WINDOWS.items()
        if w % interval == 0
    )
    return f"""
CREATE OR REPLACE VIEW b AS
SELECT
    symbol,
    CAST(ts AT TIME ZONE 'America/New_York' AS DATE)         AS d,
    CAST(date_part('hour',  ts AT TIME ZONE 'America/New_York') AS INT) * 60
      + CAST(date_part('minute', ts AT TIME ZONE 'America/New_York') AS INT) AS mod,
    open, high, low, close, volume, vwap, trades
FROM parquet_scan('{glob}')
WHERE close > 0;

CREATE OR REPLACE VIEW rth AS
SELECT * FROM b WHERE mod >= {RTH_OPEN} AND mod < {RTH_CLOSE};

CREATE OR REPLACE VIEW rth_ret AS
SELECT symbol, d, mod,
       ln(close / lag(close) OVER (PARTITION BY symbol, d ORDER BY mod)) AS r_bar
FROM rth;

CREATE OR REPLACE TABLE panel AS
WITH agg AS (
    SELECT
        symbol, d,
        count(*) FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_CLOSE})     AS n_rth_bars,
        arg_min(open, mod)  FILTER (WHERE mod >= {RTH_OPEN})                AS p_open,
        arg_max(close, mod) FILTER (WHERE mod < {RTH_CLOSE})                AS p_close,
        max(high) FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_CLOSE})    AS hi,
        min(low)  FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_CLOSE})    AS lo,
        {anchor_cols},
        {or_cols},
        sum(volume) FILTER (WHERE mod < {RTH_OPEN})                         AS pre_vol,
        sum(volume) FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_CLOSE})  AS rth_vol,
        sum(volume) FILTER (WHERE mod >= {RTH_CLOSE})                       AS post_vol,
        sum(volume) FILTER (WHERE mod >= {RTH_CLOSE - 30} AND mod < {RTH_CLOSE}) AS last30_vol,
        sum(volume) FILTER (WHERE mod >= {RTH_CLOSE - 60} AND mod < {RTH_CLOSE}) AS last60_vol,
        sum(trades) FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_CLOSE})  AS rth_trades,
        arg_max(close, mod) FILTER (WHERE mod < {RTH_OPEN})                 AS p_pre,
        sum(vwap * volume) FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_CLOSE})
          / nullif(sum(volume) FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_CLOSE}), 0) AS vwap_day,
        sum(vwap * volume) FILTER (WHERE mod >= {RTH_OPEN} AND mod < 720)
          / nullif(sum(volume) FILTER (WHERE mod >= {RTH_OPEN} AND mod < 720), 0)         AS vwap_am,
        sum(vwap * volume) FILTER (WHERE mod >= 780 AND mod < {RTH_CLOSE})
          / nullif(sum(volume) FILTER (WHERE mod >= 780 AND mod < {RTH_CLOSE}), 0)        AS vwap_pm,
        sum(vwap * volume) FILTER (WHERE mod >= {RTH_OPEN} AND mod < {RTH_CLOSE})         AS rth_dollar_vol
    FROM b
    GROUP BY symbol, d
),
rv AS (
    SELECT symbol, d,
           stddev_samp(r_bar) * sqrt({rth_bars})                        AS rv_day,
           stddev_samp(r_bar) FILTER (WHERE mod < 720) * sqrt({rth_bars}) AS rv_am,
           sum(abs(r_bar))                                              AS path_len,
           count(*)                                                     AS n_ret
    FROM rth_ret WHERE r_bar IS NOT NULL GROUP BY symbol, d
)
SELECT a.*, rv.rv_day, rv.rv_am, rv.path_len, rv.n_ret
FROM agg a LEFT JOIN rv USING (symbol, d)
WHERE a.n_rth_bars >= {max(rth_bars * 3 // 4, 4)} AND a.p_open > 0 AND a.p_close > 0;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default=str(DATA / "bars15" / "*.parquet"))
    ap.add_argument("--interval", type=int, default=15, help="bar length in minutes")
    ap.add_argument("--out", default=str(DATA / "panel.parquet"))
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--memory", default="10GB")
    args = ap.parse_args()

    (DATA / "duckdb_tmp").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute(f"PRAGMA memory_limit='{args.memory}'")
    con.execute(f"PRAGMA temp_directory='{DATA / 'duckdb_tmp'}'")
    for stmt in [s for s in build_sql(args.glob, args.interval).split(";") if s.strip()]:
        con.execute(stmt)

    print(
        con.execute(
            "SELECT count(*) AS n_rows, count(DISTINCT symbol) AS n_syms, "
            "min(d) AS d_min, max(d) AS d_max FROM panel"
        ).fetchdf().to_string()
    )
    print()
    print(con.execute("SELECT * FROM panel ORDER BY rth_dollar_vol DESC LIMIT 1").fetchdf().T.to_string())
    con.execute(f"COPY panel TO '{args.out}' (FORMAT PARQUET)")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
