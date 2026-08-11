"""Deterministic market-data replay (AIDP M20).

Replays a historical message log as if it were arriving through a source, in canonical order, over
a date range — with no wall-clock dependence (a `speed` abstraction is metadata only; tests never
sleep). At each replay date it can reconstruct the PIT snapshot Aurelius would have held, and it
emits a cumulative **replay fingerprint** so an entire replay is reproducible from its inputs.

The engine reuses `HistoricalReconstructor` for the per-date state, which is why replaying to date
T yields byte-identical state to reconstructing directly at T (proven in the tests): both are the
same pure function of the same admissible message set.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from aurelius.research.market_data_ops.messages import SourceMessage
from aurelius.research.market_data_ops.ordering import _order_key
from aurelius.research.market_data_ops.reconstruction import (
    HistoricalReconstructor,
    ReconstructionResult,
)


@dataclass(frozen=True)
class ReplayConfig:
    start: date | None = None
    end: date | None = None
    dates: tuple = ()                    # explicit replay dates; empty → distinct knowledge dates
    sources: tuple = ()                  # source filter; empty → all
    security_ids: tuple = ()             # security filter; empty → all
    fields: tuple = ()                   # field filter; empty → all
    knowledge_lag_days: int = 0          # knowledge boundary = valuation_date + lag
    speed: float = 0.0                   # metadata only — 0 == as-fast-as-possible, no sleeping


@dataclass(frozen=True)
class ReplayCheckpoint:
    valuation_date: date
    knowledge_date: date
    emitted: int                         # cumulative messages emitted through this date
    cumulative_fingerprint: str
    reconstruction: ReconstructionResult | None = None


@dataclass(frozen=True)
class ReplayResult:
    checkpoints: tuple = ()
    replay_fingerprint: str = ""
    total_emitted: int = 0

    def snapshot_on(self, d: date):
        for c in self.checkpoints:
            if c.valuation_date == d and c.reconstruction is not None:
                return c.reconstruction.snapshot
        return None


class MarketDataReplayEngine:
    def __init__(self, messages, *, reconstructor: HistoricalReconstructor | None = None) -> None:
        self._messages = list(messages)
        self.reconstructor = reconstructor or HistoricalReconstructor()

    def replay(self, config: ReplayConfig | None = None, *, reconstruct: bool = True,
               curves=None, discount_curves=None, vol_surfaces=None, dividend_yields=None,
               forwards=None, fx_provider=None) -> ReplayResult:
        cfg = config or ReplayConfig()
        pool = self._filter(cfg)
        dates = self._replay_dates(pool, cfg)

        checkpoints: list[ReplayCheckpoint] = []
        h = hashlib.blake2b(digest_size=16)
        emitted_fps: set = set()
        total = 0
        for vd in dates:
            kd = vd if cfg.knowledge_lag_days == 0 else _add_days(vd, cfg.knowledge_lag_days)
            # newly-knowable messages since the last checkpoint, in canonical order
            newly = sorted((m for m in pool
                            if _knowable(m, kd) and m.raw_fingerprint() not in emitted_fps),
                           key=_order_key)
            for m in newly:
                emitted_fps.add(m.raw_fingerprint())
                h.update(m.raw_fingerprint().encode())
            total += len(newly)
            rec = None
            if reconstruct:
                rec = self.reconstructor.reconstruct(
                    pool, valuation_date=vd, knowledge_date=kd, curves=curves,
                    discount_curves=discount_curves, vol_surfaces=vol_surfaces,
                    dividend_yields=dividend_yields, forwards=forwards, fx_provider=fx_provider,
                    security_ids=cfg.security_ids or None, fields=cfg.fields or None)
            checkpoints.append(ReplayCheckpoint(vd, kd, total, h.hexdigest(), rec))
        return ReplayResult(tuple(checkpoints), h.hexdigest(), total)

    # ── selection ────────────────────────────────────────────────────────────────
    def _filter(self, cfg: ReplayConfig):
        srcs = set(cfg.sources) or None
        sids = set(map(str, cfg.security_ids)) or None
        flds = set(cfg.fields) or None
        out = []
        for m in self._messages:
            if srcs is not None and m.source not in srcs:
                continue
            if sids is not None and m.security_hint not in sids:
                continue
            if flds is not None and m.field_hint not in flds:
                continue
            out.append(m)
        return out

    def _replay_dates(self, pool, cfg: ReplayConfig):
        if cfg.dates:
            ds = sorted(set(cfg.dates))
        else:
            ds = sorted({m.knowledge_date for m in pool if m.knowledge_date is not None})
        if cfg.start is not None:
            ds = [d for d in ds if d >= cfg.start]
        if cfg.end is not None:
            ds = [d for d in ds if d <= cfg.end]
        return ds


def _knowable(m: SourceMessage, kd: date) -> bool:
    mk = m.knowledge_date
    return mk is None or mk <= kd


def _add_days(d: date, n: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=n)
