"""Daily-bar pseudo-panel.

Produces the same column contract as `intraday_build_panel.py` from daily
OHLCV alone, leaving the columns that genuinely require intraday bars as
NULL. The point is that the overnight/intraday return decomposition -- the
primitive behind the clientele-divergence sleeve -- needs only the daily
open and close, so the whole engine can be built and validated against the
complete daily history while the 5-minute history is still downloading, and
the intraday-only sleeves then slot into the same feature contract.

Columns that are NULL here and only exist in the true intraday panel:
    p_0935 .. p_1545, or*_hi/lo/vol, pre_vol, post_vol, last30_vol,
    last60_vol, p_pre, vwap_am, vwap_pm, rv_day, rv_am, path_len
`vwap_day` is the daily VWAP the vendor reports, which is a genuine
volume-weighted average and not a reconstruction.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")

SQL = """
CREATE OR REPLACE TABLE panel AS
SELECT
    symbol, d,
    570                                   AS first_rth_mod,
    78                                    AS n_rth_bars,
    open                                  AS p_open,
    close                                 AS p_close,
    high                                  AS hi,
    low                                   AS lo,
    CAST(NULL AS DOUBLE) AS p_0935, CAST(NULL AS DOUBLE) AS p_0945,
    CAST(NULL AS DOUBLE) AS p_1000, CAST(NULL AS DOUBLE) AS p_1030,
    CAST(NULL AS DOUBLE) AS p_1100, CAST(NULL AS DOUBLE) AS p_1200,
    CAST(NULL AS DOUBLE) AS p_1300, CAST(NULL AS DOUBLE) AS p_1400,
    CAST(NULL AS DOUBLE) AS p_1500, CAST(NULL AS DOUBLE) AS p_1530,
    close                                 AS p_1545,
    close                                 AS p_1555,
    CAST(NULL AS DOUBLE) AS or5_hi,  CAST(NULL AS DOUBLE) AS or5_lo,
    CAST(NULL AS DOUBLE) AS or15_hi, CAST(NULL AS DOUBLE) AS or15_lo,
    CAST(NULL AS DOUBLE) AS or30_hi, CAST(NULL AS DOUBLE) AS or30_lo,
    CAST(NULL AS DOUBLE) AS or60_hi, CAST(NULL AS DOUBLE) AS or60_lo,
    CAST(NULL AS DOUBLE) AS or5_vol, CAST(NULL AS DOUBLE) AS or15_vol,
    CAST(NULL AS DOUBLE) AS or30_vol, CAST(NULL AS DOUBLE) AS or60_vol,
    CAST(NULL AS DOUBLE) AS pre_vol,
    volume                                AS rth_vol,
    CAST(NULL AS DOUBLE) AS post_vol,
    CAST(NULL AS DOUBLE) AS last30_vol,
    CAST(NULL AS DOUBLE) AS last60_vol,
    trades                                AS rth_trades,
    CAST(NULL AS DOUBLE) AS p_pre,
    vwap                                  AS vwap_day,
    CAST(NULL AS DOUBLE) AS vwap_am,
    CAST(NULL AS DOUBLE) AS vwap_pm,
    vwap * volume                         AS rth_dollar_vol,
    CAST(NULL AS DOUBLE) AS rv_day, CAST(NULL AS DOUBLE) AS rv_am,
    CAST(NULL AS DOUBLE) AS path_len, CAST(NULL AS BIGINT) AS n_ret
FROM parquet_scan('{daily}')
WHERE open > 0 AND close > 0 AND high > 0 AND low > 0 AND volume > 0;
"""


def build(
    daily: str | Path = DATA / "daily_clean.parquet",
    out: str | Path = DATA / "panel_daily.parquet",
    threads: int = 8,
) -> Path:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute(SQL.format(daily=daily))
    con.execute(f"COPY panel TO '{out}' (FORMAT PARQUET)")
    n, s = con.execute("SELECT count(*), count(DISTINCT symbol) FROM panel").fetchone()
    print(f"daily pseudo-panel: {n:,} rows, {s:,} symbols -> {out}")
    return Path(out)


if __name__ == "__main__":
    build()
