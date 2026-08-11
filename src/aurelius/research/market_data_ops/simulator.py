"""Deterministic streaming simulator with fault injection (AIDP M20).

How M20 proves operational robustness without paid data: generate a clean synthetic feed, then
inject controlled faults — duplicates, drops, reordering, delays, revisions, stale prints,
malformed records, sequence gaps and cross-source conflicts. Every choice is driven by a *seeded*
`random.Random`, so a given (seed, FaultSpec) always yields the identical message stream. No
wall-clock, no network, no uncontrolled randomness.

The output is a `list[SourceMessage]` ready for the ordering, arbitration, reconstruction and
monitoring layers — the fault-injection harness the adversarial tests run against.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from aurelius.research.market_data_ops.messages import (
    MessageType,
    SourceMessage,
)


@dataclass(frozen=True)
class FaultSpec:
    duplicate_frac: float = 0.0       # fraction of messages re-emitted as exact duplicates
    drop_frac: float = 0.0            # fraction of messages dropped
    reorder: bool = False            # shuffle arrival order (canonical order still recoverable)
    delay_days: int = 0              # shift source_timestamp later (late arrival)
    revision_frac: float = 0.0       # fraction of observations that get a later restatement
    stale_frac: float = 0.0          # fraction emitted with an old observation_date
    malformed_frac: float = 0.0      # fraction with a missing/bad value
    sequence_gaps: bool = False      # skip some sequence numbers
    conflict_sources: tuple = ()     # extra sources that quote a *different* value for some keys
    conflict_frac: float = 0.0       # fraction of keys that get a conflicting cross-source quote


@dataclass(frozen=True)
class SimConfig:
    seeds: dict = field(default_factory=dict)   # security_id -> base price
    start: date = date(2024, 1, 2)
    days: int = 5
    source: str = "sim"
    currency: str = "USD"
    seed: int = 0


class StreamingSimulator:
    def __init__(self, config: SimConfig) -> None:
        self.config = config

    def generate(self, faults: FaultSpec | None = None) -> list[SourceMessage]:
        cfg = self.config
        faults = faults or FaultSpec()
        rng = random.Random(cfg.seed)

        base = self._clean_feed(rng)
        stream = self._inject(base, faults, rng)
        # conflicts add cross-source variants keyed to the same observation
        stream += self._conflicts(base, faults, rng)
        if faults.reorder:
            rng.shuffle(stream)
        return stream

    # ── base feed ────────────────────────────────────────────────────────────────
    def _clean_feed(self, rng) -> list[SourceMessage]:
        cfg = self.config
        msgs: list[SourceMessage] = []
        seq = 0
        for i in range(cfg.days):
            d = cfg.start + timedelta(days=i)
            for sid in sorted(cfg.seeds):
                seq += 1
                px = round(cfg.seeds[sid] * (1.0 + 0.001 * i), 6)
                msgs.append(self._obs(sid, "close", px, d, seq))
        return msgs

    def _obs(self, sid, field, value, d, seq, *, source=None, ts=None,
             obs_date=None) -> SourceMessage:
        cfg = self.config
        obs_date = obs_date or d
        return SourceMessage(
            source=source or cfg.source,
            payload={"id": sid, "id_type": "ticker", "field": field, "type": "close",
                     "value": value, "currency": cfg.currency, "unit": "price",
                     "observation_date": obs_date.isoformat(), "effective_date": d.isoformat(),
                     "source": source or cfg.source},
            msg_type=MessageType.OBSERVATION, vendor_id=sid, sequence=seq,
            source_timestamp=ts or datetime(d.year, d.month, d.day, 16, 0, 0),
            observation_date=obs_date, effective_date=d)

    # ── fault injection ────────────────────────────────────────────────────────────
    def _inject(self, base, faults: FaultSpec, rng) -> list[SourceMessage]:
        out: list[SourceMessage] = []
        gap_seq = 0
        for m in base:
            if faults.drop_frac and rng.random() < faults.drop_frac:
                continue

            msg = m
            if faults.sequence_gaps and rng.random() < 0.3:
                gap_seq += 2
                msg = _replace_seq(msg, (msg.sequence or 0) + gap_seq)

            if faults.stale_frac and rng.random() < faults.stale_frac:
                old = (msg.observation_date or self.config.start) - timedelta(days=10)
                msg = _restamp(msg, observation_date=old)

            if faults.malformed_frac and rng.random() < faults.malformed_frac:
                msg = _malform(msg)

            if faults.delay_days and rng.random() < 0.5:
                ts = (msg.source_timestamp or datetime(2024, 1, 2)) + timedelta(days=faults.delay_days)
                msg = _restamp(msg, source_timestamp=ts)

            out.append(msg)

            if faults.duplicate_frac and rng.random() < faults.duplicate_frac:
                out.append(msg)

            if (faults.revision_frac and msg.msg_type is MessageType.OBSERVATION
                    and rng.random() < faults.revision_frac):
                out.append(self._revision(msg, rng))
        return out

    def _revision(self, m: SourceMessage, rng) -> SourceMessage:
        payload = dict(m.payload)
        payload["value"] = round(float(payload["value"]) * (1.0 + 0.0005), 6)
        payload["revision"] = int(payload.get("revision", 0)) + 1
        kd = (m.observation_date or self.config.start) + timedelta(days=1)
        return SourceMessage(
            source=m.source, payload=payload, msg_type=MessageType.REVISION,
            vendor_id=m.vendor_id, sequence=(m.sequence or 0),
            source_timestamp=datetime(kd.year, kd.month, kd.day, 16, 0, 0),
            observation_date=kd, effective_date=m.effective_date)

    def _conflicts(self, base, faults: FaultSpec, rng) -> list[SourceMessage]:
        if not faults.conflict_sources or not faults.conflict_frac:
            return []
        out: list[SourceMessage] = []
        for m in base:
            if m.msg_type is not MessageType.OBSERVATION:
                continue
            if rng.random() >= faults.conflict_frac:
                continue
            for src in faults.conflict_sources:
                payload = dict(m.payload)
                payload["value"] = round(float(payload["value"]) * (1.0 + 0.02), 6)  # 2% disagreement
                payload["source"] = src
                out.append(SourceMessage(
                    source=src, payload=payload, msg_type=MessageType.OBSERVATION,
                    vendor_id=m.vendor_id, sequence=m.sequence,
                    source_timestamp=m.source_timestamp,
                    observation_date=m.observation_date, effective_date=m.effective_date))
        return out


# ── message mutators (return new frozen messages) ────────────────────────────────

def _replace_seq(m: SourceMessage, seq: int) -> SourceMessage:
    from dataclasses import replace
    return replace(m, sequence=seq)


def _restamp(m: SourceMessage, *, observation_date=None, source_timestamp=None) -> SourceMessage:
    from dataclasses import replace
    payload = dict(m.payload)
    if observation_date is not None:
        payload["observation_date"] = observation_date.isoformat()
    return replace(m, payload=payload,
                   observation_date=observation_date or m.observation_date,
                   source_timestamp=source_timestamp or m.source_timestamp)


def _malform(m: SourceMessage) -> SourceMessage:
    from dataclasses import replace
    payload = dict(m.payload)
    payload["value"] = "n/a"          # non-numeric → normalization rejects it, not silently coerced
    return replace(m, payload=payload)
