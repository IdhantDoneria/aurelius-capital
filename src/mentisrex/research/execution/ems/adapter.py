"""Real-broker adapter interfaces (AIDP M14) — interface-only, no network, no creds.

Each adapter maps the venue's native order/fill API onto the M14 `ExecutionBroker`
contract. They deliberately raise `NotImplementedError`: wiring a live venue is a
production concern (auth, sessions, rate limits, order-state callbacks) out of scope
for the deterministic offline platform. They exist so routing/config can name a real
venue today and a future implementation drops in without touching the EMS.

Mirrors M12's `adapter.py` (same five venues) so paper-trading and execution share
one adapter vocabulary.
"""

from __future__ import annotations

from mentisrex.research.execution.ems.broker import ExecutionBroker


class BrokerAdapter(ExecutionBroker):
    """Base for live venue adapters. Concrete venues implement the ABC methods against
    their SDK/FIX session. `capabilities` documents what the venue supports so the
    router can constrain algo/order-type choices per venue."""

    venue = "generic"
    capabilities = {"native_algos": (), "order_types": ("market", "limit")}

    def __init__(self, *, credentials=None, endpoint: str | None = None) -> None:
        self._credentials = credentials
        self._endpoint = endpoint

    def _unavailable(self):
        raise NotImplementedError(
            f"{self.venue} live execution is an interface-only stub; no network/credentials "
            "in the offline platform. Use MockExecutionBroker / SimulatedExecutionBroker."
        )

    def set_prices(self, prices):
        self._unavailable()

    def submit_order(self, req, *, adv=None):
        self._unavailable()

    def get_fills(self):
        self._unavailable()

    def get_order_status(self, broker_order_id):
        self._unavailable()

    def get_positions(self):
        self._unavailable()

    def get_account(self):
        self._unavailable()


class InteractiveBrokersAdapter(BrokerAdapter):
    venue = "interactive_brokers"
    capabilities = {
        "native_algos": ("twap", "vwap", "pov"),
        "order_types": ("market", "limit", "stop"),
    }


class AlpacaAdapter(BrokerAdapter):
    venue = "alpaca"
    capabilities = {"native_algos": (), "order_types": ("market", "limit", "stop")}


class ZerodhaAdapter(BrokerAdapter):
    venue = "zerodha"
    capabilities = {"native_algos": (), "order_types": ("market", "limit")}


class FIXAdapter(BrokerAdapter):
    venue = "fix"
    capabilities = {"native_algos": ("twap", "vwap"), "order_types": ("market", "limit", "stop")}
