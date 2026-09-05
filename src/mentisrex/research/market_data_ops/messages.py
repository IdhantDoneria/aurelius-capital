"""Feed-message model (AIDP M20).

M19 works in `CanonicalObservation` — the clean, typed datum *after* normalization. M20 sits one
layer earlier, at the wire: a `SourceMessage` is one immutable record exactly as a source/vendor
handed it over, preserving raw identity (vendor id, sequence number, source & receive timestamps,
schema version, raw payload) so transformation problems can be *diagnosed* rather than silently
lost. Collapsing wire identity into `CanonicalObservation` too early throws away precisely the
metadata M20 needs for ordering, arbitration, health and replay.

A message carries its own `raw_fingerprint` (stable content hash) and a `knowledge_date` — the
day the value became *knowable* through this source. `knowledge_date` is the PIT axis M20
reconstructs against: nothing a message made knowable after a reconstruction's knowledge boundary
may enter that reconstructed state.

Deterministic and offline: no wall-clock is read here. `receive_timestamp` is whatever the caller
injects (a simulator clock, a recorded value, or None) — never `datetime.now()`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum


class MessageType(StrEnum):
    OBSERVATION = "observation"  # a market datum (trade/quote/close/rate/...) in `payload`
    REVISION = "revision"  # an explicit restatement of a prior observation
    TOMBSTONE = "tombstone"  # a deletion of a prior observation (key in payload)
    HEARTBEAT = "heartbeat"  # liveness only, no datum
    REFERENCE = "reference"  # reference/static data (identifiers, corp actions)
    STATUS = "status"  # source status/control message


class SourceCapability(StrEnum):
    """What a source is able to serve. A source declares its capability set; callers gate on it
    instead of assuming every vendor exposes identical semantics."""

    HISTORICAL = "historical"
    STREAMING = "streaming"
    QUOTES = "quotes"
    TRADES = "trades"
    BARS = "bars"
    REFERENCE_DATA = "reference_data"
    CORPORATE_ACTIONS = "corporate_actions"
    RATES = "rates"
    FX = "fx"
    OPTIONS = "options"
    CURVES = "curves"
    VOLATILITY = "volatility"
    FUNDAMENTALS = "fundamentals"


@dataclass(frozen=True)
class SourceMessage:
    """One immutable record as received from a source, before normalization.

    `payload` is the raw vendor-shaped dict (an M19 `Normalizer` accepts it directly). Wire
    identity — `source`, `vendor_id`, `sequence`, `source_timestamp`, `receive_timestamp`,
    `schema_version` — is preserved alongside it. `observation_date` is when the value was
    knowable, `effective_date` the date it is for; either may be None and be inferred from the
    payload.
    """

    source: str
    payload: dict
    msg_type: MessageType = MessageType.OBSERVATION
    vendor_id: str | None = None
    sequence: int | None = None
    source_timestamp: datetime | None = None
    receive_timestamp: datetime | None = None
    observation_date: date | None = None
    effective_date: date | None = None
    schema_version: str = "1.0"
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Fill observation/effective dates from the payload when the wire omitted them, so PIT
        # ordering always has a knowability axis. Never reads a clock.
        if self.observation_date is None:
            d = _payload_date(self.payload, "observation_date", "date", "asof")
            if d is None and self.source_timestamp is not None:
                d = self.source_timestamp.date()
            if d is not None:
                object.__setattr__(self, "observation_date", d)
        if self.effective_date is None:
            eff = _payload_date(self.payload, "effective_date") or self.observation_date
            if eff is not None:
                object.__setattr__(self, "effective_date", eff)

    @property
    def knowledge_date(self) -> date | None:
        """The day this message made its value knowable — the PIT axis for reconstruction.
        Prefers the source timestamp's date, falls back to the observation date."""
        if self.source_timestamp is not None:
            return self.source_timestamp.date()
        return self.observation_date

    @property
    def security_hint(self) -> str | None:
        p = self.payload
        v = p.get("id", p.get("security_id")) if isinstance(p, dict) else None
        return None if v is None else str(v)

    @property
    def field_hint(self) -> str | None:
        p = self.payload
        v = p.get("field", p.get("type")) if isinstance(p, dict) else None
        return None if v is None else str(v)

    def raw_fingerprint(self) -> str:
        """Stable content hash of the message identity + payload — the dedup key and the unit
        replay/reconstruction fingerprints are folded over. Deterministic across processes."""
        cached = self.__dict__.get("_fp")
        if cached is not None:
            return cached
        parts = [
            self.source,
            self.msg_type.value,
            self.vendor_id or "",
            "" if self.sequence is None else str(self.sequence),
            self.source_timestamp.isoformat() if self.source_timestamp else "",
            self.observation_date.isoformat() if self.observation_date else "",
            self.effective_date.isoformat() if self.effective_date else "",
            self.schema_version,
            json.dumps(self.payload, sort_keys=True, default=str),
        ]
        fp = hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()
        object.__setattr__(self, "_fp", fp)
        return fp

    def with_receive_timestamp(self, ts: datetime) -> SourceMessage:
        return replace(self, receive_timestamp=ts)


def _payload_date(payload, *keys):
    if not isinstance(payload, dict):
        return None
    for k in keys:
        v = payload.get(k)
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            try:
                return date.fromisoformat(v[:10])
            except ValueError:
                continue
    return None


def message_from_observation(
    obs,
    *,
    source: str | None = None,
    sequence: int | None = None,
    source_timestamp: datetime | None = None,
) -> SourceMessage:
    """Wrap an M19 `CanonicalObservation` back into a wire message — used by the replay engine to
    re-emit stored observations as if they arrived from a source."""
    payload = {
        "id": obs.security_id,
        "field": obs.field,
        "type": obs.obs_type.value,
        "value": obs.value,
        "currency": obs.currency,
        "unit": obs.unit.value,
        "observation_date": obs.observation_date.isoformat(),
        "effective_date": obs.effective_date.isoformat(),
        "source": obs.source,
        "revision": obs.revision,
        **({} if not obs.meta else dict(obs.meta)),
    }
    return SourceMessage(
        source=source or obs.source,
        payload=payload,
        msg_type=MessageType.REVISION if obs.revision else MessageType.OBSERVATION,
        vendor_id=obs.security_id,
        sequence=sequence,
        source_timestamp=source_timestamp or obs.timestamp,
        observation_date=obs.observation_date,
        effective_date=obs.effective_date,
    )
