"""NSEFactorEngine — NSE equity factor signals, ISIN-keyed.

Only price-based factors are available; Indian companies are not on EDGAR so
fundamentals (value, quality) require a separate Indian data source.

Factors returned (all percentile-ranked 0-1):
  momentum    12-1 month price momentum
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from mentisrex.factors.engine import FactorEngine
from mentisrex.market_data.storage.duckdb_store import DuckDBStore
from mentisrex.research.cross_sectional import percentile_rank


def _rank(mapping: dict[str, float]) -> dict[str, float]:
    if not mapping:
        return {}
    keys = list(mapping.keys())
    vals = np.array([mapping[k] for k in keys], dtype=float)
    ranked = percentile_rank(vals)
    return {k: float(v) for k, v in zip(keys, ranked, strict=False) if math.isfinite(v)}


class NSEFactorEngine(FactorEngine):
    """NSE equity factors using ISIN-keyed securities.

    Only momentum is available without a separate Indian fundamentals source.
    Fundamentals-based factors (book_equity, net_income, roe) are not
    implemented — add an IndianFundamentalsStore if/when that data is ingested.
    """

    _FACTORS = ("momentum",)

    def __init__(self, ohlcv_db_path: str) -> None:
        self._price = DuckDBStore(ohlcv_db_path)

    def compute(
        self, as_of: date, *, knowledge_date: date | None = None
    ) -> dict[str, dict[str, float]]:
        return {"momentum": self._momentum(as_of)}

    def compute_factor(
        self, name: str, as_of: date, *, knowledge_date: date | None = None
    ) -> dict[str, float]:
        if name == "momentum":
            return self._momentum(as_of)
        raise ValueError(
            f"Factor {name!r} not available for NSE. "
            "Fundamentals require a separate Indian data source. "
            f"Available: {self._FACTORS}"
        )

    def _momentum(self, as_of: date) -> dict[str, float]:
        sql = """
        WITH
          near_1m AS (
            SELECT symbol,
                   close,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ABS(CAST(timestamp AS DATE) - CAST(? AS DATE))) AS rn
            FROM ohlcv
            WHERE frequency = '1d'
              AND CAST(timestamp AS DATE) BETWEEN (CAST(? AS DATE) - INTERVAL 40 DAY)
                                              AND (CAST(? AS DATE) + INTERVAL 0 DAY)
          ),
          near_12m AS (
            SELECT symbol,
                   close,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ABS(CAST(timestamp AS DATE) - CAST(? AS DATE))) AS rn
            FROM ohlcv
            WHERE frequency = '1d'
              AND CAST(timestamp AS DATE) BETWEEN (CAST(? AS DATE) - INTERVAL 40 DAY)
                                              AND (CAST(? AS DATE) + INTERVAL 0 DAY)
          )
        SELECT n1.symbol,
               CAST(n1.close AS DOUBLE) AS c1,
               CAST(n12.close AS DOUBLE) AS c12
        FROM (SELECT symbol, close FROM near_1m  WHERE rn = 1) n1
        JOIN (SELECT symbol, close FROM near_12m WHERE rn = 1) n12
          ON n1.symbol = n12.symbol
        WHERE n12.close > 0
        """
        t1 = (as_of - timedelta(days=30)).isoformat()
        t12 = (as_of - timedelta(days=365)).isoformat()
        rows = self._price.query(sql, [t1, t1, t1, t12, t12, t12])
        raw = {}
        for r in rows:
            sym = r["symbol"]
            c1, c12 = r["c1"], r["c12"]
            if c1 and c12 and math.isfinite(c1) and math.isfinite(c12) and c12 != 0:
                raw[sym] = c1 / c12 - 1.0
        return _rank(raw)
