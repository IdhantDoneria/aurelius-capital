"""Yahoo Finance adapter via yfinance.

Free, no auth required. Good for daily historical data back to 1970s.
Limitations: no intraday beyond 60 days, no tick data, no streaming.

yfinance.download() is synchronous — wrapped in asyncio.to_thread.
auto_adjust=False: we manage split/dividend adjustment factors ourselves.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from aurelius.core.errors import MarketDataError
from aurelius.core.logging import get_logger
from aurelius.market_data.adapters.base import MarketDataAdapter, RawBar

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
                auto_adjust=False,
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
            def _get(col_name: str, _row: object = row, _sym: str = symbol) -> float:
                val = _row.get((col_name, _sym), _row.get(col_name, 0.0))
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
