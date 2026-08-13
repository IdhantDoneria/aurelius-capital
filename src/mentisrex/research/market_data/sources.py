"""Market-data sources (AIDP M19).

A `MarketDataSource` yields **raw** records (vendor-shaped dicts) for a valuation date — the
entry to the pipeline, before normalization/quality/PIT. Keeping raw ingestion separate from the
M18 `MarketDataProvider` (which yields a *finished* immutable snapshot) is deliberate: sources are
where messy external schemas live, providers are the clean contract the valuation engine sees.

All sources here are offline and deterministic. A live feed implements `ProductionMarketDataAdapter`
(see `adapters.py`) — no source in this module makes a network call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date


class MarketDataSource(ABC):
    """Yields raw records (dicts) knowable on/before `as_of`. Normalization turns them canonical."""
    source: str = "source"

    @abstractmethod
    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[dict]: ...


def _filter(records: list[dict], security_ids, fields) -> list[dict]:
    sids = set(security_ids) if security_ids else None
    flds = set(fields) if fields else None
    out = []
    for r in records:
        if sids is not None and str(r.get("id", r.get("security_id"))) not in sids:
            continue
        if flds is not None and r.get("field") not in flds:
            continue
        out.append(r)
    return out


class StaticSource(MarketDataSource):
    """A fixed list of raw records, returned for any `as_of` (optionally PIT-filtered)."""
    source = "static"

    def __init__(self, records: list[dict], *, pit_filter: bool = True, source: str = "static") -> None:
        self._records = list(records)
        self.pit_filter = pit_filter
        self.source = source

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[dict]:
        recs = self._records
        if self.pit_filter:
            recs = [r for r in recs if _obs_date(r) is None or _obs_date(r) <= as_of]
        return _filter(recs, security_ids, fields)


class HistoricalSource(MarketDataSource):
    """Date-keyed raw records; `fetch(as_of)` returns every record knowable on/before `as_of`.
    Point-in-time: nothing dated after `as_of` is ever returned."""
    source = "historical"

    def __init__(self, by_date: dict, *, source: str = "historical") -> None:
        self._by_date = dict(sorted(by_date.items()))     # date -> list[dict]
        self.source = source

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[dict]:
        recs: list[dict] = []
        for d, day_recs in self._by_date.items():
            if d > as_of:
                break
            recs.extend(day_recs)
        return _filter(recs, security_ids, fields)


class DeterministicMockSource(MarketDataSource):
    """Pure-function synthetic raw records for tests/benchmarks. Reproducible from `as_of` and a
    seed map; no randomness that isn't seeded, no network."""
    source = "mock"

    def __init__(self, seeds: dict, *, currency: str = "USD", source: str = "mock") -> None:
        self._seeds = dict(seeds)                          # security_id -> base price
        self.currency = currency
        self.source = source

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[dict]:
        recs = []
        for sid, base in self._seeds.items():
            drift = (as_of.toordinal() % 100) / 100.0
            px = base * (1.0 + 0.001 * drift)
            recs.append({"id": sid, "id_type": "ticker", "type": "close", "field": "close",
                         "value": round(px, 6), "currency": self.currency, "unit": "price",
                         "observation_date": as_of, "effective_date": as_of, "source": self.source})
        return _filter(recs, security_ids, fields)


def _obs_date(r: dict):
    d = r.get("observation_date") or r.get("effective_date")
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d
