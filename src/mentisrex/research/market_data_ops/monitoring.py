"""Operational data-quality, health & coverage monitoring (AIDP M20).

Composition over duplication: the individual quality *rules* live in M19 (`MarketDataQualityEngine`
and `diagnostics`). M20 aggregates them — plus ordering events and coverage — into machine-readable
operational reports an operator or an automated gate can act on.

Timing that needs a real clock (staleness in days, latency) takes an **injected** `as_of` date;
nothing here calls `datetime.now()`, so a historical health report is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from mentisrex.research.market_data.normalization import Normalizer
from mentisrex.research.market_data.quality import (
    MarketDataQualityEngine,
    QualityConfig,
)
from mentisrex.research.market_data_ops.messages import MessageType, SourceMessage
from mentisrex.research.market_data_ops.ordering import OrderingCode, OrderingReport


class FeedStatus(StrEnum):
    CONNECTED = "connected"
    DEGRADED = "degraded"  # elevated errors / gaps but still delivering
    STALE = "stale"  # no fresh data within the staleness window
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass(frozen=True)
class FeedHealth:
    source: str
    status: FeedStatus
    message_count: int = 0
    error_count: int = 0
    sequence_gaps: int = 0
    out_of_order: int = 0
    duplicates: int = 0
    last_observation_date: date | None = None
    last_knowledge_date: date | None = None
    staleness_days: int | None = None
    securities_seen: int = 0

    @property
    def healthy(self) -> bool:
        return self.status is FeedStatus.CONNECTED


class HealthMonitor:
    """Derives per-source `FeedHealth` from a message batch + optional ordering diagnostics.

    `stale_after_days`: a source with no message knowable within this many days of `as_of` is STALE.
    `degraded_error_frac`: fraction of anomalous messages above which a delivering source is DEGRADED.
    """

    def __init__(self, *, stale_after_days: int = 3, degraded_error_frac: float = 0.1) -> None:
        self.stale_after_days = stale_after_days
        self.degraded_error_frac = degraded_error_frac

    def assess(
        self,
        messages,
        *,
        as_of: date,
        ordering: OrderingReport | None = None,
        disconnected_sources=None,
    ) -> dict[str, FeedHealth]:
        disconnected = set(disconnected_sources or ())
        by_source: dict[str, list[SourceMessage]] = {}
        for m in messages:
            if m.msg_type in (MessageType.HEARTBEAT, MessageType.STATUS):
                continue
            by_source.setdefault(m.source, []).append(m)

        gap_by_src, ooo_by_src, dup_by_src = _ordering_counts(ordering)

        out: dict[str, FeedHealth] = {}
        for source in sorted(set(by_source) | disconnected):
            msgs = by_source.get(source, [])
            if source in disconnected and not msgs:
                out[source] = FeedHealth(source, FeedStatus.DISCONNECTED)
                continue
            last_obs = max((m.observation_date for m in msgs if m.observation_date), default=None)
            last_kd = max((m.knowledge_date for m in msgs if m.knowledge_date), default=None)
            staleness = None if last_kd is None else (as_of - last_kd).days
            gaps = gap_by_src.get(source, 0)
            ooo = ooo_by_src.get(source, 0)
            dups = dup_by_src.get(source, 0)
            anomalies = gaps + ooo
            frac = anomalies / len(msgs) if msgs else 0.0

            status = FeedStatus.CONNECTED
            if source in disconnected:
                status = FeedStatus.DISCONNECTED
            elif staleness is not None and staleness > self.stale_after_days:
                status = FeedStatus.STALE
            elif frac > self.degraded_error_frac:
                status = FeedStatus.DEGRADED

            out[source] = FeedHealth(
                source=source,
                status=status,
                message_count=len(msgs),
                error_count=anomalies,
                sequence_gaps=gaps,
                out_of_order=ooo,
                duplicates=dups,
                last_observation_date=last_obs,
                last_knowledge_date=last_kd,
                staleness_days=staleness,
                securities_seen=len({m.security_hint for m in msgs}),
            )
        return out


# ── coverage / completeness ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CoverageReport:
    expected_securities: int = 0
    observed_securities: int = 0
    missing_securities: tuple = ()
    expected_fields: int = 0
    missing_fields_by_security: dict = field(default_factory=dict)
    observed_dates: tuple = ()
    missing_dates: tuple = ()

    @property
    def security_coverage(self) -> float:
        return (
            0.0
            if not self.expected_securities
            else self.observed_securities / self.expected_securities
        )

    @property
    def complete(self) -> bool:
        return (
            not self.missing_securities
            and not self.missing_dates
            and not self.missing_fields_by_security
        )


def coverage(
    messages, *, expected_securities=None, expected_fields=None, expected_dates=None
) -> CoverageReport:
    """Report what's present vs expected. Missing data is never silently read as zero — it is
    listed. All three expectations are optional."""
    obs_secs: dict[str, set] = {}
    obs_dates: set = set()
    for m in messages:
        if m.msg_type in (MessageType.HEARTBEAT, MessageType.STATUS):
            continue
        sid = m.security_hint
        if sid is not None:
            obs_secs.setdefault(sid, set()).add(m.field_hint)
        if m.observation_date is not None:
            obs_dates.add(m.observation_date)

    exp_secs = (
        set(map(str, expected_securities)) if expected_securities is not None else set(obs_secs)
    )
    missing_secs = tuple(sorted(exp_secs - set(obs_secs)))

    missing_fields: dict = {}
    if expected_fields is not None:
        exp_fields = set(expected_fields)
        for sid in sorted(exp_secs):
            miss = exp_fields - obs_secs.get(sid, set())
            if miss:
                missing_fields[sid] = tuple(sorted(miss))

    missing_dates: tuple = ()
    if expected_dates is not None:
        missing_dates = tuple(sorted(set(expected_dates) - obs_dates))

    return CoverageReport(
        expected_securities=len(exp_secs),
        observed_securities=len(set(obs_secs) & exp_secs),
        missing_securities=missing_secs,
        expected_fields=len(expected_fields or ()),
        missing_fields_by_security=missing_fields,
        observed_dates=tuple(sorted(obs_dates)),
        missing_dates=missing_dates,
    )


# ── quality monitoring (composes the M19 engine) ─────────────────────────────────


@dataclass(frozen=True)
class QualityHealthReport:
    total: int = 0
    accepted: int = 0
    rejected: int = 0
    by_code: dict = field(default_factory=dict)
    by_severity: dict = field(default_factory=dict)

    @property
    def reject_rate(self) -> float:
        return 0.0 if not self.total else self.rejected / self.total


class QualityMonitor:
    """Runs the M19 quality engine over normalized messages and rolls the diagnostics into a
    machine-readable operational report. Does not re-implement any quality rule."""

    def __init__(
        self, *, normalizer: Normalizer | None = None, config: QualityConfig | None = None
    ) -> None:
        self.normalizer = normalizer or Normalizer()
        self.engine = MarketDataQualityEngine(config)

    def monitor(self, messages, *, as_of: date) -> QualityHealthReport:
        raw = [
            dict(m.payload)
            for m in messages
            if m.msg_type not in (MessageType.HEARTBEAT, MessageType.STATUS, MessageType.TOMBSTONE)
        ]
        norm = self.normalizer.normalize(raw, as_of=as_of)
        rep = self.engine.check(norm.observations, as_of=as_of)
        by_code: dict = {}
        by_sev: dict = {}
        for d in list(norm.diagnostics) + list(rep.diagnostics):
            by_code[d.code] = by_code.get(d.code, 0) + 1
            by_sev[d.severity.value] = by_sev.get(d.severity.value, 0) + 1
        return QualityHealthReport(
            total=len(norm.observations),
            accepted=len(rep.accepted),
            rejected=len(rep.rejected),
            by_code=by_code,
            by_severity=by_sev,
        )


def _ordering_counts(ordering: OrderingReport | None):
    gap: dict = {}
    ooo: dict = {}
    dup: dict = {}
    if ordering is None:
        return gap, ooo, dup
    for e in ordering.events:
        if e.code is OrderingCode.SEQUENCE_GAP:
            gap[e.source] = gap.get(e.source, 0) + 1
        elif e.code is OrderingCode.OUT_OF_ORDER:
            ooo[e.source] = ooo.get(e.source, 0) + 1
        elif e.code in (OrderingCode.DUPLICATE, OrderingCode.DUPLICATE_SEQUENCE):
            dup[e.source] = dup.get(e.source, 0) + 1
    return gap, ooo, dup
