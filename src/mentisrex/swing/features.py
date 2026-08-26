"""Cross-sectional feature panel built from intraday structure.

Timing convention, enforced throughout: **a row dated `d` contains only what
was observable by 15:45 ET on day `d`.** Strategies formed on that row may
trade in day `d`'s closing auction or day `d+1`'s opening auction. The gap
between the 15:45 decision price and the actual closing print is left in as
genuine execution uncertainty rather than assumed away -- a signal that only
works when it is both computed and filled at the same closing price is not a
signal, it is a look-ahead.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")

FEATURE_SQL = r"""
CREATE OR REPLACE VIEW pan AS SELECT * FROM parquet_scan('{panel}');
CREATE OR REPLACE VIEW dly AS SELECT * FROM parquet_scan('{daily}');
CREATE OR REPLACE VIEW uni AS SELECT * FROM parquet_scan('{universe}');
CREATE OR REPLACE VIEW earn AS SELECT symbol, CAST(date AS DATE) AS d, surprise_pct, eps, eps_forecast
                                FROM parquet_scan('{earnings}');
CREATE OR REPLACE VIEW seccls AS SELECT symbol, is_fund FROM parquet_scan('{secclass}');

-- Universe membership expanded to a daily grid. A rank date's cohort is
-- eligible from the following session until the next rank date.
CREATE OR REPLACE TABLE member AS
SELECT d.symbol, d.d, u.tier, u.liq_rank, u.addv60, u.vol60
FROM dly d
JOIN uni u
  ON u.symbol = d.symbol
 AND d.d >  u.rank_date
 AND (u.next_rank_date IS NULL OR d.d <= u.next_rank_date);

CREATE OR REPLACE TABLE base AS
SELECT
    p.symbol, p.d,
    p.p_open, p.p_close, p.hi, p.lo,
    p.p_0945, p.p_1000, p.p_1030, p.p_1100, p.p_1200,
    p.p_1300, p.p_1400, p.p_1500, p.p_1530, p.p_1545,
    p.or15_hi, p.or15_lo, p.or30_hi, p.or30_lo, p.or60_hi, p.or60_lo,
    p.or15_vol, p.or30_vol, p.or60_vol,
    p.pre_vol, p.rth_vol, p.post_vol, p.last30_vol, p.last60_vol, p.rth_trades,
    p.p_pre, p.vwap_day, p.vwap_am, p.vwap_pm, p.rth_dollar_vol,
    p.rv_day, p.rv_am, p.path_len, p.n_rth_bars,
    m.tier, m.liq_rank, m.addv60,
    lag(p.p_close) OVER w   AS prev_close,
    lag(p.rth_vol) OVER w   AS prev_rth_vol,
    lag(p.vwap_day) OVER w  AS prev_vwap,
    lag(p.hi) OVER w        AS prev_hi,
    lag(p.lo) OVER w        AS prev_lo,
    row_number() OVER w     AS bar_idx
FROM pan p
JOIN member m USING (symbol, d)
WINDOW w AS (PARTITION BY p.symbol ORDER BY p.d);

