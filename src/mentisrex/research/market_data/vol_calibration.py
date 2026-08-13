"""Volatility-surface calibration (AIDP M19).

M18 *interpolated* a supplied vol grid; M19 *fits* one. `VolatilitySurfaceCalibrator` calibrates
each expiry's smile with a DI-selected model — SABR, SVI, or plain interpolation — and then
**materializes an M18 `VolatilitySurface`** (a strike×maturity grid) so every downstream M18
consumer works unchanged. It is bid/ask-aware (calibrates to mids, flags fitted vols outside the
quoted spread) and runs the no-arbitrage diagnostics: negative variance, per-smile butterfly
(SVI Durrleman g), and calendar-spread monotonicity across expiries (reusing M18's check).

A `CalibratedVolProvider` implements the M18 `VolatilityProvider` protocol directly from the
parametric smiles, for callers that want the model rather than a materialized grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from mentisrex.research.market_data.sabr import SABRCalibration, calibrate_sabr
from mentisrex.research.market_data.svi import SVICalibration, calibrate_svi
from mentisrex.research.valuation import diagnostics as vdiag
from mentisrex.research.valuation.volatility import VolatilitySurface


class VolModel(str, Enum):
    INTERPOLATED = "interpolated"
    SABR = "sabr"
    SVI = "svi"


@dataclass(frozen=True)
class SmileQuotes:
    """One expiry's market smile. `forward` and `expiry` (years) frame the strikes."""
    forward: float
    expiry: float
    strikes: tuple
    vols: tuple                            # implied vols (mids if bids/asks given)
    bids: tuple | None = None
    asks: tuple | None = None
    underlying: str = ""


@dataclass(frozen=True)
class CalibratedSmile:
    expiry: float
    model: VolModel
    params: object                         # SABRParams | SVIParams | None (interpolated)
    max_residual: float
    rmse: float
    diagnostics: tuple = ()

    def vol(self, strike: float, forward: float) -> float:
        raise NotImplementedError                          # bound below via _SmileFn


@dataclass(frozen=True)
class _SmileFn:
    expiry: float
    model: VolModel
    fn: object                             # callable(strike) -> vol
    calib: CalibratedSmile

    def vol(self, strike: float) -> float:
        return self.fn(strike)


@dataclass(frozen=True)
class SurfaceCalibrationReport:
    surface_id: str
    smiles: tuple = ()                     # CalibratedSmile per expiry
    diagnostics: tuple = ()
    max_residual: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.diagnostics


class VolatilitySurfaceCalibrator:
    def __init__(self, model: VolModel = VolModel.SVI, *, beta: float = 0.5) -> None:
        self.model = VolModel(model)
        self.beta = beta

    # ── one smile ─────────────────────────────────────────────────────────────
    def calibrate_smile(self, smile: SmileQuotes) -> _SmileFn:
        f, t = smile.forward, smile.expiry
        strikes, vols = list(smile.strikes), list(smile.vols)
        diags: list[str] = []
        if self.model is VolModel.SABR:
            cal = calibrate_sabr(f, t, strikes, vols, beta=self.beta)
            fn = lambda k, _c=cal, _f=f, _t=t: _c.params.vol(_f, k, _t)
            calib = CalibratedSmile(t, VolModel.SABR, cal.params, cal.max_residual, cal.rmse,
                                    tuple(cal.params.validate()))
        elif self.model is VolModel.SVI:
            ks = [math.log(k / f) for k in strikes]
            w = [v * v * t for v in vols]
            cal = calibrate_svi(ks, w)
            fn = lambda k, _c=cal, _f=f, _t=t: _c.params.vol(math.log(k / _f), _t)
            calib = CalibratedSmile(t, VolModel.SVI, cal.params, cal.max_residual, cal.rmse,
                                    tuple(cal.params.validate()) + cal.arbitrage)
        else:
            fn = _interp_fn(strikes, vols)
            calib = CalibratedSmile(t, VolModel.INTERPOLATED, None, 0.0, 0.0, ())
        diags += self._bid_ask_flags(smile, fn)
        calib = CalibratedSmile(calib.expiry, calib.model, calib.params, calib.max_residual,
                                calib.rmse, calib.diagnostics + tuple(diags))
        return _SmileFn(t, self.model, fn, calib)

    def _bid_ask_flags(self, smile: SmileQuotes, fn) -> list:
        if not smile.bids or not smile.asks:
            return []
        out = []
        for k, b, a in zip(smile.strikes, smile.bids, smile.asks):
            v = fn(k)
            if v < b - 1e-9 or v > a + 1e-9:
                out.append(f"fitted vol {v:.4f} outside [{b:.4f},{a:.4f}] at K={k}")
        return out

    # ── full surface ──────────────────────────────────────────────────────────
    def calibrate_surface(self, smiles, surface_id: str, ref_date: date, *, strikes=None):
        smiles = sorted(smiles, key=lambda s: s.expiry)
        if not smiles:
            raise ValueError("no smiles to calibrate")
        fitted = [self.calibrate_smile(s) for s in smiles]
        if strikes is None:
            strikes = sorted({k for s in smiles for k in s.strikes})
        maturities = [s.expiry for s in smiles]
        # grid[i][j] = vol at strikes[i], maturities[j]
        grid = tuple(tuple(fitted[j].vol(k) for j in range(len(maturities))) for k in strikes)
        surface = VolatilitySurface(surface_id, ref_date, tuple(strikes), tuple(maturities), grid)

        diags: list[str] = []
        for sm in fitted:
            diags.extend(sm.calib.diagnostics)
        diags.extend(surface.validate())                   # negative-vol guard
        for k in strikes:                                  # calendar-spread across expiries
            for a, b in zip(maturities, maturities[1:]):
                diags.extend(vdiag.calendar_spread(surface, k, a, b))
        max_res = max((sm.calib.max_residual for sm in fitted), default=0.0)
        report = SurfaceCalibrationReport(surface_id, tuple(s.calib for s in fitted),
                                          tuple(diags), max_res)
        return surface, report, CalibratedVolProvider({smiles[0].underlying or surface_id: fitted})


class CalibratedVolProvider:
    """Implements the M18 `VolatilityProvider` protocol from parametric smiles (per underlying).
    Interpolates linearly in total variance across expiries."""

    def __init__(self, smiles_by_underlying: dict) -> None:
        self._smiles = {u: sorted(fs, key=lambda s: s.expiry)
                        for u, fs in smiles_by_underlying.items()}

    def implied_vol(self, instrument_id: str, strike: float, maturity: float) -> float:
        fs = self._smiles.get(instrument_id)
        if not fs:
            raise KeyError(f"no calibrated smiles for {instrument_id!r}")
        exps = [s.expiry for s in fs]
        if maturity <= exps[0]:
            return fs[0].vol(strike)
        if maturity >= exps[-1]:
            return fs[-1].vol(strike)
        for lo, hi in zip(fs, fs[1:]):
            if lo.expiry <= maturity <= hi.expiry:
                w_lo = lo.vol(strike) ** 2 * lo.expiry
                w_hi = hi.vol(strike) ** 2 * hi.expiry
                frac = (maturity - lo.expiry) / (hi.expiry - lo.expiry)
                w = w_lo + frac * (w_hi - w_lo)
                return math.sqrt(max(w, 1e-12) / maturity)
        return fs[-1].vol(strike)


def _interp_fn(strikes, vols):
    from mentisrex.research.valuation.interpolation import Extrapolation, linear
    xs, ys = list(strikes), list(vols)
    return lambda k: linear(xs, ys, k, extrap=Extrapolation.FLAT)
