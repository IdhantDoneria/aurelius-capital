"""Multi-instrument curve bootstrapping (AIDP M19).

The M18 deferred item: `CurveBuilder.build_zero` took (tenor, zero) nodes directly; this builds a
zero curve from *market instruments* — deposits, OIS, FRAs, futures and par swaps — by sequential
bootstrap. Instruments are sorted by maturity; each node's zero rate is solved (deterministic
bisection) so that instrument reprices to its quote given the shorter end already built. The
result is a **reused M18 `ZeroCurve`** plus a `CurveCalibrationReport` carrying per-instrument
repricing residuals. A curve that cannot reprice its inputs within tolerance is reported not-ok
(and, in strict mode, raised) — never silently accepted.

Conventions are injected on each `RateInstrument`. Convexity for futures and OIS/LIBOR basis are
explicitly out of scope here (see multicurve.py / docs); futures are treated as forward-rate
agreements on their accrual period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mentisrex.research.market_data.rate_instruments import InstrumentKind, RateInstrument
from mentisrex.research.valuation.curves import ZeroCurve
from mentisrex.research.valuation.daycount import Compounding, DayCount
from mentisrex.research.valuation.interpolation import Extrapolation
from mentisrex.research.valuation.registry import CalibrationDiagnostics, CurveCalibrationReport

_REPRICE_TOL = 1e-8


class CurveBootstrapError(ValueError):
    pass


def _trial_curve(curve_id, ref_date, tenors, zeros, mat, z, compounding, day_count, currency):
    ts = [*tenors, mat]
    zs = [*zeros, z]
    return ZeroCurve(
        curve_id,
        ref_date,
        tuple(ts),
        tuple(zs),
        compounding,
        day_count,
        Extrapolation.FLAT,
        currency,
    )


def _residual(inst: RateInstrument, curve: ZeroCurve) -> float:
    """model_value − target; zero at the calibrated node. Positive/negative sign is consistent
    per instrument so a sign-agnostic bisection can bracket the root."""
    k = inst.kind
    start, mat = inst.start, inst.maturity_years()
    if k in (InstrumentKind.DEPOSIT,):
        r = inst.implied_rate()
        return curve.discount(mat) * (1.0 + r * (mat - start)) - 1.0
    if k in (InstrumentKind.FRA, InstrumentKind.FUTURE):
        f = inst.implied_rate()
        dlt = mat - start
        return curve.discount(start) / curve.discount(mat) - (1.0 + f * dlt)
    if k in (InstrumentKind.SWAP, InstrumentKind.OIS, InstrumentKind.GOV_BOND):
        s = inst.implied_rate()
        m = max(1, inst.convention.frequency)
        n = max(1, round(inst.tenor * m))
        tau = inst.tenor / n
        annuity = sum(tau * curve.discount(start + j * tau) for j in range(1, n + 1))
        float_leg = curve.discount(start) - curve.discount(mat)
        return s * annuity - float_leg
    raise CurveBootstrapError(f"{k.value} not supported by single-curve bootstrap (use multicurve)")


def _bisect(f, lo: float, hi: float, *, tol: float = 1e-12, max_iter: int = 200) -> float:
    flo, fhi = f(lo), f(hi)
    tries = 0
    while flo * fhi > 0 and tries < 40:  # widen bracket if needed
        lo -= 0.5
        hi += 0.5
        flo, fhi = f(lo), f(hi)
        tries += 1
    if flo * fhi > 0:
        raise CurveBootstrapError("could not bracket a root for node")
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


@dataclass(frozen=True)
class BootstrapResult:
    curve: ZeroCurve
    report: CurveCalibrationReport
    residuals: tuple = ()  # (instrument_name, residual)


class CurveBootstrapper:
    def __init__(
        self,
        *,
        compounding: Compounding = Compounding.CONTINUOUS,
        day_count: DayCount = DayCount.ACT_365,
        reprice_tol: float = _REPRICE_TOL,
        strict: bool = True,
    ) -> None:
        self.compounding = compounding
        self.day_count = day_count
        self.reprice_tol = reprice_tol
        self.strict = strict

    def bootstrap(
        self, instruments, ref_date: date, *, curve_id: str = "bootstrapped", currency: str = "USD"
    ) -> BootstrapResult:
        insts = sorted(instruments, key=lambda i: i.maturity_years())
        if not insts:
            raise CurveBootstrapError("no instruments to bootstrap")
        tenors: list[float] = []
        zeros: list[float] = []
        for inst in insts:
            mat = inst.maturity_years()
            if tenors and mat <= tenors[-1] + 1e-12:
                raise CurveBootstrapError(f"non-increasing maturity {mat} for {inst.name()}")

            def f(z, _inst=inst, _mat=mat):
                c = _trial_curve(
                    curve_id,
                    ref_date,
                    tenors,
                    zeros,
                    _mat,
                    z,
                    self.compounding,
                    self.day_count,
                    currency,
                )
                return _residual(_inst, c)

            z = _bisect(f, -0.99, 2.0)
            tenors.append(mat)
            zeros.append(z)

        curve = ZeroCurve(
            curve_id,
            ref_date,
            tuple(tenors),
            tuple(zeros),
            self.compounding,
            self.day_count,
            Extrapolation.FLAT,
            currency,
        )
        residuals = tuple((inst.name(), _residual(inst, curve)) for inst in insts)
        max_res = max((abs(r) for _, r in residuals), default=0.0)
        problems = tuple(
            f"{name}: repricing residual {r:.2e}"
            for name, r in residuals
            if abs(r) > self.reprice_tol
        )
        problems += tuple(curve.validate())
        report = CurveCalibrationReport(
            curve_id,
            CalibrationDiagnostics(max_res, len(insts), not problems),
            tuple(i.name() for i in insts),
            problems,
        )
        if self.strict and problems:
            raise CurveBootstrapError(f"curve {curve_id} failed to calibrate: {problems[0]}")
        return BootstrapResult(curve, report, residuals)
