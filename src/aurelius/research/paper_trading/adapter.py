"""Real-broker adapter interfaces (AIDP M12) — design only, no live connectivity.

Each adapter is a `Broker` subclass whose methods raise `NotImplementedError`.
This fixes the *interface* a production adapter must satisfy (the same five
methods the offline brokers implement) without shipping any network code,
credentials, or fabricated fills. Implementing one means: translate `OrderRequest`
to the venue protocol, stream fills back as `BrokerFill`, and map the venue's
account report to `BrokerAccount`. Nothing else in M12 changes.

See `docs/AURELIUS_M12_PAPER_TRADING.md` §Future production path.
"""

from __future__ import annotations

from aurelius.research.paper_trading.broker import Broker


class BrokerAdapter(Broker):
    """Base for real venues. `connect`/`disconnect` manage the session; the five
    `Broker` methods must be implemented against the venue API/protocol."""

    name = "adapter"

    def connect(self) -> None:
        raise NotImplementedError(f"{type(self).__name__}: live connectivity not implemented (M12 is offline)")

    def disconnect(self) -> None:
        raise NotImplementedError

    def set_prices(self, prices):
        raise NotImplementedError("real adapters take marks from a live market-data feed")

    def place_order(self, req, *, adv=None):
        raise NotImplementedError

    def poll_fills(self):
        raise NotImplementedError

    def get_account(self):
        raise NotImplementedError


class InteractiveBrokersAdapter(BrokerAdapter):
    """TWS / IB Gateway via ib_insync or the native API. Needs: gateway session,
    contract resolution, order translation, execDetails → BrokerFill."""
    name = "interactive_brokers"


class AlpacaAdapter(BrokerAdapter):
    """Alpaca REST/streaming. Needs: API key/secret, /v2/orders, trade-update WS."""
    name = "alpaca"


class ZerodhaAdapter(BrokerAdapter):
    """Zerodha Kite Connect. Needs: api_key + access_token, /orders, postback fills."""
    name = "zerodha"


class FIXAdapter(BrokerAdapter):
    """Generic FIX 4.2/4.4 OMS. Needs: session (logon/heartbeat), NewOrderSingle(D),
    ExecutionReport(8) → BrokerFill, position/collateral report → BrokerAccount."""
    name = "fix"
