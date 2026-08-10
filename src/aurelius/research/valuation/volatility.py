"""Volatility surface (AIDP M18).

`VolatilitySurface` — implied vol as a function of (strike, maturity), bilinearly interpolated,
immutable and PIT-tagged. `flat_surface` for the deterministic single-vol case. A
`VolatilityProvider` protocol lets the engine source vol without knowing the surface shape.
Staleness is checked against a valuation date.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from aurelius.research.valuation import interpolation as interp


@dataclass(frozen=True)
class VolatilitySurface:
    """grid[i][j] = implied vol at strikes[i], maturities[j] (maturities in years)."""
    surface_id: str
    ref_date: date
    strikes: tuple
    maturities: tuple
    grid: tuple                            # tuple of tuples, len(strikes) x len(maturities)
    extrap: interp.Extrapolation = interp.Extrapolation.FLAT

    def __post_init__(self):
        if len(self.grid) != len(self.strikes):
            raise ValueError("grid rows must match strikes")
        if any(len(row) != len(self.maturities) for row in self.grid):
            raise ValueError("grid cols must match maturities")

    def vol(self, strike: float, maturity: float) -> float:
        v = interp.bilinear(list(self.strikes), list(self.maturities),
                            [list(r) for r in self.grid], strike, maturity, extrap=self.extrap)
        if v <= 0:
            raise ValueError(f"interpolated vol <= 0 at K={strike}, T={maturity}")
        return v

    def is_stale(self, as_of: date, max_days: int) -> bool:
        return (as_of - self.ref_date).days > max_days

    def validate(self) -> list:
        problems = []
        for i, row in enumerate(self.grid):
            for j, v in enumerate(row):
                if v <= 0:
                    problems.append(f"{self.surface_id}: non-positive vol at "
                                    f"K={self.strikes[i]}, T={self.maturities[j]}")
        return problems

    def fingerprint(self) -> str:
        parts = [self.surface_id, str(self.ref_date)]
        parts += [f"{k:.6g}" for k in self.strikes] + [f"{m:.6g}" for m in self.maturities]
        parts += [f"{v:.8g}" for row in self.grid for v in row]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


def flat_surface(surface_id: str, ref_date: date, vol: float) -> VolatilitySurface:
    if vol <= 0:
        raise ValueError("vol must be > 0")
    return VolatilitySurface(surface_id, ref_date, (1.0, 1e9), (0.01, 100.0),
                             ((vol, vol), (vol, vol)))


class ConstantVolProvider:
    """Deterministic `VolatilityProvider` returning one vol regardless of strike/maturity."""

    def __init__(self, vol: float) -> None:
        self.vol = vol

    def implied_vol(self, instrument_id: str, strike: float, maturity: float) -> float:
        return self.vol


class SurfaceVolProvider:
    """`VolatilityProvider` backed by per-underlying `VolatilitySurface`s."""

    def __init__(self, surfaces: dict) -> None:
        self.surfaces = surfaces            # underlying_id -> VolatilitySurface

    def implied_vol(self, instrument_id: str, strike: float, maturity: float) -> float:
        surf = self.surfaces.get(instrument_id)
        if surf is None:
            raise KeyError(f"no vol surface for {instrument_id!r}")
        return surf.vol(strike, maturity)