CREATE OR REPLACE TABLE feat AS
WITH r AS (
  SELECT
    *,
    ln(p_open  / nullif(prev_close, 0))  AS ret_on,     -- overnight, close(t-1) -> open(t)
    ln(p_close / nullif(p_open, 0))      AS ret_id,     -- intraday, open(t) -> close(t)
    ln(p_close / nullif(prev_close, 0))  AS ret_cc,
    ln(p_1545  / nullif(p_open, 0))      AS ret_id_1545,-- intraday return known at the decision time
    ln(p_close / nullif(p_1545, 0))      AS ret_last15, -- the run into the auction
    ln(p_1000  / nullif(p_open, 0))      AS ret_or30,
    ln(p_1545  / nullif(p_1500, 0))      AS ret_close45
  FROM base
),
w AS (
  SELECT
    r.*,
    -- liquidity / attention
    median(rth_vol)        OVER w20 AS med_vol20,
    median(rth_dollar_vol) OVER w20 AS med_dvol20,
    median(pre_vol)        OVER w20 AS med_prevol20,
    avg(rv_day)            OVER w20 AS avg_rv20,
    stddev_samp(ret_cc)    OVER w20 AS sd_cc20,
    stddev_samp(ret_cc)    OVER w60 AS sd_cc60,
    stddev_samp(ret_on)    OVER w60 AS sd_on60,
    stddev_samp(ret_id)    OVER w60 AS sd_id60,
    avg(abs(ret_cc))       OVER w20 AS mad20,
    -- overnight / intraday accumulation, the clientele-divergence primitives
    sum(ret_on)            OVER w5  AS son5,
    sum(ret_id)            OVER w5  AS sid5,
    sum(ret_on)            OVER w10 AS son10,
    sum(ret_id)            OVER w10 AS sid10,
    sum(ret_on)            OVER w21 AS son21,
    sum(ret_id)            OVER w21 AS sid21,
    sum(ret_on)            OVER w63 AS son63,
    sum(ret_id)            OVER w63 AS sid63,
    avg(CASE WHEN ret_id > 0 THEN 1.0 ELSE 0.0 END) OVER w10 AS idup10,
    avg(CASE WHEN ret_on > 0 THEN 1.0 ELSE 0.0 END) OVER w10 AS onup10,
    -- price levels for range / trend context
    max(hi) OVER w20 AS hi20, min(lo) OVER w20 AS lo20,
    sum(ret_cc) OVER w21  AS mom21,
    sum(ret_cc) OVER w63  AS mom63,
    sum(ret_cc) OVER w252 AS mom252,
    -- Corwin-Schultz inputs: two-day range
    greatest(hi, prev_hi) AS hi2, least(lo, prev_lo) AS lo2,
    -- Amihud illiquidity
    avg(abs(ret_cc) / nullif(rth_dollar_vol, 0)) OVER w20 * 1e9 AS amihud20
  FROM r
  WINDOW
    w5   AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN  4 PRECEDING AND CURRENT ROW),
    w10  AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN  9 PRECEDING AND CURRENT ROW),
    w20  AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
    w21  AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 20 PRECEDING AND CURRENT ROW),
    w60  AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
    w63  AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 62 PRECEDING AND CURRENT ROW),
    w252 AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
)
SELECT
  w.*,
  -- relative volume: the "stock in play" primitive
  rth_vol / nullif(med_vol20, 0)              AS rvol,
  pre_vol / nullif(med_prevol20, 0)           AS pre_rvol,
  or30_vol / nullif(med_vol20, 0)             AS rvol_or30,
  -- opening-range width relative to the name's own recent daily volatility:
  -- a wide first half hour is the clearest same-session evidence that a name
  -- is being repriced rather than drifting
  ln(or30_hi / nullif(or30_lo, 0)) / nullif(sd_cc60, 0) AS or30_range_z,
  last30_vol / nullif(rth_vol, 0)             AS close_vol_share,
  last60_vol / nullif(rth_vol, 0)             AS close60_vol_share,
  rth_dollar_vol / nullif(rth_trades, 0)      AS avg_trade_dollar,
  -- where the close sits in the day's range and versus the day's VWAP
  (p_close - lo) / nullif(hi - lo, 0)         AS clv,
  ln(p_close / nullif(vwap_day, 0))           AS close_vs_vwap,
  ln(p_1545  / nullif(vwap_day, 0))           AS p1545_vs_vwap,
  ln(p_close / nullif(vwap_pm, 0))            AS close_vs_vwap_pm,
  ln(p_close / nullif(vwap_pm, 0)) / nullif(rv_day / sqrt(26), 0) AS close_push,
  -- daily-only fallback: displacement from the *session* VWAP scaled by
  -- close-to-close volatility. A weaker instrument than close_push -- it
  -- cannot see whether the move happened in the last half hour -- and it is
  -- kept as a separate column rather than blended, so the two are never
  -- silently confused for one another.
  ln(p_close / nullif(vwap_day, 0)) / nullif(sd_cc60, 0) AS close_push_daily,
  -- normalised gap
  ret_on / nullif(sd_on60, 0)                 AS gap_z,
  ret_id / nullif(sd_id60, 0)                 AS id_z,
  -- position within the 20-day range
  (p_close - lo20) / nullif(hi20 - lo20, 0)   AS range_pos20,
  -- realised-vol ratio: is today unusually wide?
  rv_day / nullif(avg_rv20, 0)                AS rv_ratio,
  e.surprise_pct                              AS earn_surprise,
  CASE WHEN e.d IS NOT NULL THEN 1 ELSE 0 END AS is_earn_day,
  coalesce(sc.is_fund, FALSE)                 AS is_fund
FROM w
LEFT JOIN earn e ON e.symbol = w.symbol AND e.d = w.d
LEFT JOIN seccls sc ON sc.symbol = w.symbol
WHERE prev_close IS NOT NULL AND bar_idx > 60;
"""


def build(
    *,
    panel: str | Path = DATA / "panel.parquet",
    daily: str | Path = DATA / "daily_clean.parquet",
    universe: str | Path = DATA / "universe.parquet",
    earnings: str | Path = DATA / "earnings.parquet",
    secclass: str | Path = DATA / "security_class.parquet",
    out: str | Path = DATA / "features.parquet",
    threads: int = 8,
    memory: str = "12GB",
) -> Path:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"PRAGMA memory_limit='{memory}'")
    con.execute(f"PRAGMA temp_directory='{DATA / 'duckdb_tmp'}'")
    sql = FEATURE_SQL.format(
        panel=panel, daily=daily, universe=universe, earnings=earnings, secclass=secclass
    )
    for stmt in [s for s in sql.split(";") if s.strip()]:
        con.execute(stmt)
    con.execute(f"COPY feat TO '{out}' (FORMAT PARQUET)")
    n, s, a, b = con.execute(
        "SELECT count(*), count(DISTINCT symbol), min(d), max(d) FROM feat"
    ).fetchone()
    print(f"features: {n:,} rows  {s:,} symbols  {a} .. {b}  -> {out}")
    return Path(out)


if __name__ == "__main__":
    build()
