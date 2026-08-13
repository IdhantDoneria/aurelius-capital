"""Multi-source arbitration & cross-source reconciliation (AIDP M20).

When two vendors quote the same instrument, someone must decide which value becomes state — and
that decision must be explicit, configurable and fingerprinted, never a hard-coded "trust
Bloomberg". `SourceArbiter` resolves conflicts per an `ArbitrationPolicy`; vendor priority is
plain configuration.

`reconcile` is the diagnostic sibling: it reports where sources *disagree* (price, FX, rate,
timestamp) without picking a winner, so an operator can see cross-source dispersion before any
policy collapses it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

from mentisrex.research.market_data_ops.messages import SourceMessage


class ArbitrationPolicy(str, Enum):
    PRIMARY_SOURCE = "primary_source"                # only the named primary source counts
    SOURCE_PRIORITY = "source_priority"              # first available in a priority list wins
    LATEST_VALID = "latest_valid"                    # newest knowledge_date wins
    CROSS_SOURCE_CONFIRMATION = "cross_source_confirmation"  # require ≥N sources within tolerance
    REJECT_ON_CONFLICT = "reject_on_conflict"        # any disagreement beyond tolerance → drop key


@dataclass(frozen=True)
class ArbitrationConfig:
    policy: ArbitrationPolicy = ArbitrationPolicy.SOURCE_PRIORITY
    priority: tuple = ()                 # source names, highest priority first
    primary: str | None = None
    tolerance_frac: float = 1e-6         # relative agreement tolerance
    min_confirmations: int = 2

    def fingerprint(self) -> str:
        parts = [self.policy.value, "|".join(self.priority), self.primary or "",
                 f"{self.tolerance_frac:.3e}", str(self.min_confirmations)]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


@dataclass(frozen=True)
class ArbitrationEvent:
    obs_key: tuple
    code: str                            # resolved | conflict | insufficient_confirmation | dropped
    winner_source: str | None
    detail: str = ""


@dataclass(frozen=True)
class ArbitrationResult:
    winners: tuple = ()                  # one SourceMessage per resolved key
    dropped: tuple = ()                  # keys dropped by REJECT_ON_CONFLICT / no winner
    events: tuple = ()
    policy_fingerprint: str = ""


class SourceArbiter:
    def __init__(self, config: ArbitrationConfig | None = None) -> None:
        self.config = config or ArbitrationConfig()

    def arbitrate(self, messages) -> ArbitrationResult:
        cfg = self.config
        groups: dict[tuple, list[SourceMessage]] = {}
        for m in messages:
            groups.setdefault(_key(m), []).append(m)

        winners: list[SourceMessage] = []
        dropped: list[tuple] = []
        events: list[ArbitrationEvent] = []

        for key in sorted(groups, key=lambda k: tuple(str(x) for x in k)):
            cands = groups[key]
            winner, code, detail = self._resolve(key, cands)
            if winner is None:
                dropped.append(key)
                events.append(ArbitrationEvent(key, code, None, detail))
            else:
                winners.append(winner)
                if len(cands) > 1:
                    events.append(ArbitrationEvent(key, code, winner.source, detail))
        return ArbitrationResult(tuple(winners), tuple(dropped), tuple(events), cfg.fingerprint())

    def _resolve(self, key, cands):
        cfg = self.config
        if cfg.policy is ArbitrationPolicy.PRIMARY_SOURCE:
            pri = [c for c in cands if c.source == cfg.primary]
            if pri:
                return _newest(pri), "resolved", f"primary {cfg.primary}"
            return None, "dropped", f"no primary source {cfg.primary!r} for key"

        if cfg.policy is ArbitrationPolicy.SOURCE_PRIORITY:
            for src in cfg.priority:
                match = [c for c in cands if c.source == src]
                if match:
                    return _newest(match), "resolved", f"priority {src}"
            # no configured priority matched → deterministic fallback: newest, then source name
            return _newest(cands), "resolved", "priority fallback (newest)"

        if cfg.policy is ArbitrationPolicy.LATEST_VALID:
            return _newest(cands), "resolved", "latest knowledge_date"

        if cfg.policy is ArbitrationPolicy.CROSS_SOURCE_CONFIRMATION:
            agree = _largest_agreeing_cluster(cands, cfg.tolerance_frac)
            if len({c.source for c in agree}) >= cfg.min_confirmations:
                return _newest(agree), "resolved", f"{len(agree)} sources confirm"
            return None, "insufficient_confirmation", \
                f"only {len({c.source for c in cands})} sources, need {cfg.min_confirmations}"

        if cfg.policy is ArbitrationPolicy.REJECT_ON_CONFLICT:
            if _all_agree(cands, cfg.tolerance_frac):
                return _newest(cands), "resolved", "sources agree"
            return None, "conflict", "sources disagree beyond tolerance"

        raise ValueError(f"unknown arbitration policy {cfg.policy!r}")


# ── cross-source reconciliation (diagnostic, no winner picked) ─────────────────

@dataclass(frozen=True)
class Disagreement:
    obs_key: tuple
    sources: tuple                       # (source, value) pairs
    max_rel_diff: float
    kind: str                            # value | timestamp | presence


@dataclass(frozen=True)
class ReconciliationReport:
    disagreements: tuple = ()
    agreed_keys: int = 0
    total_keys: int = 0

    @property
    def ok(self) -> bool:
        return not self.disagreements


def reconcile(messages, *, tolerance_frac: float = 1e-6) -> ReconciliationReport:
    """Report cross-source value disagreements per observation key. Does not resolve them."""
    groups: dict[tuple, list[SourceMessage]] = {}
    for m in messages:
        groups.setdefault(_key(m), []).append(m)
    diffs: list[Disagreement] = []
    agreed = 0
    for key in sorted(groups, key=lambda k: tuple(str(x) for x in k)):
        cands = groups[key]
        srcs = {c.source for c in cands}
        if len(srcs) < 2:
            agreed += 1
            continue
        vals = [(c.source, _value(c)) for c in cands if _value(c) is not None]
        numeric = [v for _, v in vals]
        if numeric and _all_agree(cands, tolerance_frac):
            agreed += 1
            continue
        mx = _max_rel_diff(numeric)
        diffs.append(Disagreement(key, tuple(sorted(vals)), mx, "value"))
    return ReconciliationReport(tuple(diffs), agreed, len(groups))


# ── helpers ────────────────────────────────────────────────────────────────────

def _key(m: SourceMessage) -> tuple:
    return (m.security_hint, m.field_hint, m.effective_date)


def _value(m: SourceMessage):
    v = m.payload.get("value") if isinstance(m.payload, dict) else None
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _newest(cands):
    from datetime import date, datetime
    return max(cands, key=lambda c: (c.knowledge_date or date.min,
                                     c.source_timestamp or datetime.min,
                                     -1 if c.sequence is None else c.sequence, c.source))


def _all_agree(cands, tol) -> bool:
    vals = [_value(c) for c in cands]
    vals = [v for v in vals if v is not None]
    return _max_rel_diff(vals) <= tol


def _max_rel_diff(vals) -> float:
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return 0.0
    lo, hi = min(vals), max(vals)
    scale = max(abs(lo), abs(hi), 1e-12)
    return (hi - lo) / scale


def _largest_agreeing_cluster(cands, tol):
    """The biggest subset whose values agree within tolerance. O(n²) over candidates for one key —
    candidate counts per key are tiny (number of sources), so this is fine."""
    best: list = []
    for anchor in cands:
        av = _value(anchor)
        if av is None:
            continue
        cluster = [c for c in cands if _value(c) is not None
                   and abs(_value(c) - av) <= tol * max(abs(av), 1e-12)]
        if len(cluster) > len(best):
            best = cluster
    return best or list(cands)
