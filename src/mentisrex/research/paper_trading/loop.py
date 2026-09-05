"""Continuous paper-trading runtime loop (AIDP M23).

PaperTradingLoop is the orchestrator: given a MarketDataSnapshot, it evaluates
each active strategy via M22 StrategyRuntime, then paper-executes the result
via M12 PaperTradingSession.

It does NOT implement:
  - strategy evaluation    (delegates to M22 StrategyRuntime)
  - portfolio construction (delegates to M10 via M22)
  - risk checks            (delegates to M13 via M22)
  - paper execution        (delegates to M12 PaperTradingSession + Broker)
  - fill processing        (delegates to M12 PaperPortfolio.ingest_fill)
  - reconciliation         (delegates to M12 reconcile())
  - drift monitoring       (delegates to M12 compute_drift())
  - market-data replay     (delegates to M20 MarketDataReplayEngine)

Operating modes:
  SIMULATION      — deterministic fixture data, no external calls
  REPLAY          — historical M20 replay, no external calls
  PAPER_LIVE_FEED — live/delayed M21 open data through M20

M23 is a PAPER-TRADING runtime. No real-money trading or broker connectivity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from mentisrex.research.paper_trading.broker import Broker, MockBroker, SimulatedBroker
from mentisrex.research.paper_trading.cycle import CycleRecord, ForwardPerformanceRecord
from mentisrex.research.paper_trading.runtime_state import StrategyRuntimeState
from mentisrex.research.paper_trading.scheduler import Clock, RebalanceScheduler
from mentisrex.research.paper_trading.session import PaperTradingSession, SessionConfig


class LoopError(Exception):
    """Raised when the loop encounters an unrecoverable error (fail-closed)."""


def _active_states():
    # ponytail: deferred to avoid circular import through paper_trading.__init__
    from mentisrex.research.strategy_deployment.models import StrategyState
    return frozenset({StrategyState.DEPLOYABLE, StrategyState.PAPER})


# ── configuration ─────────────────────────────────────────────────────────────

@dataclass
class LoopConfig:
    initial_capital: float = 1_000_000.0
    permit_experimental: bool = False
    fail_closed: bool = True
    validate_readiness: bool = True
    # SIMULATION | REPLAY | PAPER_LIVE_FEED
    mode: str = "SIMULATION"


# ── result objects (immutable) ────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategyCycleResult:
    strategy_id: str
    as_of: date
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""
    evaluation: object = None           # M22 StrategyEvaluation
    sync_event: object = None           # M12 SyncEvent
    cycle_record: object = None         # CycleRecord
    portfolio_value: float = 0.0
    cash: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    risk_approved: bool = False


@dataclass(frozen=True)
class LoopCycleResult:
    cycle_id: str
    as_of: date
    snapshot_fingerprint: str
    strategy_results: list              # list[StrategyCycleResult]
    skipped: bool = False
    skip_reason: str = ""
    processed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def result_for(self, strategy_id: str) -> StrategyCycleResult | None:
        for r in self.strategy_results:
            if r.strategy_id == strategy_id:
                return r
        return None


# ── cost-model compatibility ──────────────────────────────────────────────────

_SUPPORTED_COST_KEYS = frozenset({"slippage_bps", "commission_per_share", "spread_bps"})


@dataclass(frozen=True)
class CostCompatibilityResult:
    compatible: bool
    research_fingerprint: str
    execution_fingerprint: str
    mapped_assumptions: dict
    unmapped_keys: list
    issues: list = field(default_factory=list)


def check_cost_compatibility(spec) -> CostCompatibilityResult:
    """Validate that M22 spec cost assumptions are mappable to M14 execution models.

    Returns a CostCompatibilityResult. If not compatible, deployment should FAIL
    readiness (the loop raises LoopError on add_strategy if validate_readiness=True
    and the cost check fails for VALIDATED_DEPLOYABLE strategies).
    """
    from mentisrex.research.strategy_deployment.models import _fp
    tca = spec.transaction_cost_assumption
    unmapped = [k for k in tca if k not in _SUPPORTED_COST_KEYS]
    mapped = {k: tca[k] for k in _SUPPORTED_COST_KEYS if k in tca}
    issues = [f"unsupported cost key {k!r} — not wirable to M14 execution models" for k in unmapped]
    research_fp = _fp(tca)
    execution_fp = _fp(mapped)
    return CostCompatibilityResult(
        compatible=not unmapped,
        research_fingerprint=research_fp,
        execution_fingerprint=execution_fp,
        mapped_assumptions=mapped,
        unmapped_keys=unmapped,
        issues=issues,
    )


# ── main loop ─────────────────────────────────────────────────────────────────

class PaperTradingLoop:
    """Continuous paper-trading runtime orchestrator (AIDP M23).

    Lifecycle:
      1. loop = PaperTradingLoop(runtime=M22_runtime, registry=M22_registry)
      2. loop.add_strategy(strategy_id, logic, initial_capital=...)
      3. for snapshot in snapshot_stream:
             result = loop.process_snapshot(snapshot)
      4. loop.forward_record(strategy_id)  →  ForwardPerformanceRecord
      5. save_checkpoint(path, loop)        →  checkpoint file
      6. (restart) load_checkpoint(path)    →  loop.restore_from_checkpoint(data)
    """

    def __init__(self, *,
                 runtime,                            # M22 StrategyRuntime
                 registry,                           # M22 StrategyRegistry
                 scheduler: RebalanceScheduler | None = None,
                 config: LoopConfig | None = None,
                 clock: Clock | None = None) -> None:
        self._runtime = runtime
        self._registry = registry
        self._scheduler = scheduler or RebalanceScheduler()
        self._config = config or LoopConfig()
        self._clock = clock or Clock()
        from mentisrex.research.strategy_deployment.readiness import ReadinessValidator
        self._validator = ReadinessValidator()

        # per-strategy state
        self._sessions: dict[str, PaperTradingSession] = {}
        self._logics: dict = {}                      # strategy_id -> M22 StrategyLogic
        self._runtime_states: dict[str, StrategyRuntimeState] = {}

        # loop state
        self._seen: set[str] = set()                 # processed snapshot fingerprints
        self._cycle_records: list[CycleRecord] = []
        self._cycle_seq: int = 0

    # ── strategy management ───────────────────────────────────────────────────

    def add_strategy(self,
                     strategy_id: str,
                     logic,                          # M22 StrategyLogic
                     *,
                     initial_capital: float | None = None,
                     broker: Broker | None = None,
                     session_config: SessionConfig | None = None,
                     risk_gate=None) -> None:         # M12 PreTradeRiskGate override
        """Register a strategy for continuous paper trading.

        Validates M22 readiness gate before accepting. Each strategy gets its
        own isolated M12 PaperTradingSession (separate paper portfolio, broker).
        """
        entry = self._registry.get(strategy_id)
        if entry is None:
            raise LoopError(f"strategy {strategy_id!r} not found in registry")

        spec = entry.spec
        state = entry.state

        # Lifecycle gate
        active = _active_states()
        from mentisrex.research.strategy_deployment.models import StrategyState, StrategyType
        if state not in active:
            is_experimental_ok = (
                self._config.permit_experimental
                and spec.strategy_type in (StrategyType.EXPERIMENTAL_PAPER,
                                            StrategyType.EXPERIMENTAL_PAPER.value)
                and state == StrategyState.VALIDATED
            )
            if not is_experimental_ok:
                raise LoopError(
                    f"strategy {strategy_id!r} is in state {state.value!r} — "
                    f"must be in {[s.value for s in active]} to paper-trade"
                )

        # Readiness gate
        if self._config.validate_readiness:
            report = self._validator.validate(
                spec, permit_experimental=self._config.permit_experimental)
            if not report.ready:
                raise LoopError(
                    f"strategy {strategy_id!r} failed readiness gate: {report.issues}")

        capital = initial_capital or spec.capital_assumption or self._config.initial_capital
        if broker is None:
            broker = _build_broker(spec, capital)

        cfg = session_config or SessionConfig(initial_capital=capital)
        session = PaperTradingSession(broker=broker, config=cfg,
                                      risk_gate=risk_gate)

        self._sessions[strategy_id] = session
        self._logics[strategy_id] = logic
        self._runtime_states[strategy_id] = StrategyRuntimeState(
            strategy_id=strategy_id,
            strategy_version=spec.version,
            strategy_fingerprint=spec.configuration_fingerprint or spec.fingerprint(),
        )

    def remove_strategy(self, strategy_id: str) -> None:
        """Remove a strategy from the loop (does not affect M22 registry state)."""
        self._sessions.pop(strategy_id, None)
        self._logics.pop(strategy_id, None)
        self._runtime_states.pop(strategy_id, None)

    def pause_strategy(self, strategy_id: str, *, reason: str = "") -> None:
        """Operational pause: stop new orders without a M22 lifecycle transition.
        State is preserved; resume() continues from where it left off."""
        rs = self._get_rs(strategy_id)
        rs.status = "paused"

    def resume_strategy(self, strategy_id: str) -> None:
        """Resume a paused strategy. Revalidates M22 lifecycle state."""
        rs = self._get_rs(strategy_id)
        reg_state = self._registry.state(strategy_id)
        if reg_state not in _active_states():
            raise LoopError(
                f"cannot resume {strategy_id!r}: M22 state is {reg_state.value!r}")
        rs.status = "active"

    def trigger_evaluation(self, strategy_id: str, snapshot) -> StrategyCycleResult:
        """Force-evaluate a strategy regardless of schedule (event_driven / manual)."""
        as_of = getattr(snapshot, "as_of", None)
        if as_of is None:
            raise LoopError("snapshot.as_of is None")
        snap_fp = _snapshot_fp(snapshot)
        prices = _extract_prices(snapshot)
        return self._process_one(strategy_id, snapshot, as_of, snap_fp, prices,
                                 force=True)

    # ── main entry point ──────────────────────────────────────────────────────

    def process_snapshot(self, snapshot) -> LoopCycleResult:
        """Process one MarketDataSnapshot.

        Idempotent: duplicate snapshots (same fingerprint) are silently skipped.
        Fail-closed: None snapshot or missing as_of raises LoopError.
        """
        if snapshot is None:
            raise LoopError("snapshot is None — cannot process without market data")
        as_of = getattr(snapshot, "as_of", None)
        if as_of is None:
            raise LoopError("snapshot.as_of is None — PIT boundary unknown")

        snap_fp = _snapshot_fp(snapshot)
        self._cycle_seq += 1
        cycle_id = f"cycle-{self._cycle_seq:06d}"

        if snap_fp in self._seen:
            return LoopCycleResult(
                cycle_id=cycle_id, as_of=as_of, snapshot_fingerprint=snap_fp,
                strategy_results=[], skipped=True, skip_reason="duplicate_snapshot")

        self._seen.add(snap_fp)
        prices = _extract_prices(snapshot)

        results = [
            self._process_one(sid, snapshot, as_of, snap_fp, prices)
            for sid in list(self._sessions.keys())
        ]

        return LoopCycleResult(
            cycle_id=cycle_id, as_of=as_of,
            snapshot_fingerprint=snap_fp, strategy_results=results)

    def _process_one(self, strategy_id: str, snapshot, as_of: date,
                     snap_fp: str, prices: dict, *,
                     force: bool = False) -> StrategyCycleResult:
        rs = self._runtime_states[strategy_id]

        # M22 lifecycle check (authoritative)
        try:
            reg_state = self._registry.state(strategy_id)
        except KeyError:
            return _skip(strategy_id, as_of, "strategy_removed_from_registry")

        if reg_state not in _active_states():
            from mentisrex.research.strategy_deployment.models import StrategyState, StrategyType
            spec_check = self._registry.spec(strategy_id)
            is_experimental_ok = (
                self._config.permit_experimental
                and spec_check.strategy_type in (StrategyType.EXPERIMENTAL_PAPER,
                                                  StrategyType.EXPERIMENTAL_PAPER.value)
                and reg_state == StrategyState.VALIDATED
            )
            if not is_experimental_ok:
                return _skip(strategy_id, as_of, f"lifecycle_{reg_state.value}")

        # Operational pause
        if rs.status == "paused":
            return _skip(strategy_id, as_of, "paused")

        # Schedule check (bypassed by force=True for manual/event triggers)
        spec = self._registry.spec(strategy_id)
        if not force and not self._scheduler.is_due(spec, rs, as_of):
            return _skip(strategy_id, as_of, "not_due")

        # ── M22 evaluate ─────────────────────────────────────────────────────
        session = self._sessions[strategy_id]
        logic = self._logics[strategy_id]
        portfolio_state = session.book.state

        try:
            evaluation = self._runtime.evaluate(
                spec, logic, snapshot, portfolio_state,
                evaluation_id=f"{strategy_id}-eval-{rs.evaluation_count + 1:06d}",
                order_id_prefix=f"m23-{strategy_id[:8]}",
            )
        except Exception as exc:
            rs.error_count += 1
            rs.last_error = str(exc)
            if self._config.fail_closed:
                return StrategyCycleResult(
                    strategy_id=strategy_id, as_of=as_of, error=str(exc))
            raise

        # Risk-rejected → empty target (fail-closed on bad risk: no trade)
        target_weights = evaluation.portfolio.weights if evaluation.risk_approved else {}

        # ── M12 paper-execute ─────────────────────────────────────────────────
        try:
            sync_event = session.step(as_of, target_weights, prices)
        except Exception as exc:
            rs.error_count += 1
            rs.last_error = str(exc)
            if self._config.fail_closed:
                return StrategyCycleResult(
                    strategy_id=strategy_id, as_of=as_of, error=str(exc))
            raise

        # ── update runtime state ──────────────────────────────────────────────
        rs.last_eval_date = as_of
        rs.last_snapshot_fingerprint = snap_fp
        rs.last_evaluation_id = evaluation.evaluation_id
        rs.last_evaluation_fingerprint = evaluation.evaluation_fingerprint
        rs.evaluation_count += 1

        # ── cycle record ──────────────────────────────────────────────────────
        book = session.book
        portfolio_value = book.value()
        cash = book.cash
        realized_pnl = book.state.realized_pnl_total
        unrealized_pnl = book.state.unrealized_pnl()

        record = CycleRecord(
            cycle_id=f"{strategy_id}-{rs.evaluation_count:06d}",
            strategy_id=strategy_id,
            strategy_version=spec.version,
            strategy_fingerprint=spec.configuration_fingerprint or spec.fingerprint(),
            as_of=as_of,
            snapshot_fingerprint=snap_fp,
            evaluation_fingerprint=evaluation.evaluation_fingerprint,
            evaluation_id=evaluation.evaluation_id,
            portfolio_value=portfolio_value,
            nav=portfolio_value,
            cash=cash,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            n_orders=sync_event.n_orders,
            n_fills=sync_event.n_fills,
            reconciled=sync_event.reconciled,
            risk_approved=evaluation.risk_approved,
            risk_decision=evaluation.risk_decision,
            n_signals=len(evaluation.signal_set.signals),
        )
        self._cycle_records.append(record)

        return StrategyCycleResult(
            strategy_id=strategy_id,
            as_of=as_of,
            evaluation=evaluation,
            sync_event=sync_event,
            cycle_record=record,
            portfolio_value=portfolio_value,
            cash=cash,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            risk_approved=evaluation.risk_approved,
        )

    # ── query / views ─────────────────────────────────────────────────────────

    def strategy_records(self, strategy_id: str) -> list[CycleRecord]:
        return [r for r in self._cycle_records if r.strategy_id == strategy_id]

    def forward_record(self, strategy_id: str) -> ForwardPerformanceRecord:
        spec = self._registry.spec(strategy_id)
        return ForwardPerformanceRecord(
            strategy_id=strategy_id,
            strategy_version=spec.version,
            strategy_fingerprint=spec.configuration_fingerprint or spec.fingerprint(),
            cycles=self.strategy_records(strategy_id),
        )

    def session(self, strategy_id: str) -> PaperTradingSession:
        s = self._sessions.get(strategy_id)
        if s is None:
            raise KeyError(f"strategy {strategy_id!r} not in loop")
        return s

    def runtime_state(self, strategy_id: str) -> StrategyRuntimeState:
        return self._get_rs(strategy_id)

    @property
    def active_strategies(self) -> list[str]:
        return list(self._sessions.keys())

    @property
    def cycle_count(self) -> int:
        return self._cycle_seq

    @property
    def all_cycle_records(self) -> list[CycleRecord]:
        return list(self._cycle_records)

    # ── persistence ───────────────────────────────────────────────────────────

    def checkpoint_state(self) -> dict:
        """Serialize all loop state to a plain dict (JSON-serializable)."""
        from mentisrex.research.paper_trading.checkpoint import _checkpoint_dict
        return _checkpoint_dict(self)

    def restore_from_checkpoint(self, data: dict) -> None:
        """Restore loop state from a checkpoint dict in-place."""
        from mentisrex.research.paper_trading.checkpoint import _restore_checkpoint
        _restore_checkpoint(self, data)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _get_rs(self, strategy_id: str) -> StrategyRuntimeState:
        rs = self._runtime_states.get(strategy_id)
        if rs is None:
            raise LoopError(f"strategy {strategy_id!r} not in loop")
        return rs


# ── module helpers ────────────────────────────────────────────────────────────

def _skip(strategy_id: str, as_of: date, reason: str) -> StrategyCycleResult:
    return StrategyCycleResult(strategy_id=strategy_id, as_of=as_of,
                               skipped=True, skip_reason=reason)


def _snapshot_fp(snapshot) -> str:
    try:
        return snapshot.fingerprint()
    except AttributeError:
        import hashlib, json
        body = json.dumps(
            {"as_of": str(getattr(snapshot, "as_of", None)),
             "n_spots": len(getattr(snapshot, "spots", {}))},
            sort_keys=True)
        return hashlib.blake2b(body.encode(), digest_size=16).hexdigest()


def _extract_prices(snapshot) -> dict:
    spots = getattr(snapshot, "spots", {})
    out: dict = {}
    for sid, v in spots.items():
        try:
            out[sid] = float(v.mid) if hasattr(v, "mid") else float(v)
        except (TypeError, ValueError):
            pass
    return out


def _build_broker(spec, capital: float) -> Broker:
    """Build a paper broker wired to M22 spec cost assumptions."""
    tca = spec.transaction_cost_assumption
    slippage_bps = float(tca.get("slippage_bps", 0.0))
    if slippage_bps > 0:
        return SimulatedBroker(initial_cash=capital, slippage_bps=slippage_bps)
    return MockBroker(initial_cash=capital)
