"""Yahoo Finance adapter via yfinance.

Free, no auth required. Good for daily historical data back to 1970s.
Limitations: no intraday beyond 60 days, no tick data, no streaming.

yfinance.download() is synchronous — wrapped in asyncio.to_thread.
auto_adjust=True: yfinance applies split and dividend adjustments so that
returns computed from sequential closes are economically correct. Without
this, a 2:1 split inflates the prior-day return by ~100%.
"""

import asyncio
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from mentisrex.core.errors import MarketDataError
from mentisrex.core.logging import get_logger
from mentisrex.market_data.adapters.base import MarketDataAdapter, RawBar

logger = get_logger(__name__)

# yfinance interval strings differ from our frequency notation
_FREQ_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "1d": "1d",
    "1w": "1wk",
    "1M": "1mo",
}


class YahooFinanceAdapter(MarketDataAdapter):
    name = "yahoo_finance"

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        frequency: str = "1d",
    ) -> list[RawBar]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise MarketDataError("yfinance not installed: pip install yfinance") from exc

        interval = _FREQ_MAP.get(frequency)
        if interval is None:
            raise MarketDataError(f"Yahoo Finance does not support frequency={frequency!r}")

        try:
            df = await asyncio.to_thread(
                yf.download,
                symbol,
                start=start.date(),
                end=end.date(),
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            raise MarketDataError(f"Yahoo Finance fetch failed for {symbol}: {exc}") from exc

        if df is None or df.empty:
            logger.warning(
                "yahoo_empty_response", symbol=symbol, start=str(start.date()), end=str(end.date())
            )
            return []

        bars: list[RawBar] = []
        for ts, row in df.iterrows():
            # yfinance may return MultiIndex columns when columns=["Open","High",...] x [symbol]
            def _get(col_name: str, _row: object = row, _sym: str = symbol) -> float:  # type: ignore
                val = _row.get((col_name, _sym), _row.get(col_name, 0.0))  # type: ignore
                return float(val) if val is not None else 0.0

            ts_dt = ts.to_pydatetime()
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=UTC)

            bars.append(
                RawBar(
                    symbol=symbol.upper(),
                    timestamp=ts_dt,
                    open=Decimal(str(round(_get("Open"), 8))),
                    high=Decimal(str(round(_get("High"), 8))),
                    low=Decimal(str(round(_get("Low"), 8))),
                    close=Decimal(str(round(_get("Close"), 8))),
                    volume=Decimal(str(int(_get("Volume")))),
                    frequency=frequency,
                    source=self.name,
                )
            )

        logger.info("yahoo_fetch_complete", symbol=symbol, bar_count=len(bars))
        return bars

    async def fetch_raw_and_splits(
        self, symbol: str, start: datetime, end: datetime, frequency: str = "1d"
    ) -> tuple[list[dict], list[dict]]:
        """Fetch UNADJUSTED bars + split events for the PIT store (auto_adjust=False).

        Returns (raw_bars, actions) as dicts ready for
        PitPriceStore.write_raw_bars / record_actions. Separate from fetch_ohlcv
        (which stays adjusted for the legacy path) — this feeds the PIT store.
        """
        try:
            import yfinance as yf
        except ImportError as exc:
            raise MarketDataError("yfinance not installed: pip install yfinance") from exc
        interval = _FREQ_MAP.get(frequency)
        if interval is None:
            raise MarketDataError(f"Yahoo Finance does not support frequency={frequency!r}")
        try:
            df = await asyncio.to_thread(
                yf.Ticker(symbol).history,
                start=start.date(),
                end=end.date(),
                interval=interval,
                auto_adjust=False,
                actions=True,
            )
        except Exception as exc:
            raise MarketDataError(f"Yahoo raw fetch failed for {symbol}: {exc}") from exc
        return parse_raw_history(df, symbol, frequency)


def parse_raw_history(df: Any, symbol: str, frequency: str = "1d") -> tuple[list[dict], list[dict]]:
    """Split a yfinance history frame (auto_adjust=False, actions=True) into raw
    bars + split actions. Pure — no I/O, unit-testable without network.

    yfinance gives only the split's effective (ex-) date, not its announcement
    date, so announced_date = effective_date. Conservative for daily PIT: a split
    is treated as known on its ex-date. True announced dates need another source.
    """
    sym = symbol.upper()
    bars: list[dict] = []
    actions: list[dict] = []
    if df is None or getattr(df, "empty", True):
        return bars, actions

    def _f(row: Any, col: str) -> float:
        val = row.get(col)
        if val is None:
            return 0.0
        f = float(val)
        return 0.0 if math.isnan(f) else f

    for ts, row in df.iterrows():
        close = _f(row, "Close")
        if close <= 0:  # skip NaN/blank rows
            continue
        ts_dt = ts.to_pydatetime()
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=UTC)
        bars.append({
            "symbol": sym,
            "timestamp": ts_dt,
            "frequency": frequency,
            "open": Decimal(str(round(_f(row, "Open"), 8))),
            "high": Decimal(str(round(_f(row, "High"), 8))),
            "low": Decimal(str(round(_f(row, "Low"), 8))),
            "close": Decimal(str(round(close, 8))),
            "volume": Decimal(str(int(_f(row, "Volume")))),
            "source": "yahoo_finance",
        })
        ratio = _f(row, "Stock Splits")
        if ratio > 0:
            actions.append({
                "symbol": sym,
                "effective_date": ts_dt.date(),
                "ratio": ratio,
                "announced_date": ts_dt.date(),
            })
    return bars, actions
