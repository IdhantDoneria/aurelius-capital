"""FX rate providers (AIDP M16).

Dependency-injected rate sources. A provider knows a *canonical* rate for the pairs it
covers and derives everything else deterministically: the inverse by reciprocal (so
`rate(A,B)·rate(B,A) == 1` to machine tolerance) and cross rates via a pivot currency.
No hardcoded market levels, no network — the offline/production split is an explicit
`ProductionFXRateAdapter` seam.

Convention (see `CurrencyPair`): `rate(base, quote)` = units of `quote` per unit of
`base`; converting an amount in `base` to `quote` multiplies by the rate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from mentisrex.research.fx.currency import validate_code
from mentisrex.research.fx.models import ConversionDirection, CurrencyPair, FXRate, FXRateSnapshot


class FXError(Exception):
    """Base class for FX rate errors."""


class MissingFXRateError(FXError, LookupError):
    pass


class StaleFXRateError(FXError):
    pass


class InvalidFXRateError(FXError, ValueError):
    pass


def _check_positive(rate: float, pair: str) -> float:
    if rate is None:
        raise MissingFXRateError(f"no rate for {pair}")
    if rate <= 0 or rate != rate:  # non-positive or NaN
        raise InvalidFXRateError(f"non-positive/NaN FX rate {rate!r} for {pair}")
    return rate


class FXRateProvider(ABC):
    """Base provider. Subclasses implement `_canonical`; direction/inversion/cross are
    resolved here so every provider shares the same, tested conventions."""

    source = "provider"
    pivot: str | None = None

    @abstractmethod
    def _canonical(self, base: str, quote: str, as_of: date | None) -> float | None:
        """Directly-known `quote per base`, or None if this provider must derive it."""

    def resolve(self, base, quote, *, as_of: date | None = None):
        """Return (rate, direction, source) converting `base`→`quote`."""
        base, quote = validate_code(base), validate_code(quote)
        if base == quote:
            return 1.0, ConversionDirection.IDENTITY, self.source
        r = self._canonical(base, quote, as_of)
        if r is not None:
            return _check_positive(r, f"{base}/{quote}"), ConversionDirection.DIRECT, self.source
        r = self._canonical(quote, base, as_of)
        if r is not None:
            return (
                1.0 / _check_positive(r, f"{quote}/{base}"),
                ConversionDirection.INVERSE,
                self.source,
            )
        p = self.pivot
        if p and p not in (base, quote):
            r1, _, _ = self.resolve(base, p, as_of=as_of)
            r2, _, _ = self.resolve(p, quote, as_of=as_of)
            return r1 * r2, ConversionDirection.CROSS, self.source
        raise MissingFXRateError(f"no rate {base}/{quote} as_of {as_of}")

    def rate(self, base, quote, *, as_of: date | None = None) -> float:
        return self.resolve(base, quote, as_of=as_of)[0]

    def spot(self, base, quote, *, as_of: date | None = None) -> FXRate:
        return FXRate(
            CurrencyPair(validate_code(base), validate_code(quote)),
            self.rate(base, quote, as_of=as_of),
            as_of,
            self.source,
        )

    def snapshot(self, currencies, base, *, as_of: date | None = None) -> FXRateSnapshot:
        base = validate_code(base)
        rates = {f"{validate_code(c)}/{base}": self.rate(c, base, as_of=as_of) for c in currencies}
        return FXRateSnapshot(as_of=as_of, base=base, rates=rates, source=self.source)


class StaticFXRateProvider(FXRateProvider):
    """Constant rates regardless of date. `rates` keyed 'EUR/USD' -> 1.10."""

    source = "static"

    def __init__(self, rates: dict, *, pivot: str | None = None) -> None:
        self._rates: dict = {}
        for k, v in rates.items():
            b, q = k.split("/")
            self._rates[(validate_code(b), validate_code(q))] = float(v)
        self.pivot = validate_code(pivot) if pivot else None

    def _canonical(self, base, quote, as_of):
        return self._rates.get((base, quote))


class HistoricalFXRateProvider(FXRateProvider):
    """As-of rates from a per-pair time series. `series` keyed 'EUR/USD' -> {date: rate}.
    `as_of` returns the last observation on/before the date; `max_staleness_days` raises
    `StaleFXRateError` when the nearest observation is older than allowed."""

    source = "historical"

    def __init__(
        self, series: dict, *, pivot: str | None = None, max_staleness_days: int | None = None
    ) -> None:
        self._series: dict = {}
        for k, dr in series.items():
            b, q = k.split("/")
            self._series[(validate_code(b), validate_code(q))] = dict(
                sorted((d, float(r)) for d, r in dr.items())
            )
        self.pivot = validate_code(pivot) if pivot else None
        self.max_staleness_days = max_staleness_days

    def _canonical(self, base, quote, as_of):
        s = self._series.get((base, quote))
        if not s:
            return None
        if as_of is None:
            return next(reversed(list(s.values())))
        best = None
        for d, r in s.items():
            if d <= as_of:
                best = (d, r)
            else:
                break
        if best is None:
            return None
        if self.max_staleness_days is not None and (as_of - best[0]).days > self.max_staleness_days:
            raise StaleFXRateError(
                f"{base}/{quote} rate as_of {as_of} is stale (last {best[0]}, "
                f"limit {self.max_staleness_days}d)"
            )
        return best[1]


class DeterministicMockFXProvider(FXRateProvider):
    """Deterministic, pure-function rates for tests and benchmarks — no randomness, no
    network. Canonical direction is always CCY/pivot; a reproducible date drift keeps
    inversion and cross exact because everything derives from one canonical number."""

    source = "mock"

    def __init__(self, base: str = "USD", *, seeds: dict | None = None, drift: float = 0.0) -> None:
        self.pivot = validate_code(base)
        self._seeds = {validate_code(k): float(v) for k, v in (seeds or {}).items()}
        self.drift = float(drift)

    def _canonical(self, base, quote, as_of):
        # canonical: base priced in the pivot (X/USD). Everything else derives.
        if quote == self.pivot and base != self.pivot:
            seed = self._seeds.get(base)
            if seed is None:
                seed = 1.0 + (sum(map(ord, base)) % 50) / 100.0
            if as_of is not None and self.drift:
                seed *= 1.0 + self.drift * (as_of.toordinal() % 100) / 100.0
            return seed
        return None


class ProductionFXRateAdapter(FXRateProvider):
    """DI extension point for a live rate feed (ECB/Bloomberg/Reuters). Interface only —
    this platform is offline. Unblock: implement `_canonical` against a real feed."""

    source = "production"
    pivot = None

    def _canonical(self, base, quote, as_of):
        raise NotImplementedError(
            "wire a production FX feed into ProductionFXRateAdapter._canonical"
        )
