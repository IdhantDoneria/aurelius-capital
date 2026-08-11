"""Market-data engine façade (AIDP M19).

One entry point over the whole pipeline: ingest raw records, bootstrap curves, calibrate vol
surfaces, and build the immutable M18 `MarketDataSnapshot` that feeds valuation. It wires the
pieces (normalizer, quality engine, snapshot builder, bootstrapper, calibrator) with injected
conventions and an M16 FX provider; it holds no mutable market state itself — every call is a
pure function of its inputs, so the same data + conventions + date always yield the same snapshot
and fingerprint.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.market_data.bootstrap import BootstrapResult, CurveBootstrapper
from aurelius.research.market_data.normalization import Normalizer
from aurelius.research.market_data.pit import (
    BuildResult,
    MarketDataSnapshotBuilder,
    PITPolicy,
)
from aurelius.research.market_data.quality import MarketDataQualityEngine, QualityConfig
from aurelius.research.market_data.vol_calibration import (
    VolatilitySurfaceCalibrator,
    VolModel,
)
from aurelius.research.valuation.daycount import Compounding, DayCount


class MarketDataEngine:
    def __init__(self, *, id_map=None, fx_provider=None, base_currency: str = "USD",
                 quality_config: QualityConfig | None = None,
                 compounding: Compounding = Compounding.CONTINUOUS,
                 day_count: DayCount = DayCount.ACT_365) -> None:
        self.normalizer = Normalizer(id_map=id_map, fx_provider=fx_provider,
                                     base_currency=base_currency)
        self.quality = MarketDataQualityEngine(quality_config)
        self.builder = MarketDataSnapshotBuilder(normalizer=self.normalizer, quality=self.quality)
        self.bootstrapper = CurveBootstrapper(compounding=compounding, day_count=day_count)
        self.fx_provider = fx_provider
        self.base_currency = base_currency

    # ── stages ────────────────────────────────────────────────────────────────
    def ingest(self, raw: list[dict], *, as_of: date):
        """Normalize + quality-check raw records. Returns (accepted_observations, diagnostics)."""
        norm = self.normalizer.normalize(raw, as_of=as_of)
        qrep = self.quality.check(norm.observations, as_of=as_of)
        return qrep.accepted, tuple(norm.diagnostics) + tuple(qrep.diagnostics)

    def bootstrap_curve(self, instruments, *, as_of: date, curve_id: str = "curve",
                        currency: str = "USD") -> BootstrapResult:
        return self.bootstrapper.bootstrap(instruments, as_of, curve_id=curve_id, currency=currency)

    def calibrate_surface(self, smiles, *, surface_id: str, as_of: date,
                          model: VolModel = VolModel.SVI, beta: float = 0.5):
        return VolatilitySurfaceCalibrator(model, beta=beta).calibrate_surface(
            smiles, surface_id, as_of)

    def build_snapshot(self, *, as_of: date, raw=None, source=None, curves=None,
                       vol_surfaces=None, dividend_yields=None, forwards=None,
                       policy: PITPolicy | None = None, **kw) -> BuildResult:
        return self.builder.build(
            as_of=as_of, raw=raw, source=source, curves=curves, vol_surfaces=vol_surfaces,
            dividend_yields=dividend_yields, forwards=forwards, fx_provider=self.fx_provider,
            policy=policy, **kw)

    # ── one-call pipeline ──────────────────────────────────────────────────────
    def pipeline(self, *, as_of: date, raw=None, source=None, curve_instruments=None,
                 smiles=None, curve_id: str = "curve", currency: str = "USD",
                 surface_underlying: str = "", vol_model: VolModel = VolModel.SVI,
                 dividend_yields=None, forwards=None, policy: PITPolicy | None = None) -> BuildResult:
        """Sources → curves + surfaces → M18 snapshot in one deterministic call."""
        curves = {}
        if curve_instruments:
            res = self.bootstrap_curve(curve_instruments, as_of=as_of, curve_id=currency,
                                       currency=currency)
            curves[currency] = res.curve
        vol_surfaces = {}
        if smiles:
            surf, _rep, _prov = self.calibrate_surface(
                smiles, surface_id=surface_underlying or "surface", as_of=as_of, model=vol_model)
            vol_surfaces[surface_underlying] = surf
        return self.build_snapshot(
            as_of=as_of, raw=raw, source=source, curves=curves, vol_surfaces=vol_surfaces,
            dividend_yields=dividend_yields, forwards=forwards, policy=policy)
