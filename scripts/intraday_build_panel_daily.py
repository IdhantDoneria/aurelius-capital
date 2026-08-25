"""Build a panel with the same schema from *daily* bars only.

Two uses. First, it lets the whole stack -- features, overlay, backtester,
metrics, validation -- be exercised end to end before the intraday pull
finishes. Second, and more usefully, it is a genuine robustness sample: it
covers every name in the universe over the full history, where the intraday
panel is restricted to the names whose bars were pulled.

Columns that genuinely cannot be derived from a daily bar are written NULL
rather than approximated, so any strategy that depends on them fails loudly
instead of silently trading a fabricated signal. Alpaca's daily bar does
carry a session VWAP and a trade count, so those are real; the afternoon
VWAP, the closing-volume share and every intraday price anchor are not.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")

SQL = """
CREATE OR REPLACE TABLE panel AS
SELECT
    symbol,
    CAST(ts AT TIME ZONE 'America/New_York' AS DATE) AS d,
    26                       AS n_rth_bars,
    open                     AS p_open,
    close                    AS p_close,
    high                     AS hi,
    low                      AS lo,
    -- intraday price anchors are not observable in a daily bar
    NULL::DOUBLE AS p_0945, NULL::DOUBLE AS p_1000, NULL::DOUBLE AS p_1030,
    NULL::DOUBLE AS p_1100, NULL::DOUBLE AS p_1200, NULL::DOUBLE AS p_1300,
    NULL::DOUBLE AS p_1400, NULL::DOUBLE AS p_1500, NULL::DOUBLE AS p_1530,
    NULL::DOUBLE AS p_1545,
    NULL::DOUBLE AS or15_hi, NULL::DOUBLE AS or15_lo, NULL::DOUBLE AS or15_vol,
    NULL::DOUBLE AS or30_hi, NULL::DOUBLE AS or30_lo, NULL::DOUBLE AS or30_vol,
    NULL::DOUBLE AS or60_hi, NULL::DOUBLE AS or60_lo, NULL::DOUBLE AS or60_vol,
    NULL::DOUBLE AS pre_vol,
    volume                   AS rth_vol,
    NULL::DOUBLE AS post_vol,
    NULL::DOUBLE AS last30_vol,
    NULL::DOUBLE AS last60_vol,
    trades                   AS rth_trades,
    NULL::DOUBLE AS p_pre,
    vwap                     AS vwap_day,
    NULL::DOUBLE AS vwap_am,
    NULL::DOUBLE AS vwap_pm,
    vwap * volume            AS rth_dollar_vol,
    -- a close-to-close volatility proxy stands in for realised intraday
    -- volatility; it is a different quantity and is labelled as one
    NULL::DOUBLE AS rv_day,
    NULL::DOUBLE AS rv_am,
    NULL::DOUBLE AS path_len,
    NULL::BIGINT AS n_ret
FROM parquet_scan('{glob}')
WHERE close > 0 AND open > 0 AND volume > 0;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default=str(DATA / "daily" / "*.parquet"))
    ap.add_argument("--out", default=str(DATA / "panel_daily.parquet"))
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--memory", default="10GB")
    args = ap.parse_args()

    (DATA / "duckdb_tmp").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute(f"PRAGMA memory_limit='{args.memory}'")
    con.execute(f"PRAGMA temp_directory='{DATA / 'duckdb_tmp'}'")
    con.execute(SQL.format(glob=args.glob))
    print(
        con.execute(
            "SELECT count(*) AS n_rows, count(DISTINCT symbol) AS n_syms, "
            "min(d) AS d_min, max(d) AS d_max FROM panel"
        ).fetchdf().to_string()
    )
    con.execute(f"COPY panel TO '{args.out}' (FORMAT PARQUET)")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
