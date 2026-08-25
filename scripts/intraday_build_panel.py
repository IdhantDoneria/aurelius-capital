"""Collapse 5-minute bars into one row per symbol-day of intraday structure.

Everything a strategy is allowed to see at a given clock time is materialised
here as a named column, so that no downstream signal can accidentally read a
price from later in the same session. Anchor columns are named for the ET
wall-clock time at which the quantity is *known* (p_1000 is the price you
could have traded at 10:00), not for the bar that produced them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")

# (column suffix, ET minute-of-day at which the price is known)
ANCHORS = [
    ("0935", 9 * 60 + 35),
    ("0945", 9 * 60 + 45),
    ("1000", 10 * 60),
    ("1030", 10 * 60 + 30),
    ("1100", 11 * 60),
    ("1200", 12 * 60),
    ("1300", 13 * 60),
    ("1400", 14 * 60),
    ("1500", 15 * 60),
    ("1530", 15 * 60 + 30),
    ("1545", 15 * 60 + 45),
    ("1555", 15 * 60 + 55),
]

# opening-range windows: (suffix, minutes after 09:30)
OR_WINDOWS = [("5", 5), ("15", 15), ("30", 30), ("60", 60)]


def build_sql(glob: str) -> str:
    anchor_cols = ",\n        ".join(
        f"max(close) FILTER (WHERE mod = {m - 5}) AS p_{name}" for name, m in ANCHORS
    )
    or_cols = ",\n        ".join(
        f"max(high) FILTER (WHERE mod >= 570 AND mod < {570 + w}) AS or{name}_hi,\n        "
        f"min(low)  FILTER (WHERE mod >= 570 AND mod < {570 + w}) AS or{name}_lo,\n        "
        f"sum(volume) FILTER (WHERE mod >= 570 AND mod < {570 + w}) AS or{name}_vol"
        for name, w in OR_WINDOWS
    )
    return f"""
CREATE OR REPLACE VIEW b AS
SELECT
    symbol,
    ts AT TIME ZONE 'America/New_York'                       AS et,
    CAST(ts AT TIME ZONE 'America/New_York' AS DATE)         AS d,
    CAST(date_part('hour',  ts AT TIME ZONE 'America/New_York') AS INT) * 60
      + CAST(date_part('minute', ts AT TIME ZONE 'America/New_York') AS INT) AS mod,
    open, high, low, close, volume, vwap, trades
FROM parquet_scan('{glob}')
WHERE close > 0;

CREATE OR REPLACE VIEW rth AS SELECT * FROM b WHERE mod >= 570 AND mod < 960;

CREATE OR REPLACE VIEW rth_ret AS
SELECT symbol, d, mod,
       ln(close / lag(close) OVER (PARTITION BY symbol, d ORDER BY mod)) AS r5
FROM rth;

CREATE OR REPLACE TABLE panel AS
WITH agg AS (
    SELECT
        symbol, d,
        -- session shape
        min(mod) FILTER (WHERE mod >= 570)                   AS first_rth_mod,
        count(*) FILTER (WHERE mod >= 570 AND mod < 960)     AS n_rth_bars,
        arg_min(open, mod) FILTER (WHERE mod >= 570)         AS p_open,
        arg_max(close, mod) FILTER (WHERE mod < 960)         AS p_close,
        max(high) FILTER (WHERE mod >= 570 AND mod < 960)    AS hi,
        min(low)  FILTER (WHERE mod >= 570 AND mod < 960)    AS lo,
        {anchor_cols},
        {or_cols},
        -- volume segmentation
        sum(volume) FILTER (WHERE mod < 570)                 AS pre_vol,
        sum(volume) FILTER (WHERE mod >= 570 AND mod < 960)  AS rth_vol,
        sum(volume) FILTER (WHERE mod >= 960)                AS post_vol,
        sum(volume) FILTER (WHERE mod >= 930 AND mod < 960)  AS last30_vol,
        sum(volume) FILTER (WHERE mod >= 900 AND mod < 960)  AS last60_vol,
        sum(trades) FILTER (WHERE mod >= 570 AND mod < 960)  AS rth_trades,
        -- pre-market reference price (last print before the bell)
        arg_max(close, mod) FILTER (WHERE mod < 570)         AS p_pre,
        -- session VWAP and the AM/PM split
        sum(vwap * volume) FILTER (WHERE mod >= 570 AND mod < 960)
          / nullif(sum(volume) FILTER (WHERE mod >= 570 AND mod < 960), 0)  AS vwap_day,
        sum(vwap * volume) FILTER (WHERE mod >= 570 AND mod < 720)
          / nullif(sum(volume) FILTER (WHERE mod >= 570 AND mod < 720), 0)  AS vwap_am,
        sum(vwap * volume) FILTER (WHERE mod >= 780 AND mod < 960)
          / nullif(sum(volume) FILTER (WHERE mod >= 780 AND mod < 960), 0)  AS vwap_pm,
        -- dollar volume in RTH
        sum(vwap * volume) FILTER (WHERE mod >= 570 AND mod < 960)          AS rth_dollar_vol
    FROM b
    GROUP BY symbol, d
),
rv AS (
    SELECT symbol, d,
           stddev_samp(r5) * sqrt(78)                        AS rv_day,
           stddev_samp(r5) FILTER (WHERE mod < 720) * sqrt(78) AS rv_am,
           sum(abs(r5))                                      AS path_len,
           count(*)                                          AS n_ret
    FROM rth_ret WHERE r5 IS NOT NULL GROUP BY symbol, d
)
SELECT a.*, rv.rv_day, rv.rv_am, rv.path_len, rv.n_ret
FROM agg a LEFT JOIN rv USING (symbol, d)
WHERE a.n_rth_bars >= 40 AND a.p_open > 0 AND a.p_close > 0;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default=str(DATA / "bars5" / "*.parquet"))
    ap.add_argument("--out", default=str(DATA / "panel.parquet"))
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--memory", default="12GB")
    args = ap.parse_args()

    con = duckdb.connect()
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute(f"PRAGMA memory_limit='{args.memory}'")
    con.execute(f"PRAGMA temp_directory='{DATA / 'duckdb_tmp'}'")
    con.execute(build_sql(args.glob))

    print(
        con.execute(
            "SELECT count(*) rows, count(DISTINCT symbol) syms, min(d) mn, max(d) mx FROM panel"
        ).fetchdf().to_string()
    )
    print()
    print(con.execute("SELECT * FROM panel ORDER BY d DESC, rth_dollar_vol DESC LIMIT 2").fetchdf().T.to_string())
    con.execute(f"COPY panel TO '{args.out}' (FORMAT PARQUET)")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
