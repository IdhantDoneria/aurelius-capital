"""Ordering & sequence management (AIDP M20).

Real feeds do not arrive clean: messages come out of order, duplicated, with gaps or repeated
sequence numbers, late or stale. M20 makes the handling of each an **explicit, fingerprinted
policy** — never a hidden heuristic. Every decision (dropped duplicate, reordered message,
quarantined late arrival, detected gap) is recorded as an `OrderingEvent` so the audit trail
survives.

The default `REORDER` policy is deterministic and order-independent: the same multiset of messages
yields the same accepted sequence regardless of arrival order. That property is what makes
incremental ingestion provably equal to a full rebuild (M20 §4.8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from mentisrex.research.market_data_ops.messages import MessageType, SourceMessage


class OrderingPolicy(StrEnum):
    STRICT = "strict"  # sequence must be strictly increasing; violation is an error
    REJECT = "reject"  # drop anything out-of-order/late; keep the in-order prefix
    BUFFER = "buffer"  # keep everything, do not reorder (report anomalies only)
    REORDER = "reorder"  # deterministically sort into canonical order (default)
    LATEST_VALID = "latest_valid"  # per key keep only the newest valid message
    QUARANTINE = "quarantine"  # divert offending messages to a quarantine list


class OrderingCode(StrEnum):
    DUPLICATE = "duplicate"
    DUPLICATE_SEQUENCE = "duplicate_sequence"
    OUT_OF_ORDER = "out_of_order"
    SEQUENCE_GAP = "sequence_gap"
    MISSING_SEQUENCE = "missing_sequence"
    LATE = "late"
    STALE = "stale"
    REORDERED = "reordered"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class OrderingEvent:
    code: OrderingCode
    message_fingerprint: str
    source: str
    detail: str = ""


@dataclass(frozen=True)
class OrderingReport:
    accepted: tuple = ()  # messages that passed, in canonical order
    quarantined: tuple = ()  # diverted messages (QUARANTINE policy)
    dropped: tuple = ()  # messages removed (duplicates / REJECT policy)
    events: tuple = ()

    @property
    def event_counts(self) -> dict:
        out: dict = {}
        for e in self.events:
            out[e.code.value] = out.get(e.code.value, 0) + 1
        return out


class SequenceManager:
    """Applies an `OrderingPolicy` to a batch of messages from one or many sources.

    `stale_boundary` (an injected date, never a clock) flags messages knowable before it as stale.
    `late_boundary` flags messages arriving after processing has advanced past their knowledge date.
    Sequence gaps/duplicates are tracked per source.
    """

    def __init__(
        self, policy: OrderingPolicy = OrderingPolicy.REORDER, *, stale_boundary: date | None = None
    ) -> None:
        self.policy = policy
        self.stale_boundary = stale_boundary

    def process(self, messages) -> OrderingReport:
        msgs = list(messages)
        events: list[OrderingEvent] = []

        # 1. duplicate removal by content fingerprint — order-independent, always applied
        deduped = self._dedup(msgs, events)

        # 2. per-source sequence + staleness diagnostics (no drops yet)
        self._diagnose_sequences(deduped, events)
        self._diagnose_stale(deduped, events)

        # 3. policy application
        if self.policy is OrderingPolicy.REORDER:
            accepted = self._canonical_sort(deduped)
            if [m.raw_fingerprint() for m in accepted] != [m.raw_fingerprint() for m in deduped]:
                events.append(
                    OrderingEvent(
                        OrderingCode.REORDERED,
                        "",
                        "",
                        f"{len(accepted)} messages sorted to canonical order",
                    )
                )
            return OrderingReport(
                tuple(accepted), (), tuple(self._dropped(msgs, deduped)), tuple(events)
            )

        if self.policy is OrderingPolicy.BUFFER:
            return OrderingReport(
                tuple(deduped), (), tuple(self._dropped(msgs, deduped)), tuple(events)
            )

        if self.policy is OrderingPolicy.LATEST_VALID:
            accepted = self._latest_valid(deduped)
            return OrderingReport(
                tuple(self._canonical_sort(accepted)),
                (),
                tuple(self._dropped(msgs, accepted)),
                tuple(events),
            )

        if self.policy in (OrderingPolicy.REJECT, OrderingPolicy.STRICT, OrderingPolicy.QUARANTINE):
            return self._reject_or_quarantine(msgs, deduped, events)

        raise ValueError(f"unknown ordering policy {self.policy!r}")

    # ── steps ────────────────────────────────────────────────────────────────────
    def _dedup(self, msgs, events) -> list[SourceMessage]:
        seen: dict[str, SourceMessage] = {}
        for m in msgs:
            fp = m.raw_fingerprint()
            if fp in seen:
                events.append(
                    OrderingEvent(OrderingCode.DUPLICATE, fp, m.source, "identical message")
                )
            else:
                seen[fp] = m
        # deterministic: preserve canonical order for reproducibility across arrival orders
        return list(seen.values())

    def _diagnose_sequences(self, msgs, events) -> None:
        by_source: dict[str, list[SourceMessage]] = {}
        for m in msgs:
            if m.sequence is None:
                if m.msg_type not in (MessageType.HEARTBEAT, MessageType.STATUS):
                    events.append(
                        OrderingEvent(
                            OrderingCode.MISSING_SEQUENCE,
                            m.raw_fingerprint(),
                            m.source,
                            "no sequence number",
                        )
                    )
                continue
            by_source.setdefault(m.source, []).append(m)
        for source, seq_msgs in by_source.items():
            ordered = sorted(seq_msgs, key=lambda m: (m.sequence, m.raw_fingerprint()))
            seen_seq: set = set()
            prev = None
            for m in ordered:
                if m.sequence in seen_seq:
                    events.append(
                        OrderingEvent(
                            OrderingCode.DUPLICATE_SEQUENCE,
                            m.raw_fingerprint(),
                            source,
                            f"sequence {m.sequence} repeated",
                        )
                    )
                seen_seq.add(m.sequence)
                if prev is not None and m.sequence > prev + 1:
                    events.append(
                        OrderingEvent(
                            OrderingCode.SEQUENCE_GAP,
                            m.raw_fingerprint(),
                            source,
                            f"gap {prev}->{m.sequence}",
                        )
                    )
                prev = m.sequence if prev is None else max(prev, m.sequence)
        # arrival-order out-of-order detection (informational)
        self._diagnose_arrival_order(msgs, events)

    def _diagnose_arrival_order(self, msgs, events) -> None:
        prev = None
        for m in msgs:
            k = _order_key(m)
            if prev is not None and k < prev:
                events.append(
                    OrderingEvent(
                        OrderingCode.OUT_OF_ORDER,
                        m.raw_fingerprint(),
                        m.source,
                        "arrived before an earlier-keyed message",
                    )
                )
            prev = k if prev is None else max(prev, k)

    def _diagnose_stale(self, msgs, events) -> None:
        # "stale" = the datum is *for* a date well before the boundary, however recently it
        # arrived — so the observation date is the right axis, not knowledge date.
        if self.stale_boundary is None:
            return
        for m in msgs:
            od = m.observation_date
            if od is not None and od < self.stale_boundary:
                events.append(
                    OrderingEvent(
                        OrderingCode.STALE,
                        m.raw_fingerprint(),
                        m.source,
                        f"observation_date {od} < boundary {self.stale_boundary}",
                    )
                )

    def _canonical_sort(self, msgs) -> list[SourceMessage]:
        return sorted(msgs, key=_order_key)

    def _latest_valid(self, msgs) -> list[SourceMessage]:
        best: dict[tuple, SourceMessage] = {}
        for m in msgs:
            k = _obs_key(m)
            cur = best.get(k)
            if cur is None or _order_key(m) > _order_key(cur):
                best[k] = m
        return list(best.values())

    def _reject_or_quarantine(self, original, deduped, events) -> OrderingReport:
        """Keep the in-order prefix by canonical key; divert the rest per policy."""
        self._canonical_sort(deduped)
        accepted: list[SourceMessage] = []
        offending: list[SourceMessage] = []
        prev = None
        # process in *arrival* order so "out of order" is meaningful for REJECT/STRICT
        for m in deduped:
            k = _order_key(m)
            if prev is not None and k < prev:
                offending.append(m)
                events.append(
                    OrderingEvent(
                        OrderingCode.QUARANTINED
                        if self.policy is OrderingPolicy.QUARANTINE
                        else OrderingCode.LATE,
                        m.raw_fingerprint(),
                        m.source,
                        "out-of-order arrival",
                    )
                )
                if self.policy is OrderingPolicy.STRICT:
                    raise OrderingError(f"STRICT ordering violated at {m.source} seq={m.sequence}")
            else:
                accepted.append(m)
                prev = k if prev is None else max(prev, k)
        accepted = self._canonical_sort(accepted)
        if self.policy is OrderingPolicy.QUARANTINE:
            return OrderingReport(
                tuple(accepted),
                tuple(offending),
                tuple(self._dropped(original, deduped)),
                tuple(events),
            )
        return OrderingReport(
            tuple(accepted),
            (),
            tuple(list(self._dropped(original, deduped)) + offending),
            tuple(events),
        )

    def _dropped(self, original, kept):
        {id(m) for m in kept}
        keep_fps = {m.raw_fingerprint() for m in kept}
        out = []
        seen = set()
        for m in original:
            fp = m.raw_fingerprint()
            if fp not in keep_fps and fp not in seen:
                out.append(m)
            seen.add(fp)
        return out


class OrderingError(ValueError):
    pass


# ── ordering keys ──────────────────────────────────────────────────────────────


def _order_key(m: SourceMessage):
    """Canonical total order: (source_timestamp, knowledge/observation date, sequence, fingerprint).
    Total and deterministic — the fingerprint tie-breaker guarantees a stable sort."""
    ts = m.source_timestamp or datetime.min
    kd = m.knowledge_date or date.min
    seq = -1 if m.sequence is None else m.sequence
    return (ts, kd, seq, m.raw_fingerprint())


def _obs_key(m: SourceMessage):
    """Identity of what a message observes — (security, field, effective_date) — for LATEST_VALID."""
    return (m.security_hint, m.field_hint, m.effective_date)
