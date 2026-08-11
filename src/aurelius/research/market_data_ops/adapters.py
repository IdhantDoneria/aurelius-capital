"""Source-adapter runtime (AIDP M20).

A clean operational runtime around M19's raw sources. M19 `MarketDataSource` answers a single
question — "give me raw records knowable on/before as_of". A production feed needs more: a
lifecycle (connect/disconnect), subscription management, polling, a declared **capability set**,
metadata and a health probe. `SourceAdapter` is that contract; concrete offline adapters wrap M19
sources, replay message logs, or serve recorded fixtures.

Nothing here opens a socket. `ProductionSourceAdapter` defines the exact live contract but its
transport methods raise `NotImplementedError` with the precise unblock — this platform has no paid
market-data credentials by mandate. A real deployment subclasses it, wires the transport, and
inherits everything else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from enum import Enum

from aurelius.research.market_data.sources import MarketDataSource
from aurelius.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
)


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(frozen=True)
class SourceMetadata:
    name: str
    capabilities: frozenset
    schema_version: str = "1.0"
    description: str = ""
    vendor: str = ""

    def supports(self, cap: SourceCapability) -> bool:
        return cap in self.capabilities


@dataclass
class AdapterHealthSample:
    """A cheap, wall-clock-free health readout. Operational timing (latency/staleness in real
    seconds) is computed by the monitoring layer with an *injected* clock — never read here."""
    state: ConnectionState
    message_count: int = 0
    error_count: int = 0
    last_sequence: int | None = None
    last_observation_date: date | None = None
    last_message_fingerprint: str | None = None
    subscriptions: tuple = ()


class SourceAdapter(ABC):
    """Operational source contract: lifecycle + subscription + fetch/poll + capabilities + health.

    Offline adapters implement `fetch`/`poll` deterministically. `connect`/`disconnect` default to
    state bookkeeping; a live adapter overrides them to manage a real session.
    """

    def __init__(self, metadata: SourceMetadata) -> None:
        self.metadata = metadata
        self._state = ConnectionState.DISCONNECTED
        self._subscriptions: set = set()
        self._message_count = 0
        self._error_count = 0
        self._last: AdapterHealthSample | None = None

    # ── capability model ────────────────────────────────────────────────────────
    @property
    def capabilities(self) -> frozenset:
        return self.metadata.capabilities

    def supports(self, cap: SourceCapability) -> bool:
        return self.metadata.supports(cap)

    def require(self, cap: SourceCapability) -> None:
        if not self.supports(cap):
            raise CapabilityError(f"{self.metadata.name}: capability {cap.value!r} not supported")

    # ── lifecycle ───────────────────────────────────────────────────────────────
    def connect(self) -> None:
        self._state = ConnectionState.CONNECTED

    def disconnect(self) -> None:
        self._state = ConnectionState.DISCONNECTED

    @property
    def state(self) -> ConnectionState:
        return self._state

    # ── subscription ────────────────────────────────────────────────────────────
    def subscribe(self, security_ids) -> None:
        self._subscriptions.update(str(s) for s in security_ids)

    def unsubscribe(self, security_ids) -> None:
        for s in security_ids:
            self._subscriptions.discard(str(s))

    @property
    def subscriptions(self) -> tuple:
        return tuple(sorted(self._subscriptions))

    # ── data access ─────────────────────────────────────────────────────────────
    @abstractmethod
    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        """Return every message knowable on/before `as_of` (historical/batch semantics)."""

    def poll(self, *, max_messages: int | None = None) -> list[SourceMessage]:
        """Streaming semantics: return the next available messages. Offline default: none.
        A streaming adapter overrides this to drain its deterministic buffer."""
        return []

    # ── health ──────────────────────────────────────────────────────────────────
    def health(self) -> AdapterHealthSample:
        return self._last or AdapterHealthSample(state=self._state,
                                                 subscriptions=self.subscriptions)

    def _record(self, messages: list[SourceMessage]) -> list[SourceMessage]:
        """Update health bookkeeping from an emitted batch. Deterministic — respects subscription
        filtering — and used by all concrete adapters."""
        if self._subscriptions:
            messages = [m for m in messages if m.security_hint in self._subscriptions
                        or m.msg_type in (MessageType.HEARTBEAT, MessageType.STATUS)]
        self._message_count += len(messages)
        last = messages[-1] if messages else None
        self._last = AdapterHealthSample(
            state=self._state, message_count=self._message_count, error_count=self._error_count,
            last_sequence=last.sequence if last else (self._last.last_sequence if self._last else None),
            last_observation_date=last.observation_date if last and last.observation_date
                                  else (self._last.last_observation_date if self._last else None),
            last_message_fingerprint=last.raw_fingerprint() if last else None,
            subscriptions=self.subscriptions)
        return messages


class CapabilityError(ValueError):
    pass


# ── concrete offline adapters ─────────────────────────────────────────────────

class LocalSourceAdapter(SourceAdapter):
    """Wraps an M19 `MarketDataSource` (Static/Historical/Mock) as an operational adapter. Its raw
    dicts become `SourceMessage`s; capabilities are declared by the caller. Fully offline."""

    def __init__(self, source: MarketDataSource, *, capabilities=None, name: str | None = None,
                 schema_version: str = "1.0") -> None:
        caps = frozenset(capabilities or (SourceCapability.HISTORICAL,))
        super().__init__(SourceMetadata(name or source.source, caps, schema_version,
                                        "M19 source wrapped as adapter", vendor=source.source))
        self._source = source
        self._seq = 0

    def connect(self) -> None:
        super().connect()

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        if self._state is not ConnectionState.CONNECTED:
            self.connect()
        raw = self._source.fetch(as_of, security_ids=security_ids, fields=fields)
        msgs = []
        for r in _stable_raw_order(raw):
            self._seq += 1
            msgs.append(_raw_to_message(r, self.metadata.name, self._seq, self.metadata.schema_version))
        return self._record(msgs)


class MessageLogAdapter(SourceAdapter):
    """Serves a fixed, ordered log of `SourceMessage`s. Backs the replay engine and fixtures:
    `fetch(as_of)` returns messages whose knowledge_date ≤ as_of; `poll` streams them in order."""

    def __init__(self, messages, *, metadata: SourceMetadata | None = None,
                 name: str = "message_log") -> None:
        super().__init__(metadata or SourceMetadata(
            name, frozenset((SourceCapability.HISTORICAL, SourceCapability.STREAMING)),
            description="Ordered message log"))
        self._messages = list(messages)
        self._cursor = 0

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        if self._state is not ConnectionState.CONNECTED:
            self.connect()
        out = [m for m in self._messages
               if (m.knowledge_date is None or m.knowledge_date <= as_of)
               and (security_ids is None or m.security_hint in set(map(str, security_ids)))
               and (fields is None or m.field_hint in set(fields))]
        return self._record(out)

    def poll(self, *, max_messages: int | None = None) -> list[SourceMessage]:
        if self._state is not ConnectionState.CONNECTED:
            self.connect()
        end = len(self._messages) if max_messages is None else min(len(self._messages),
                                                                   self._cursor + max_messages)
        out = self._messages[self._cursor:end]
        self._cursor = end
        return self._record(out)

    def reset(self) -> None:
        self._cursor = 0


class FixtureVendorAdapter(MessageLogAdapter):
    """A recorded vendor-shaped fixture log labelled with a vendor name — the substrate for offline
    vendor contract tests. Carries recorded payloads only; connects to nothing."""

    def __init__(self, vendor: str, messages, *, capabilities=None) -> None:
        caps = frozenset(capabilities or (SourceCapability.HISTORICAL, SourceCapability.QUOTES,
                                          SourceCapability.TRADES))
        super().__init__(messages, metadata=SourceMetadata(
            f"{vendor}.fixture", caps, description=f"Recorded {vendor} fixtures", vendor=vendor),
            name=f"{vendor}.fixture")


class ProductionSourceAdapter(SourceAdapter):
    """The live-vendor contract. Defines connect/subscribe/fetch/poll semantics a real connector
    must satisfy, but every transport method raises `NotImplementedError` with its unblock — no
    credentials, no network in this platform. Subclass, wire the transport, inherit the rest."""

    def __init__(self, name: str, capabilities, *, vendor: str = "", schema_version: str = "1.0") -> None:
        super().__init__(SourceMetadata(name, frozenset(capabilities), schema_version,
                                        "Production adapter contract (offline)", vendor=vendor))

    def connect(self) -> None:
        raise NotImplementedError(
            f"{self.metadata.name}: no live session in this offline platform. Unblock: implement "
            f"connect() against the vendor endpoint (auth + session); the runtime, ordering, "
            f"arbitration and reconstruction layers already consume what fetch()/poll() return.")

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        raise NotImplementedError(
            f"{self.metadata.name}: implement fetch() to pull raw records from the vendor and wrap "
            f"them as SourceMessage (use messages helpers); to_canonical/normalization already map "
            f"them to PIT-tagged observations.")

    def poll(self, *, max_messages: int | None = None) -> list[SourceMessage]:
        raise NotImplementedError(
            f"{self.metadata.name}: implement poll() to drain the live subscription buffer into "
            f"SourceMessage objects.")


# ── helpers ────────────────────────────────────────────────────────────────────

def _raw_to_message(r: dict, source: str, seq: int, schema_version: str) -> SourceMessage:
    return SourceMessage(source=source, payload=dict(r), sequence=seq, schema_version=schema_version,
                         vendor_id=(str(r.get("id")) if r.get("id") is not None else None))


def _stable_raw_order(raw):
    """Deterministic order for raw dicts that may arrive unordered, so wrapping into sequenced
    messages is reproducible regardless of the source's internal iteration order."""
    def k(r):
        return (str(r.get("observation_date") or r.get("date") or ""),
                str(r.get("id", r.get("security_id", ""))), str(r.get("field", r.get("type", ""))))
    return sorted(raw, key=k)
