"""Strategy runtime (AIDP M22).

StrategyRuntime.evaluate() is the single seam connecting a validated strategy
to the existing M10 portfolio construction, M13 risk, and M14 execution layers.

It does NOT implement:
  - portfolio construction  (delegates to M10 PortfolioEngine)
  - risk checking           (delegates to M13 RiskEngine)
  - order execution         (produces M14-ready OrderRequests; EMS/OMS is separate)
  - market data fetching    (consumes M18 MarketDataSnapshot; never fetches)
  - paper trading           (produces intents for M12 PaperTradingSession)

Determinism guarantee: same strategy + same snapshot fingerprint + same portfolio
state weights + same config → same evaluation fingerprint.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from typing import Any

from mentisrex.research.execution.ems.models import OrderType
from mentisrex.research.execution.ems.orders import (
    MarketInfo,
    build_requests,
    intents_from_target,
)
from mentisrex.research.portfolio.constraints import ConstraintSet
from mentisrex.research.portfolio.engine import PortfolioEngine
from mentisrex.research.risk.engine import RiskEngine
from mentisrex.research.risk.models import RiskDecision
from mentisrex.research.strategy_deployment.models import (
    FeatureSet,
    OrderIntentRecord,
    SignalSet,
    StrategyEvaluation,
    StrategySpecification,
    _fp,
)

# ── strategy logic protocol ───────────────────────────────────────────────────


class StrategyLogic(ABC):
    """Abstract base for user-supplied strategy computation.

    Implementors provide the two methods below. The runtime supplies the snapshot
    and the strategy spec; the logic never calls external providers.

    No random behavior. No wall-clock reads in deterministic mode.
    """

    @abstractmethod
    def compute_features(self, snapshot, spec: StrategySpecification) -> FeatureSet:
        """Extract features from a MarketDataSnapshot.

        snapshot: M18 MarketDataSnapshot (or any object with .spots and .as_of)
        spec: StrategySpecification (carries feature_definition config)
        Returns: FeatureSet — one row per security, keyed by security_id.
        """

    @abstractmethod
    def generate_signal(self, features: FeatureSet, spec: StrategySpecification) -> SignalSet:
        """Compute signals from a FeatureSet.

        No future data may be used. Signal as_of == features.as_of.
        Returns: SignalSet — security_id -> float (positive = long, negative = short).
        """


# ── runtime ───────────────────────────────────────────────────────────────────


class EvaluationError(Exception):
    """Raised when a strategy evaluation fails deterministically."""


class StrategyRuntime:
    """Orchestrates the strategy evaluation pipeline.

    Components are injected — none are constructed internally — so this class
    is testable without live infrastructure.
    """

    def __init__(
        self,
        *,
        portfolio_engine: PortfolioEngine | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self._portfolio = portfolio_engine or PortfolioEngine()
        self._risk = risk_engine or RiskEngine()

    def evaluate(
        self,
        spec: StrategySpecification,
        logic: StrategyLogic,
        snapshot,  # M18 MarketDataSnapshot
        portfolio_state,  # M11 PortfolioState
        *,
        evaluation_id: str | None = None,
        order_id_prefix: str | None = None,
    ) -> StrategyEvaluation:
        """Run one full strategy evaluation cycle.

        Steps:
          1. Validate inputs
          2. Compute features
          3. Generate signals
          4. Construct portfolio targets via M10
          5. Run pre-trade risk check via M13
          6. Build M22 OrderIntentRecords with full lineage
          7. Build M14-ready OrderRequests for the EMS
          8. Return StrategyEvaluation with deterministic fingerprint
        """
        eval_id = evaluation_id or str(uuid.uuid4())
        order_prefix = order_id_prefix or f"m22-{spec.strategy_id[:8]}"

        warnings: list[str] = []
        errors: list[str] = []

        # ── 1. input validation ───────────────────────────────────────────────
        if snapshot is None:
            raise EvaluationError("snapshot is None — cannot evaluate without market data")
        as_of: date = getattr(snapshot, "as_of", None)
        if as_of is None:
            raise EvaluationError("snapshot.as_of is None — PIT boundary unknown")

        snap_fp = _snapshot_fingerprint(snapshot)

        # ── 2. feature computation ────────────────────────────────────────────
        feature_set = logic.compute_features(snapshot, spec)
        if feature_set is None:
            raise EvaluationError("compute_features() returned None")
        if feature_set.as_of != as_of:
            raise EvaluationError(
                f"FeatureSet.as_of={feature_set.as_of} != snapshot.as_of={as_of} — PIT violation"
            )

        # ── 3. signal generation ──────────────────────────────────────────────
        signal_set = logic.generate_signal(feature_set, spec)
        if signal_set is None:
            raise EvaluationError("generate_signal() returned None")
        if signal_set.as_of != as_of:
            raise EvaluationError(
                f"SignalSet.as_of={signal_set.as_of} != snapshot.as_of={as_of} — PIT violation"
            )

        signals = signal_set.signals
        _validate_signals(signals, warnings, errors)
        if errors:
            raise EvaluationError(f"invalid signals: {errors}")

        # ── 4. portfolio construction (M10) ───────────────────────────────────
        universe = _universe_from_signals(signals)
        constraints = _build_constraints(spec)
        objective = _build_objective(spec)
        prices = _prices_from_snapshot(snapshot, universe)
        capital = spec.capital_assumption or 1_000_000.0

        portfolio = self._portfolio.construct(
            signals=signals,
            universe=universe,
            constraints=constraints,
            objective=objective,
            as_of=as_of,
            prices=prices,
            capital=capital,
        )

        target_weights = portfolio.weights
        portfolio_fp = _portfolio_fingerprint(portfolio)

        # ── 5. risk check (M13) ───────────────────────────────────────────────
        portfolio_value = portfolio_state.total_value() if portfolio_state is not None else capital
        risk_report = self._risk.pre_trade_check(
            target_weights,
            portfolio_value=portfolio_value,
        )
        risk_fp = _risk_fingerprint(risk_report)
        risk_approved = risk_report.decision != RiskDecision.REJECT
        if not risk_approved:
            warnings.append(f"Risk gate REJECTED: {[v.message for v in risk_report.violations]}")

        # ── 6. build M22 order intents with full lineage ─────────────────────
        current_shares = (
            {sid: h.shares for sid, h in portfolio_state.holdings.items()}
            if portfolio_state is not None
            else {}
        )
        target_shares = {
            p.security_id: p.shares for p in portfolio.positions if abs(p.shares) > 1e-9
        }
        ems_intents = intents_from_target(target_shares, current_shares)

        now = datetime.now(UTC).replace(tzinfo=None)
        spec_fp = spec.configuration_fingerprint or spec.fingerprint()
        sig_fp = signal_set.fingerprint()

        order_intents = []
        for i, intent in enumerate(ems_intents):
            sid = intent.security_id
            ref_price = prices.get(sid, 0.0) if prices else 0.0
            tw = target_weights.get(sid, 0.0)
            record = OrderIntentRecord(
                intent_id=f"{order_prefix}-intent-{i:06d}",
                strategy_id=spec.strategy_id,
                strategy_version=spec.version,
                security_id=sid,
                side=intent.side,
                delta_shares=intent.delta_shares,
                target_weight=tw,
                reference_price=ref_price,
                generated_at=now,
                reason="strategy_runtime_evaluation",
                signal_reference=sig_fp,
                target_reference=portfolio_fp,
                risk_reference=risk_fp,
                configuration_fingerprint=spec_fp,
            )
            order_intents.append(record)

        # ── 7. build M14-ready OrderRequests for EMS ─────────────────────────
        market = MarketInfo(prices=prices or {})
        ems_requests = (
            build_requests(
                ems_intents,
                market=market,
                id_prefix=order_prefix,
                order_type=OrderType.MARKET,
            )
            if risk_approved
            else []
        )

        # ── 8. deterministic evaluation fingerprint ───────────────────────────
        eval_fp = _fp(
            {
                "strategy_id": spec.strategy_id,
                "version": spec.version,
                "spec_fingerprint": spec_fp,
                "snapshot_fingerprint": snap_fp,
                "portfolio_fingerprint": portfolio_fp,
                "signal_fingerprint": sig_fp,
                "risk_fingerprint": risk_fp,
                "n_intents": len(order_intents),
            }
        )

        provenance = {
            "m10_portfolio_engine": type(self._portfolio).__name__,
            "m13_risk_engine": type(self._risk).__name__,
            "strategy_logic": type(logic).__name__,
            "snapshot_as_of": str(as_of),
            "snapshot_fingerprint": snap_fp,
        }

        return StrategyEvaluation(
            evaluation_id=eval_id,
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=as_of,
            feature_set=feature_set,
            signal_set=signal_set,
            portfolio=portfolio,
            risk_report=risk_report,
            order_intents=order_intents,
            ems_requests=ems_requests,
            evaluation_fingerprint=eval_fp,
            provenance=provenance,
            evaluated_at=now,
            strategy_fingerprint=spec_fp,
            risk_approved=risk_approved,
            risk_decision=risk_report.decision.value,
            warnings=warnings,
            errors=errors,
        )


# ── helpers ───────────────────────────────────────────────────────────────────


def _snapshot_fingerprint(snapshot) -> str:
    try:
        return snapshot.fingerprint()
    except AttributeError:
        return _fp(
            {
                "as_of": str(getattr(snapshot, "as_of", None)),
                "n_spots": len(getattr(snapshot, "spots", {})),
            }
        )


def _portfolio_fingerprint(portfolio) -> str:
    return _fp(
        {
            "date": str(portfolio.date),
            "n_positions": len(portfolio.positions),
            "gross_exposure": portfolio.gross_exposure,
            "turnover": portfolio.turnover,
        }
    )


def _risk_fingerprint(risk_report) -> str:
    return _fp(
        {
            "decision": risk_report.decision.value
            if hasattr(risk_report.decision, "value")
            else str(risk_report.decision),
            "n_violations": len(risk_report.violations)
            if hasattr(risk_report, "violations")
            else 0,
            "volatility": getattr(risk_report, "volatility", 0.0),
        }
    )


def _validate_signals(signals: dict, warnings: list, errors: list) -> None:
    import math

    for sid, val in signals.items():
        if not isinstance(val, (int, float)):
            errors.append(f"signal for {sid!r} is not numeric: {val!r}")
        elif math.isnan(val):
            errors.append(f"NaN signal for {sid!r}")
        elif math.isinf(val):
            errors.append(f"infinite signal for {sid!r}")


def _universe_from_signals(signals: dict) -> list[str]:
    """Non-zero signals define the universe for construction."""
    return [sid for sid, v in signals.items() if abs(v) > 1e-12]


def _prices_from_snapshot(snapshot, universe: list[str]) -> dict:
    spots = getattr(snapshot, "spots", {})
    out = {}
    for sid in universe:
        v = spots.get(sid)
        if v is not None:
            try:
                out[sid] = float(v.mid) if hasattr(v, "mid") else float(v)
            except (TypeError, ValueError):
                pass
    return out


def _build_constraints(spec: StrategySpecification) -> ConstraintSet:
    cfg = spec.portfolio_construction_config
    from mentisrex.research.portfolio.constraints import ConstraintSet

    kwargs: dict[str, Any] = {}
    if "max_position_weight" in cfg:
        kwargs["max_position_weight"] = float(cfg["max_position_weight"])
    if "min_position_weight" in cfg:
        kwargs["min_position_weight"] = float(cfg["min_position_weight"])
    if "long_only" in cfg:
        kwargs["long_only"] = bool(cfg["long_only"])
    if "gross_exposure" in cfg:
        kwargs["gross_exposure"] = float(cfg["gross_exposure"])
    if "max_leverage" in cfg:
        kwargs["max_leverage"] = float(cfg["max_leverage"])
    return ConstraintSet(**kwargs)


def _build_objective(spec: StrategySpecification) -> str:
    return spec.portfolio_construction_config.get("objective", "max_sharpe")
