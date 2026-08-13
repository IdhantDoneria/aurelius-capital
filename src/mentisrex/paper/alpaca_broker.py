"""AlpacaBroker — wraps Alpaca paper trading REST API with the same interface as PaperBroker.

Set env vars ALPACA_API_KEY and ALPACA_API_SECRET (paper trading keys).
Swap BASE_URL to https://api.alpaca.markets for live.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from mentisrex.backtesting.events.types import FillEvent, OrderType, Side
from mentisrex.core.logging import get_logger
from mentisrex.paper.broker import OrderRequest, OrderResult, Tick

logger = get_logger(__name__)

BASE_URL = "https://paper-api.alpaca.markets"

_SIDE = {Side.BUY: "buy", Side.SELL: "sell"}
_TYPE = {OrderType.MARKET: "market", OrderType.LIMIT: "limit"}


class AlpacaBroker:
    """Drop-in replacement for PaperBroker backed by Alpaca paper trading.

    TradingEngine.on_tick() is a no-op here — Alpaca manages fills server-side.
    Call account() to poll current state instead.
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str = BASE_URL) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
                "accept": "application/json",
            },
            timeout=10.0,
        )

    # ── market data (no-op: Alpaca manages fills) ────────────────────────────

    def on_tick(self, tick: Tick) -> list[FillEvent]:  # noqa: ARG002
        return []

    # ── order entry ──────────────────────────────────────────────────────────

    def submit(self, req: OrderRequest, now: datetime | None = None) -> OrderResult:  # noqa: ARG002
        payload: dict = {
            "symbol": req.symbol,
            "qty": str(req.quantity),
            "side": _SIDE[req.side],
            "type": _TYPE[req.order_type],
            "time_in_force": "day",
        }
        if req.order_type == OrderType.LIMIT and req.limit_price is not None:
            payload["limit_price"] = str(req.limit_price)

        resp = self._http.post("/v2/orders", json=payload)
        if not resp.is_success:
            msg = resp.json().get("message", resp.text)
            logger.warning("alpaca_order_rejected", symbol=req.symbol, reason=msg)
            return OrderResult(accepted=False, reason=msg)

        data = resp.json()
        oid = data["id"]
        resting = data.get("status") in ("new", "partially_filled", "accepted")
        fill: FillEvent | None = None
        if data.get("status") == "filled":
            fill = _to_fill(data)
        logger.info("alpaca_order", symbol=req.symbol, id=oid, status=data.get("status"))
        return OrderResult(accepted=True, resting=resting, fill=fill, order_id=oid)

    # ── account ──────────────────────────────────────────────────────────────

    def account(self) -> dict:
        acc = self._http.get("/v2/account").raise_for_status().json()
        pos_list = self._http.get("/v2/positions").raise_for_status().json()
        positions = {p["symbol"]: Decimal(p["qty"]) for p in pos_list}
        unrealized = sum(Decimal(p.get("unrealized_pl", "0")) for p in pos_list)
        return {
            "cash": Decimal(acc["cash"]),
            "equity": Decimal(acc["equity"]),
            "buying_power": Decimal(acc["buying_power"]),
            "unrealized_pnl": unrealized,
            "realized_pnl": Decimal(0),  # ponytail: Alpaca doesn't expose realized PnL on account endpoint
            "positions": positions,
            "open_orders": self.open_orders,
        }

    @property
    def open_orders(self) -> int:
        return len(self._http.get("/v2/orders", params={"status": "open"}).raise_for_status().json())

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AlpacaBroker:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _to_fill(data: dict) -> FillEvent:
    px = Decimal(data.get("filled_avg_price") or data.get("limit_price") or "0")
    qty = Decimal(data.get("filled_qty") or data.get("qty") or "0")
    side = Side.BUY if data["side"] == "buy" else Side.SELL
    return FillEvent(
        timestamp=datetime.now(UTC),
        symbol=data["symbol"],
        side=side,
        quantity=qty,
        fill_price=px,
        commission=Decimal(0),
        slippage_cost=Decimal(0),
        order_id=data["id"],
    )


if __name__ == "__main__":
    import os

    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_API_SECRET", "")
    assert key and secret, "Set ALPACA_API_KEY and ALPACA_API_SECRET env vars"
    with AlpacaBroker(key, secret) as broker:
        acc = broker.account()
        print("cash:", acc["cash"], "equity:", acc["equity"], "positions:", acc["positions"])
