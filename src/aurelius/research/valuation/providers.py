"""Market-data providers (AIDP M18).

`MarketDataProvider` ABC + deterministic, offline implementations. A provider's job is to
BUILD an immutable `MarketDataSnapshot` for a valuation date — the engine consumes the
snapshot, never the provider, so valuation can never "silently fetch live data". No network
dependency anywhere; `ProductionMarketDataAdapter` is the interface a real feed would
implement (left abstract on purpose — see docs).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from aurelius.research.valuation.models import MarketDataSnapshot, Provenance


class MarketDataProvider(ABC):
    """Interface for spot / rates / curves / FX / volatility / dividends / futures / bonds.

    The one required method is `snapshot(as_of)`; the typed accessors default to reading from
    a produced snapshot so subclasses only override what they source differently.
    """
    source: str = "provider"

    @abstractmethod
    def snapshot(self, as_of: date) -> MarketDataSnapshot: ...

    def spot(self, instrument_id: str, as_of: date) -> float:
        return self.snapshot(as_of).spot(instrument_id)

    def curve(self, curve_id: str, as_of: date):
        return self.snapshot(as_of).curve(curve_id)

    def vol_surface(self, surface_id: str, as_of: date):
        return self.snapshot(as_of).vol_surface(surface_id)

    def dividend_yield(self, instrument_id: str, as_of: date) -> float:
        return self.snapshot(as_of).dividend_yield(instrument_id)


class StaticMarketDataProvider(MarketDataProvider):
    """Wraps one fixed snapshot — returns it for any `as_of` (asserts date match if strict)."""

    def __init__(self, snapshot: MarketDataSnapshot, *, strict_date: bool = False,
                 source: str = "static") -> None:
        self._snap = snapshot
        self.strict_date = strict_date
        self.source = source

    def snapshot(self, as_of: date) -> MarketDataSnapshot:
        if self.strict_date and as_of != self._snap.as_of:
            raise ValueError(f"static snapshot is as_of {self._snap.as_of}, requested {as_of}")
        return self._snap


class HistoricalMarketDataProvider(MarketDataProvider):
    """Date-keyed snapshots; `snapshot(as_of)` returns the last observation on/before the date
    (point-in-time, no look-ahead). Raises if nothing is available."""

    def __init__(self, snapshots: dict, *, source: str = "historical") -> None:
        self._by_date = dict(sorted(snapshots.items()))     # date -> MarketDataSnapshot
        self.source = source

    def snapshot(self, as_of: date) -> MarketDataSnapshot:
        best = None
        for d, snap in self._by_date.items():
            if d <= as_of:
                best = snap
            else:
                break
        if best is None:
            raise LookupError(f"no market data on/before {as_of}")
        return best


class DeterministicMockMarketDataProvider(MarketDataProvider):
    """Pure-function synthetic snapshot for tests/benchmarks — reproducible from `as_of` and a
    seed map, no randomness that isn't seeded, no network."""

    def __init__(self, spots: dict, *, rates=None, vol_surfaces=None, dividend_yields=None,
                 fx_provider=None, source: str = "mock") -> None:
        self.spots = dict(spots)
        self.rates = dict(rates or {})
        self.vol_surfaces = dict(vol_surfaces or {})
        self.dividend_yields = dict(dividend_yields or {})
        self.fx_provider = fx_provider
        self.source = source

    def snapshot(self, as_of: date) -> MarketDataSnapshot:
        return MarketDataSnapshot(
            as_of=as_of, spots=self.spots, rates=self.rates,
            vol_surfaces=self.vol_surfaces, dividend_yields=self.dividend_yields,
            fx_provider=self.fx_provider,
            provenance=Provenance(source=self.source, observation_date=as_of,
                                  effective_date=as_of))


class ProductionMarketDataAdapter(MarketDataProvider):
    """Interface a real market-data feed implements. Left abstract — M18 ships no live feed
    (see docs, limitations). Implementers MUST return an immutable, PIT-tagged snapshot and
    MUST NOT let `as_of` observe future data."""

    @abstractmethod
    def snapshot(self, as_of: date) -> MarketDataSnapshot: ...
