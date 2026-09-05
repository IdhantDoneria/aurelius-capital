"""Credit curves (AIDP M19).

A `CreditCurve` carries a piecewise-constant hazard-rate term structure and derives survival /
default probability and an approximate par credit spread from it. `bootstrap_credit` calibrates
the hazard curve from par CDS spreads by sequential bootstrap against an injected discount curve
(M18 `ZeroCurve`) — deterministic, one hazard node per CDS maturity, each solved so its CDS
prices to zero on a discrete premium grid. Survival is monotone non-increasing and hazards are
constrained non-negative.

This is a deterministic bootstrap *interface*, not a full ISDA-standard CDS pricer (accrual-on-
default, upfront/points-running conversion, and the ISDA calendar are out of scope — see docs
limitations). It is the seam a production CDS calibration slots behind.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from mentisrex.research.valuation.curves import ZeroCurve
from mentisrex.research.valuation.registry import CalibrationDiagnostics, CurveCalibrationReport


@dataclass(frozen=True)
class CreditCurve:
    curve_id: str
    tenors: tuple  # increasing year-fractions, hazard node ends
    hazards: tuple  # piecewise-constant hazard rate on (t_{i-1}, t_i]
    recovery: float = 0.4
    currency: str = "USD"

    def __post_init__(self):
        if len(self.tenors) != len(self.hazards) or not self.tenors:
            raise ValueError("tenors/hazards must be non-empty and equal length")
        if list(self.tenors) != sorted(self.tenors):
            raise ValueError("tenors must be increasing")
        if any(h < 0 for h in self.hazards):
            raise ValueError("hazard rates must be >= 0 (no negative default intensity)")

    def _cum_hazard(self, t: float) -> float:
        if t <= 0:
            return 0.0
        total, prev = 0.0, 0.0
        for ti, hi in zip(self.tenors, self.hazards, strict=False):
            seg = min(t, ti) - prev
            if seg > 0:
                total += hi * seg
            prev = ti
            if t <= ti:
                return total
        total += self.hazards[-1] * (t - self.tenors[-1])  # flat extrapolation
        return total

    def survival(self, t: float) -> float:
        return math.exp(-self._cum_hazard(t))

    def default_prob(self, t: float) -> float:
        return 1.0 - self.survival(t)

    def hazard(self, t: float) -> float:
        for ti, hi in zip(self.tenors, self.hazards, strict=False):
            if t <= ti:
                return hi
        return self.hazards[-1]

    def par_spread(self, t: float) -> float:
        """Credit-triangle approximation s ≈ hazard·(1−R) — a diagnostic, not the bootstrap target."""
        return self.hazard(t) * (1.0 - self.recovery)

    def fingerprint(self) -> str:
        parts = [self.curve_id, f"R={self.recovery:.6g}"]
        parts += [f"{t:.6g}:{h:.10g}" for t, h in zip(self.tenors, self.hazards, strict=False)]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


@dataclass(frozen=True)
class CDSQuote:
    tenor: float  # years
    spread: float  # par spread, decimal (0.01 == 100bp)
    frequency: int = 4  # premium payments per year


def _cds_pv(spread, tenor, freq, hazards_tenors, hazards, disc: ZeroCurve, recovery, ref):
    """Premium leg − protection leg on a discrete grid. Zero at the par spread."""
    curve = CreditCurve("_tmp", tuple(hazards_tenors), tuple(hazards), recovery)
    n = max(1, round(tenor * freq))
    dt = tenor / n
    prem = prot = 0.0
    prev_surv, _prev_t = 1.0, 0.0
    for j in range(1, n + 1):
        t = j * dt
        df = disc.discount(t)
        surv = curve.survival(t)
        prem += spread * dt * df * surv  # premium on surviving notional
        prot += (1.0 - recovery) * df * (prev_surv - surv)  # protection on default in period
        prev_surv, _prev_t = surv, t
    return prem - prot


def bootstrap_credit(
    quotes,
    disc: ZeroCurve,
    *,
    recovery: float = 0.4,
    curve_id: str = "credit",
    currency: str = "USD",
    ref=None,
    tol: float = 1e-12,
    strict: bool = True,
):
    """Sequential hazard bootstrap from par CDS spreads. Returns (CreditCurve, report)."""
    qs = sorted(quotes, key=lambda q: q.tenor)
    if not qs:
        raise ValueError("no CDS quotes to bootstrap")
    tenors: list[float] = []
    hazards: list[float] = []
    for q in qs:

        def f(h, _q=q):
            return _cds_pv(
                _q.spread,
                _q.tenor,
                _q.frequency,
                [*tenors, _q.tenor],
                [*hazards, h],
                disc,
                recovery,
                ref,
            )

        h = _bisect_pos(f, 1e-9, 5.0, tol=tol)
        tenors.append(q.tenor)
        hazards.append(h)
    curve = CreditCurve(curve_id, tuple(tenors), tuple(hazards), recovery, currency)
    residuals = tuple(
        (
            f"CDS@{q.tenor:g}y",
            _cds_pv(
                q.spread, q.tenor, q.frequency, curve.tenors, curve.hazards, disc, recovery, ref
            ),
        )
        for q in qs
    )
    max_res = max((abs(r) for _, r in residuals), default=0.0)
    problems = tuple(f"{n}: PV residual {r:.2e}" for n, r in residuals if abs(r) > 1e-8)
    report = CurveCalibrationReport(
        curve_id,
        CalibrationDiagnostics(max_res, len(qs), not problems),
        tuple(n for n, _ in residuals),
        problems,
    )
    if strict and problems:
        raise ValueError(f"credit curve {curve_id} failed to calibrate: {problems[0]}")
    return curve, report


def _bisect_pos(f, lo, hi, *, tol=1e-12, max_iter=200):
    flo, fhi = f(lo), f(hi)
    tries = 0
    while flo * fhi > 0 and tries < 30:
        hi *= 2.0
        fhi = f(hi)
        tries += 1
    if flo * fhi > 0:
        raise ValueError("could not bracket hazard root")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < tol or (hi - lo) < tol:
            return mid
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi, fhi = mid, fm
    return 0.5 * (lo + hi)
