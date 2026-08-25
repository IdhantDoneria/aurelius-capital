"""Intraday volatility cone: how far a name is expected to have travelled
from its open by a given time of day.

US intraday volatility is strongly U-shaped -- wide at the open, quiet
around midday, widening again into the close. A breakout rule with a fixed
percentage threshold is therefore a different rule at 09:45 than at 13:00,
and will systematically over-trade the open and under-trade the afternoon.

The cone is estimated as a product of two pieces:

    expected |log move from open| at bin b  =  sigma_name  x  shape(b)

`shape(b)` is a universe-wide profile: the median across names of the
absolute move-from-open at bin b divided by the name's own daily volatility,
taken over a trailing window. Estimating one common shape rather than a
separate cone per name is deliberate -- the per-name version is what the
literature does, but it estimates ~78 parameters per name from ~20
observations each, and the resulting cone is mostly noise.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")

SHAPE_SQL = """
CREATE OR REPLACE VIEW b AS
SELECT symbol,
       CAST(ts AT TIME ZONE 'America/New_York' AS DATE) AS d,
       CAST(date_part('hour', ts AT TIME ZONE 'America/New_York') AS INT) * 60
         + CAST(date_part('minute', ts AT TIME ZONE 'America/New_York') AS INT) AS mod,
       close
FROM parquet_scan('{bars}')
WHERE close > 0;

CREATE OR REPLACE VIEW rth AS SELECT * FROM b WHERE mod >= 570 AND mod < 960;

CREATE OR REPLACE VIEW dev AS
SELECT r.symbol, r.d, r.mod,
       abs(ln(r.close / o.p_open)) AS absmove,
       p.rv_day
FROM rth r
JOIN (SELECT symbol, d, arg_min(close, mod) AS p_open FROM rth GROUP BY 1, 2) o
  USING (symbol, d)
JOIN parquet_scan('{panel}') p USING (symbol, d)
WHERE o.p_open > 0 AND p.rv_day > 0;

-- one ratio per symbol-day-bin, then a daily cross-sectional median, then a
-- trailing average of those medians so the profile at date d uses only
-- sessions strictly before d
CREATE OR REPLACE TABLE shape AS
WITH per_day AS (
    SELECT d, mod, median(absmove / rv_day) AS ratio, count(*) AS n
    FROM dev GROUP BY 1, 2
)
SELECT d, mod,
       avg(ratio) OVER (
           PARTITION BY mod ORDER BY d ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
       ) AS shape_ratio
FROM per_day
WHERE n >= 30;
"""


def build(
    *,
    bars: str | Path = DATA / "bars15" / "*.parquet",
    panel: str | Path = DATA / "panel.parquet",
    out: str | Path = DATA / "cone.parquet",
    threads: int = 8,
    memory: str = "12GB",
) -> Path:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"PRAGMA memory_limit='{memory}'")
    con.execute(f"PRAGMA temp_directory='{DATA / 'duckdb_tmp'}'")
    for stmt in [s for s in SHAPE_SQL.format(bars=bars, panel=panel).split(";") if s.strip()]:
        con.execute(stmt)
    con.execute(f"COPY shape TO '{out}' (FORMAT PARQUET)")
    print(con.execute("SELECT count(*) AS n, min(d) AS a, max(d) AS b FROM shape").fetchdf().to_string())
    print(
        con.execute(
            "SELECT mod, avg(shape_ratio) AS avg_shape FROM shape "
            "WHERE mod IN (585,600,630,720,840,930,945) GROUP BY 1 ORDER BY 1"
        ).fetchdf().to_string()
    )
    return Path(out)


if __name__ == "__main__":
    build()
