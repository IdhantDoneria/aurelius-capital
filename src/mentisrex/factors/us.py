"""USFactorEngine — US equity factor signals, CIK-keyed.

Factors returned (all percentile-ranked 0-1):
  momentum    12-1 month price momentum (skips missing endpoints)
  book_equity raw StockholdersEquity cross-section
  net_income  raw NetIncomeLoss cross-section
  roe         net_income / |book_equity| (quality/earnings-yield proxy)
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np

from mentisrex.factors.engine import FactorEngine
from mentisrex.market_data.fundamentals.store import FundamentalsStore
from mentisrex.market_data.storage.duckdb_store import DuckDBStore
from mentisrex.research.cross_sectional import percentile_rank

_DEFAULT_TICKER_MAP_PATHS = (
    Path("raw/edgar/company_tickers.json"),
    Path("./raw/edgar/company_tickers.json"),
)


def _load_cik_to_ticker(path: Path) -> dict[str, str]:
    """Load {CIK0000...: TICKER} from EDGAR company_tickers.json."""
    data = json.loads(path.read_text())
    return {f"CIK{int(v['cik_str']):010d}": v["ticker"].upper() for v in data.values()}


def _rank(mapping: dict[str, float]) -> dict[str, float]:
    """Percentile-rank the values of a {id: float} dict, drop NaN."""
    if not mapping:
        return {}
    keys = list(mapping.keys())
    vals = np.array([mapping[k] for k in keys], dtype=float)
    ranked = percentile_rank(vals)
    return {k: float(v) for k, v in zip(keys, ranked) if math.isfinite(v)}


class USFactorEngine(FactorEngine):
    """US equity factors using CIK-keyed securities.

    ohlcv_db_path       path to analytics.duckdb (Parquet auto-detect supported)
    fundamentals_db_path path to fundamentals.duckdb (Parquet auto-detect supported)
    """

    _FACTORS = ("momentum", "book_equity", "net_income", "roe")

    def __init__(self, ohlcv_db_path: str, fundamentals_db_path: str,
                 ticker_map_path: str | None = None) -> None:
        self._price = DuckDBStore(ohlcv_db_path)
        self._fund = FundamentalsStore(fundamentals_db_path)

        # CIK → ticker map so fundamentals (CIK-keyed) align with OHLCV (ticker-keyed).
        # analytics.duckdb stores Alpaca bars by ticker (AAPL) not CIK (CIK0000320193)
        # when the bulk fetch ran without a resolved CIK mapping at fetch time.
        self._cik_to_ticker: dict[str, str] = {}
        candidates = [Path(ticker_map_path)] if ticker_map_path else list(_DEFAULT_TICKER_MAP_PATHS)
        for p in candidates:
            if p.exists():
                self._cik_to_ticker = _load_cik_to_ticker(p)
                break

    # ── public API ────────────────────────────────────────────────────────────

    def compute(
        self, as_of: date, *, knowledge_date: date | None = None
    ) -> dict[str, dict[str, float]]:
        return {name: self.compute_factor(name, as_of, knowledge_date=knowledge_date)
                for name in self._FACTORS}

    def compute_factor(
        self, name: str, as_of: date, *, knowledge_date: date | None = None
    ) -> dict[str, float]:
        if name == "momentum":
            return self._momentum(as_of)
        if name == "book_equity":
            return self._fundamental("StockholdersEquity", as_of, knowledge_date)
        if name == "net_income":
            return self._fundamental("NetIncomeLoss", as_of, knowledge_date)
        if name == "roe":
            return self._roe(as_of, knowledge_date)
        raise ValueError(f"Unknown factor: {name!r}. Available: {self._FACTORS}")

    # ── factor implementations ────────────────────────────────────────────────

    def _momentum(self, as_of: date) -> dict[str, float]:
        """12-1 month momentum: (close ~1m ago) / (close ~12m ago) - 1, per symbol."""
        # ponytail: ~21 and ~252 trading-day offsets via calendar days (30/365).
        # Use SQL to find the nearest bar within a ±10-day window of each target date.
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
        from datetime import timedelta
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

    def _remap(self, cik_dict: dict[str, float]) -> dict[str, float]:
        """Remap CIK keys → ticker keys when the mapping file is available."""
        if not self._cik_to_ticker:
            return cik_dict
        return {self._cik_to_ticker[cik]: v for cik, v in cik_dict.items()
                if cik in self._cik_to_ticker}

    def _fundamental(
        self, concept: str, as_of: date, knowledge_date: date | None
    ) -> dict[str, float]:
        cross = self._fund.cross_section_as_of(concept, as_of, knowledge_date=knowledge_date)
        clean = {cik: v for cik, v in cross.items()
                 if v is not None and math.isfinite(v)}
        return _rank(self._remap(clean))

    def _roe(self, as_of: date, knowledge_date: date | None) -> dict[str, float]:
        ni = self._fund.cross_section_as_of("NetIncomeLoss", as_of, knowledge_date=knowledge_date)
        eq = self._fund.cross_section_as_of("StockholdersEquity", as_of, knowledge_date=knowledge_date)
        raw = {}
        for cik in ni:
            if cik not in eq:
                continue
            n, e = ni[cik], eq[cik]
            if n is None or e is None:
                continue
            if not (math.isfinite(n) and math.isfinite(e)):
                continue
            denom = abs(e)
            if denom < 1.0:  # guard near-zero equity
                continue
            raw[cik] = n / denom
        return _rank(self._remap(raw))
