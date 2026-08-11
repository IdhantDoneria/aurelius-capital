"""Market-data validators (AIDP M19).

Composable validators over the M19 artifacts. Each `validate(...)` returns a list of problem
strings (empty == clean) — the same convention M18 uses — so a caller can gate on emptiness or
surface findings. They reuse M18/M19 diagnostics rather than re-deriving them: curve positivity
and discontinuity come from M18, PIT from M18's `validate_pit`, arbitrage from the shared
diagnostics module.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.market_data import diagnostics as diag
from aurelius.research.market_data.models import Severity
from aurelius.research.valuation.snapshot import validate_pit


class MarketDataValidator:
    """Observation-level: PIT, unit/currency presence, value finiteness."""

    def validate(self, observations, *, as_of: date) -> list:
        problems = []
        for o in observations:
            if o.value is None or o.value != o.value:
                problems.append(f"{o.security_id}.{o.field}: missing/NaN value")
            m = diag.look_ahead(o.observation_date, as_of)
            if m:
                problems.append(f"{o.security_id}.{o.field}: {m}")
            if o.currency is None and o.unit.value == "price":
                problems.append(f"{o.security_id}.{o.field}: price without currency")
        return problems


class CurveValidator:
    """Zero/discount curve invariants: DF > 0, no large discontinuities."""

    def __init__(self, *, jump_tol: float = 0.05, tmax: float = 30.0) -> None:
        self.jump_tol = jump_tol
        self.tmax = tmax

    def validate(self, curve) -> list:
        problems = list(curve.validate())
        problems += diag.negative_discount_factors(curve)
        tmax = min(self.tmax, float(curve.tenors[-1]))
        problems += diag.curve_discontinuities(curve, tmax=tmax, jump_tol=self.jump_tol)
        return problems


class CalibrationValidator:
    """A calibration report reprices within tolerance and converged."""

    def __init__(self, *, tol: float = 1e-6) -> None:
        self.tol = tol

    def validate(self, report) -> list:
        problems = list(report.problems)
        if report.diagnostics.max_repricing_error > self.tol:
            problems.append(f"{report.curve_id}: max repricing error "
                            f"{report.diagnostics.max_repricing_error:.2e} > {self.tol:.0e}")
        if not report.diagnostics.converged:
            problems.append(f"{report.curve_id}: calibration did not converge")
        return problems


class VolatilitySurfaceValidator:
    """Surface positivity + calendar-spread monotonicity across its own maturities."""

    def validate(self, surface) -> list:
        problems = list(surface.validate())
        for k in surface.strikes:
            for a, b in zip(surface.maturities, surface.maturities[1:]):
                problems += diag.calendar_spread(surface, k, a, b)
        return problems


class SnapshotValidator:
    """A built M18 snapshot is PIT-safe and complete for the requested instruments."""

    def validate(self, snapshot, *, required_spots=(), max_staleness_days=None) -> list:
        problems = validate_pit(snapshot, max_staleness_days=max_staleness_days)
        for sid in required_spots:
            if sid not in snapshot.spots:
                problems.append(f"missing required spot {sid!r}")
        return problems
