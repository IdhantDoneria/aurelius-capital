"""Deterministic serialization for the operations layer (AIDP M20).

Source messages and sealed-snapshot envelopes → JSON and back, with stable key ordering and
fingerprint-preserving round-trips. Reuses the M19/M15 `to_json`/`_clean` conventions so an
identical artifact serializes byte-identically. `message_from_dict` re-checks the stored
`raw_fingerprint` against the rehydrated message and raises on mismatch — corrupt/tampered artifact
detection.

The full M18 snapshot is deliberately *not* serialized here: it is reproduced from the message log
by the reconstructor, and its fingerprint travels in the sealed envelope for integrity. Persisting
the message log (fully round-trippable) plus the envelope is the honest reproducibility boundary.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from aurelius.research.market_data_ops.lifecycle import SealedSnapshot, SnapshotState
from aurelius.research.market_data_ops.messages import MessageType, SourceMessage
from aurelius.research.market_data_ops.store import _envelope


class DeserializationError(ValueError):
    pass


# ── source messages ─────────────────────────────────────────────────────────────

def message_to_dict(m: SourceMessage) -> dict:
    return {
        "source": m.source, "payload": _clean_payload(m.payload), "msg_type": m.msg_type.value,
        "vendor_id": m.vendor_id, "sequence": m.sequence,
        "source_timestamp": m.source_timestamp.isoformat() if m.source_timestamp else None,
        "receive_timestamp": m.receive_timestamp.isoformat() if m.receive_timestamp else None,
        "observation_date": m.observation_date.isoformat() if m.observation_date else None,
        "effective_date": m.effective_date.isoformat() if m.effective_date else None,
        "schema_version": m.schema_version, "meta": dict(m.meta),
        "raw_fingerprint": m.raw_fingerprint(),
    }


def message_from_dict(d: dict, *, verify: bool = True) -> SourceMessage:
    m = SourceMessage(
        source=d["source"], payload=dict(d["payload"]),
        msg_type=MessageType(d.get("msg_type", "observation")), vendor_id=d.get("vendor_id"),
        sequence=d.get("sequence"),
        source_timestamp=_dt(d.get("source_timestamp")),
        receive_timestamp=_dt(d.get("receive_timestamp")),
        observation_date=_d(d.get("observation_date")),
        effective_date=_d(d.get("effective_date")),
        schema_version=d.get("schema_version", "1.0"), meta=dict(d.get("meta") or {}))
    if verify and "raw_fingerprint" in d and m.raw_fingerprint() != d["raw_fingerprint"]:
        raise DeserializationError(
            f"message fingerprint mismatch: stored {d['raw_fingerprint']} != {m.raw_fingerprint()} "
            f"(corrupt or tampered artifact)")
    return m


def messages_to_json(messages, *, indent: int = 2) -> str:
    return json.dumps([message_to_dict(m) for m in messages], indent=indent,
                      sort_keys=True, default=str)


def messages_from_json(text: str, *, verify: bool = True) -> list[SourceMessage]:
    return [message_from_dict(d, verify=verify) for d in json.loads(text)]


# ── sealed snapshot envelope ─────────────────────────────────────────────────────

def sealed_to_dict(s: SealedSnapshot) -> dict:
    return _envelope(s)


def sealed_to_json(s: SealedSnapshot, *, indent: int = 2) -> str:
    return json.dumps(_envelope(s), indent=indent, sort_keys=True)


def sealed_envelope_from_json(text: str) -> dict:
    """Rehydrate the envelope metadata (not the M18 snapshot object). Reconstruct from the message
    log to rebuild the snapshot itself; the stored `snapshot_fingerprint` verifies the rebuild."""
    d = json.loads(text)
    if "snapshot_id" not in d or "snapshot_fingerprint" not in d:
        raise DeserializationError("sealed envelope missing snapshot_id/fingerprint")
    d["_state"] = SnapshotState(d["state"])
    return d


# ── helpers ────────────────────────────────────────────────────────────────────

def _clean_payload(p):
    if not isinstance(p, dict):
        return p
    out = {}
    for k, v in p.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _dt(v):
    return datetime.fromisoformat(v) if v else None


def _d(v):
    return date.fromisoformat(v) if v else None
