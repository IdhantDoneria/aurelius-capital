"""Alpaca Markets adapter — historical REST + real-time WebSocket streaming.

Uses Alpaca Data API v2. Free tier provides:
  - Historical OHLCV back to 2015 (IEX feed)
  - Real-time minute bars (IEX feed, 15-min delay on free plan)

Auth: APCA-API-KEY-ID / APCA-API-SECRET-KEY headers.
Implemented over httpx (already a project dep) + websockets for streaming.
No alpaca-py SDK needed — direct REST keeps the dep count down.

Retry logic: 3 attempts with exponential backoff for network errors.
Rate limit (429): back off 60s and retry.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

import httpx

from aurelius.core.errors import MarketDataError
from aurelius.core.logging import get_logger
from aurelius.market_data.adapters.base import MarketDataAdapter, RawBar

logger = get_logger(__name__)

_DATA_BASE = "https://data.alpaca.markets/v2"
_STREAM_URL = "wss://stream.data.alpaca.markets/v2/iex"
_MAX_RETRIES = 3

# Alpaca timeframe strings
_FREQ_MAP: dict[str, str] = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "4h": "4Hour",
    "1d": "1Day",
}


class AlpacaAdapter(MarketDataAdapter):
    name = "alpaca"

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
        }

    @classmethod
    def from_settings(cls) -> "AlpacaAdapter":
        from aurelius.infrastructure.config.settings import get_settings

        s = get_settings()
        return cls(api_key=s.alpaca_api_key, api_secret=s.alpaca_api_secret)

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        frequency: str = "1d",
    ) -> list[RawBar]:
        timeframe = _FREQ_MAP.get(frequency)
        if timeframe is None:
            raise MarketDataError(f"Alpaca does not support frequency={frequency!r}")

        bars: list[RawBar] = []
        page_token: str | None = None

        async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
            while True:
                params: dict = {
                    "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "timeframe": timeframe,
                    "limit": 10_000,
                    "adjustment": "raw",  # we apply adjustments via corporate actions
                }
                if page_token:
                    params["page_token"] = page_token

                resp = await self._get_with_retry(
                    client, f"{_DATA_BASE}/stocks/{symbol}/bars", params
                )
                data = resp.json()

                for b in data.get("bars", []):
                    ts = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
                    bars.append(
                        RawBar(
                            symbol=symbol.upper(),
                            timestamp=ts,
                            open=Decimal(str(b["o"])),
                            high=Decimal(str(b["h"])),
                            low=Decimal(str(b["l"])),
                            close=Decimal(str(b["c"])),
                            volume=Decimal(str(b["v"])),
                            vwap=Decimal(str(b["vw"])) if "vw" in b else None,
                            trade_count=b.get("n"),
                            frequency=frequency,
                            source=self.name,
                        )
                    )

                page_token = data.get("next_page_token")
                if not page_token:
                    break

        logger.info("alpaca_fetch_complete", symbol=symbol, bar_count=len(bars))
        return bars

    async def stream_bars(self, symbols: list[str]) -> AsyncIterator[RawBar]:
        """Stream real-time minute bars from Alpaca IEX WebSocket feed.

        Runs indefinitely until the caller cancels the task or the connection drops.
        Reconnect logic is the caller's responsibility (wrap in asyncio.Task + retry loop).
        """
        try:
            import websockets
        except ImportError as exc:
            raise MarketDataError("websockets not installed: pip install websockets") from exc

        auth_msg = json.dumps(
            {
                "action": "auth",
                "key": self._headers["APCA-API-KEY-ID"],
                "secret": self._headers["APCA-API-SECRET-KEY"],
            }
        )
        subscribe_msg = json.dumps({"action": "subscribe", "bars": symbols})

        async with websockets.connect(_STREAM_URL) as ws:  # type: ignore[attr-defined]
            await ws.send(auth_msg)
            await ws.recv()  # auth confirmation
            await ws.send(subscribe_msg)
            await ws.recv()  # subscription confirmation

            async for message in ws:
                for event in json.loads(message):
                    if event.get("T") != "b":
                        continue
                    ts = datetime.fromisoformat(event["t"].replace("Z", "+00:00"))
                    yield RawBar(
                        symbol=event["S"].upper(),
                        timestamp=ts,
                        open=Decimal(str(event["o"])),
                        high=Decimal(str(event["h"])),
                        low=Decimal(str(event["l"])),
                        close=Decimal(str(event["c"])),
                        volume=Decimal(str(event["v"])),
                        vwap=Decimal(str(event["vw"])) if "vw" in event else None,
                        trade_count=event.get("n"),
                        frequency="1m",
                        source=self.name,
                    )

    async def _get_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict,
    ) -> httpx.Response:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    logger.warning("alpaca_rate_limited", attempt=attempt)
                    await asyncio.sleep(60)
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                if attempt == _MAX_RETRIES - 1:
                    raise MarketDataError(
                        f"Alpaca network error after {_MAX_RETRIES} attempts: {exc}"
                    ) from exc
                await asyncio.sleep(2**attempt)
            except httpx.HTTPStatusError as exc:
                raise MarketDataError(
                    f"Alpaca HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                ) from exc
        raise MarketDataError("Alpaca request failed after all retries")
