"""Model registry (AIDP M18) — governance.

A deterministic catalog of valuation models by name → version → callable/metadata, plus the
`CurveBuilder` calibration reports. Every `ValuationResult` names a model+version; this
registry is where those names are declared and looked up, so a valuation is always traceable
to a governed model.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    name: str
    version: str
    description: str = ""
    assumptions: tuple = ()


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict = {}

    def register(self, info: ModelInfo) -> ModelInfo:
        key = (info.name, info.version)
        if key in self._models and self._models[key] != info:
            raise ValueError(f"model {info.name}@{info.version} already registered differently")
        self._models[key] = info
        return info

    def get(self, name: str, version: str) -> ModelInfo:
        try:
            return self._models[(name, version)]
        except KeyError:
            raise KeyError(f"unknown model {name}@{version}") from None

    def all(self) -> list:
        return [self._models[k] for k in sorted(self._models)]


def default_registry() -> ModelRegistry:
    """The models M18 ships, declared for governance."""
    r = ModelRegistry()
    for info in (
        ModelInfo("equity.spot", "1.0.0", "Spot mark", ()),
        ModelInfo("futures.cost_of_carry", "1.0.0", "F = S·e^{(r-q)T}", ("continuous carry",)),
        ModelInfo("option.black_scholes", "1.0.0", "European BS w/ dividend yield",
                  ("European exercise", "flat vol per strike/maturity node")),
        ModelInfo("option.black_76", "1.0.0", "Option on forward/future", ("European exercise",)),
        ModelInfo("option.binomial_crr", "1.0.0", "American CRR tree",
                  ("discrete Bermudan approx", "steps-limited")),
        ModelInfo("bond.dcf", "1.0.0", "Discounted cash-flow / YTM", ("no credit spread",)),
        ModelInfo("swap.discount_curve", "1.0.0", "Single/dual-curve IRS NPV", ()),
        ModelInfo("xccy_swap.dual_curve", "1.0.0", "Cross-currency swap via M16 FX", ()),
        ModelInfo("forward.cost_of_carry", "1.0.0", "Forward fair value", ()),
    ):
        r.register(info)
    return r


# ── curve calibration reporting (deterministic bootstrap interface) ──────────

@dataclass(frozen=True)
class CalibrationDiagnostics:
    max_repricing_error: float = 0.0
    n_instruments: int = 0
    converged: bool = True


@dataclass(frozen=True)
class CurveCalibrationReport:
    curve_id: str
    diagnostics: CalibrationDiagnostics
    instruments: tuple = ()
    problems: tuple = ()

    @property
    def ok(self) -> bool:
        return self.diagnostics.converged and not self.problems


class CurveBuilder:
    """Deterministic curve construction from market instruments (deposits/FRAs/futures/swaps).

    M18 ships a direct zero-node builder (instruments already expressed as (tenor, zero));
    full multi-instrument bootstrap is an injected-convention extension point (see docs).
    Conventions are NOT assumed universal — they are passed in.
    """

    def build_zero(self, curve_id: str, ref_date, nodes: list, *, compounding=None,
                   day_count=None, currency: str = "USD"):
        from mentisrex.research.valuation.curves import ZeroCurve
        from mentisrex.research.valuation.daycount import Compounding, DayCount
        nodes = sorted(nodes)
        tenors = tuple(t for t, _ in nodes)
        zeros = tuple(z for _, z in nodes)
        curve = ZeroCurve(curve_id, ref_date, tenors, zeros,
                          compounding or Compounding.CONTINUOUS,
                          day_count or DayCount.ACT_365, currency=currency)
        problems = tuple(curve.validate())
        report = CurveCalibrationReport(
            curve_id, CalibrationDiagnostics(0.0, len(nodes), not problems),
            tuple(nodes), problems)
        return curve, report
