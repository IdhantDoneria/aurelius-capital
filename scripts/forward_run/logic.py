"""EqualWeightMomentumLogic — strategy logic for the experimental forward run.

EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED.

Signal rule: for each security in the fixed universe that appears in the
snapshot with a positive price, emit signal=1.0.  M10 PortfolioEngine with
objective=equal_weight then converts equal signals to equal target weights.

Properties:
  - No look-ahead: reads only snapshot.spots (the current price cross-section).
  - No external calls: logic receives snapshot from M23; never fetches data.
  - Deterministic: same snapshot → same FeatureSet → same SignalSet → same fingerprint.
  - PIT-safe: FeatureSet.as_of and SignalSet.as_of both inherit from snapshot.as_of.
"""

from __future__ import annotations

from mentisrex.research.strategy_deployment.models import (
    FeatureSet,
    SignalRecord,
    SignalSet,
    StrategySpecification,
)
from mentisrex.research.strategy_deployment.runtime import StrategyLogic


class EqualWeightMomentumLogic(StrategyLogic):
    """Equal-weight logic: signal=1.0 for every universe security with price>0."""

    def __init__(self, universe: list[str]) -> None:
        self._universe = list(universe)

    def compute_features(self, snapshot, spec: StrategySpecification) -> FeatureSet:
        spots = getattr(snapshot, "spots", {})
        features: dict = {}
        for sid in self._universe:
            raw = spots.get(sid)
            if raw is None:
                continue
            try:
                price = float(raw.mid) if hasattr(raw, "mid") else float(raw)
            except (TypeError, ValueError):
                continue
            features[sid] = {"price": price}

        snap_fp = snapshot.fingerprint() if hasattr(snapshot, "fingerprint") else ""
        spec_fp = spec.configuration_fingerprint or spec.fingerprint()
        return FeatureSet(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=snapshot.as_of,
            features=features,
            input_fingerprint=snap_fp,
            strategy_fingerprint=spec_fp,
        )

    def generate_signal(self, features: FeatureSet, spec: StrategySpecification) -> SignalSet:
        spec_fp = spec.configuration_fingerprint or spec.fingerprint()
        feat_fp = features.fingerprint()

        signals = {
            sid: 1.0
            for sid, fv in features.features.items()
            if fv.get("price", 0.0) > 0.0
        }
        records = [
            SignalRecord(
                strategy_id=spec.strategy_id,
                strategy_version=spec.version,
                security_id=sid,
                as_of=features.as_of,
                signal_value=1.0,
                input_fingerprint=feat_fp,
                strategy_fingerprint=spec_fp,
            )
            for sid in signals
        ]
        return SignalSet(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=features.as_of,
            signals=signals,
            signal_records=records,
            features_fingerprint=feat_fp,
            strategy_fingerprint=spec_fp,
        )
