"""Valuation domain models (AIDP M18).

Frozen dataclasses only. The core rule of M18 lives here: every valuation is reproducible
from Instrument + MarketDataSnapshot + ValuationDate + ValuationConfiguration. Nothing in
this package fetches live data — the snapshot is injected, immutable, point-in-time tagged
and provenance-stamped, and a `ValuationResult` carries the model/version/fingerprints that
make the number auditable and reproducible.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime

from aurelius.research.valuation.daycount import Compounding, DayCount


# ── provenance & point-in-time ───────────────────────────────────────────────

@dataclass(frozen=True)
class Provenance:
    """Where a datum came from and when it was seen — the PIT audit stamp."""
    source: str = "unknown"
    observation_date: date | None = None     # when the value was observed
    effective_date: date | None = None       # when the value is effective/for
    timestamp: datetime | None = None
    currency: str | None = None
    instrument_id: str | None = None


@dataclass(frozen=True)
class MarketQuote:
    """One observed number with its PIT metadata."""
    instrument_id: str
    value: float
    currency: str = "USD"
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    provenance: Provenance = field(default_factory=Provenance)

    @property
    def mid(self) -> float:
        if self.bid is not None and self.ask is not None:
            return 0.5 * (self.bid + self.ask)
        return self.value


# ── valuation configuration ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ValuationConfiguration:
    """Model & convention choices that, with the snapshot, fully determine a valuation."""
    base_currency: str = "USD"
    day_count: DayCount = DayCount.ACT_365
    compounding: Compounding = Compounding.CONTINUOUS
    max_staleness_days: int | None = None     # reject data older than this vs valuation date
    allow_extrapolation: bool = True
    equity_model: str = "spot"
    option_model: str = "black_scholes"       # black_scholes | black_76 | binomial
    american_steps: int = 200
    fd_bump: float = 1e-4                      # finite-difference bump for numerical Greeks

    def fingerprint(self) -> str:
        parts = [self.base_currency, self.day_count.value, self.compounding.value,
                 str(self.max_staleness_days), str(self.allow_extrapolation),
                 self.equity_model, self.option_model, str(self.american_steps)]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


# ── market data snapshot ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class MarketDataSnapshot:
    """Immutable, point-in-time set of market inputs. `as_of` is the valuation date; every
    datum should not be observed after it (look-ahead is rejected by `snapshot.validate_pit`).

    FX is NOT duplicated — an M16 `FXRateProvider` is injected via `fx_provider`. Curves and
    vol surfaces are stored by id and are themselves immutable M18 objects.
    """
    as_of: date
    spots: dict = field(default_factory=dict)              # id -> float (or MarketQuote)
    rates: dict = field(default_factory=dict)              # curve_id -> ZeroCurve
    discount_factors: dict = field(default_factory=dict)   # curve_id -> DiscountCurve (optional)
    forwards: dict = field(default_factory=dict)           # id -> forward price
    dividend_yields: dict = field(default_factory=dict)    # id -> continuous div yield
    vol_surfaces: dict = field(default_factory=dict)       # id -> VolatilitySurface
    corporate_actions: dict = field(default_factory=dict)  # id -> assumption dict
    fx_provider: object = None                             # M16 FXRateProvider
    provenance: Provenance = field(default_factory=Provenance)
    quotes: dict = field(default_factory=dict)             # id -> MarketQuote (bid/ask/volume)

    # ── accessors (raise on missing so nothing is silently defaulted) ───────────
    def spot(self, instrument_id: str) -> float:
        v = self.spots.get(instrument_id)
        if v is None:
            raise KeyError(f"no spot for {instrument_id!r} in snapshot as_of {self.as_of}")
        return v.mid if isinstance(v, MarketQuote) else float(v)

    def dividend_yield(self, instrument_id: str) -> float:
        return float(self.dividend_yields.get(instrument_id, 0.0))

    def forward(self, instrument_id: str) -> float:
        v = self.forwards.get(instrument_id)
        if v is None:
            raise KeyError(f"no forward for {instrument_id!r}")
        return float(v)

    def curve(self, curve_id: str):
        c = self.rates.get(curve_id)
        if c is None:
            raise KeyError(f"no curve {curve_id!r} in snapshot")
        return c

    def vol_surface(self, surface_id: str):
        s = self.vol_surfaces.get(surface_id)
        if s is None:
            raise KeyError(f"no vol surface {surface_id!r} in snapshot")
        return s

    def fx_rate(self, base: str, quote: str) -> float:
        if base == quote:
            return 1.0
        if self.fx_provider is None:
            raise ValueError("snapshot has no fx_provider (M16) for FX conversion")
        return self.fx_provider.rate(base, quote, as_of=self.as_of)

    def fingerprint(self) -> str:
        # immutable snapshot → the fingerprint is stable; cache it (frozen dataclass, so set
        # through object.__setattr__). Turns per-instrument portfolio valuation from O(n·|snap|)
        # into O(n).
        cached = self.__dict__.get("_fp")
        if cached is not None:
            return cached
        h = hashlib.blake2b(digest_size=16)
        h.update(str(self.as_of).encode())
        for k in sorted(self.spots):
            h.update(f"S:{k}={self.spot(k):.10g}".encode())
        for k in sorted(self.dividend_yields):
            h.update(f"D:{k}={self.dividend_yields[k]:.10g}".encode())
        for k in sorted(self.forwards):
            h.update(f"F:{k}={float(self.forwards[k]):.10g}".encode())
        for k in sorted(self.rates):
            h.update(f"C:{k}={self.rates[k].fingerprint()}".encode())
        for k in sorted(self.vol_surfaces):
            h.update(f"V:{k}={self.vol_surfaces[k].fingerprint()}".encode())
        h.update(f"P:{self.provenance.source}".encode())
        fp = h.hexdigest()
        object.__setattr__(self, "_fp", fp)
        return fp


# ── valuation result ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Greeks:
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    vanna: float = 0.0
    volga: float = 0.0

    def scale(self, f: float) -> "Greeks":
        return Greeks(self.delta * f, self.gamma * f, self.theta * f, self.vega * f,
                      self.rho * f, self.vanna * f, self.volga * f)

    def __add__(self, o: "Greeks") -> "Greeks":
        return Greeks(self.delta + o.delta, self.gamma + o.gamma, self.theta + o.theta,
                      self.vega + o.vega, self.rho + o.rho, self.vanna + o.vanna,
                      self.volga + o.volga)


@dataclass(frozen=True)
class ValuationResult:
    instrument_id: str
    valuation_date: date
    price: float                          # per-unit theoretical price / NPV per contract
    market_value: float                   # price * quantity * contract_size (position value)
    currency: str
    base_value: float                     # market_value converted to config.base_currency
    model_name: str
    model_version: str
    input_fingerprint: str
    market_data_fingerprint: str
    quantity: float = 0.0
    pnl: float = 0.0                       # unrealized vs supplied cost basis
    greeks: Greeks | None = None
    valuation_adjustments: dict = field(default_factory=dict)
    assumptions: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)

    @property
    def reproducible_key(self) -> str:
        return f"{self.model_name}@{self.model_version}:{self.input_fingerprint}:{self.market_data_fingerprint}"


@dataclass(frozen=True)
class PortfolioValuation:
    valuation_date: date
    base_currency: str
    gross_market_value: float
    net_market_value: float
    base_value: float
    unrealized_pnl: float
    results: list = field(default_factory=list)      # list[ValuationResult]
    greeks: Greeks | None = None
    risk_inputs: dict = field(default_factory=dict)
    market_data_fingerprint: str = ""
