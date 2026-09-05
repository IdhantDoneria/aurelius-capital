"""Forward paper-trading campaign orchestrator (M25).

ForwardCampaign is the top-level PAPER_FORWARD operating layer. It:
  - Isolates forward state from SIMULATION / BACKTEST / REPLAY state
  - Implements deterministic cycle identity and duplicate prevention
  - Produces immutable sealed ForwardCycleRecord files
  - Persists campaign checkpoint independently of SIMULATION checkpoint
  - Handles restart / resume without duplicating financial effects
  - Delegates data fetch to LiveFeedBuilder, execution to PaperTradingLoop

Operating modes distinguished:
  SIMULATION      — synthetic fixture prices, no external calls
  REPLAY          — historical M20 replay, no external calls
  PAPER_LIVE_FEED — single real-data cycle (legacy name, cbcd4d1)
  PAPER_FORWARD   — this module: persistent, idempotent forward campaign
  LIVE            — not implemented; no real broker

PAPER_FORWARD semantic: "The system is operating using only information
available at the current forward decision point. No hindsight. No future data.
No retroactive reconstruction substituted for genuine forward evidence."

NO REAL CAPITAL DEPLOYED. STRATEGY UNMODIFIED.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from mentisrex.research.forward_campaign.ledger import ForwardLedger
from mentisrex.research.forward_campaign.record import (
    CycleStatus,
    ForwardCycleRecord,
    make_forward_cycle_id,
)
from mentisrex.research.paper_trading.checkpoint import (
    _restore_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from mentisrex.research.paper_trading.live_feed import LiveFeedBuilder, LiveFeedConfig
from mentisrex.research.paper_trading.loop import LoopConfig, PaperTradingLoop
from mentisrex.research.paper_trading.scheduler import RebalanceScheduler
from mentisrex.research.strategy_deployment.models import StrategyState, StrategyType, make_manifest
from mentisrex.research.strategy_deployment.registry import StrategyRegistry
from mentisrex.research.strategy_deployment.runtime import StrategyRuntime


@dataclass
class CampaignConfig:
    """Immutable configuration for a forward campaign run."""
    campaign_id: str
    strategy_id: str
    strategy_version: str
    universe: list
    starting_capital: float = 1_000_000.0
    fetch_window_days: int = 5
    max_staleness_days: int = 5
    data_dir: str = ""             # resolved at init time; set by ForwardCampaign
    account_id: str = "paper-default"
    mode: str = "PAPER_FORWARD"
    # Data health gate (M26): 0.0 = disabled; >0 enforces minimum universe coverage.
    min_universe_coverage: float = 0.0


@dataclass
class CycleResult:
    """Return value from ForwardCampaign.run()."""
    cycle_id: str
    status: str
    record: ForwardCycleRecord | None = None
    message: str = ""
    loop_result: Any = None   # raw LoopCycleResult from M23 (for inspection)


class ForwardCampaign:
    """Persistent, idempotent PAPER_FORWARD campaign.

    Lifecycle:
      campaign = ForwardCampaign.init(spec, logic, data_dir, universe, capital)
      result   = campaign.run(as_of=date.today())    # monthly; idempotent
      result   = campaign.run(as_of=date.today())    # second call → ALREADY_SEALED
      status   = campaign.status()
      history  = campaign.ledger.list_cycles()

    Restart safety:
      All state is checkpointed after each successful cycle.
      On restart, the campaign loads its own checkpoint (never the SIMULATION checkpoint).
      A cycle that was already sealed before the crash is detected and skipped.
    """

    _CAMPAIGN_CHECKPOINT = "campaign_checkpoint.json"
    _CAMPAIGN_MANIFEST   = "campaign_manifest.json"
    _CYCLES_DIR          = "cycles"
    _HEALTH_FILE         = "campaign_health.json"

    def __init__(self,
                 spec,                           # StrategySpecification
                 logic,                          # M22 StrategyLogic
                 config: CampaignConfig,
                 *,
                 _loop: PaperTradingLoop | None = None) -> None:
        self._spec = spec
        self._logic = logic
        self._config = config
        self._data_dir = Path(config.data_dir)
        self._cycles_dir = self._data_dir / self._CYCLES_DIR
        self._checkpoint_path = self._data_dir / self._CAMPAIGN_CHECKPOINT
        self._health_path = self._data_dir / self._HEALTH_FILE
        self._scheduler = RebalanceScheduler()
        self._loop: PaperTradingLoop | None = _loop   # allow injection for tests
        self.ledger = ForwardLedger(self._data_dir)
        self._health: dict = {}

    # ── factory ───────────────────────────────────────────────────────────────

    @classmethod
    def init(cls,
             spec,
             logic,
             data_dir: str | Path,
             universe: list,
             *,
             starting_capital: float = 1_000_000.0,
             campaign_id: str = "",
             account_id: str = "paper-default",
             fetch_window_days: int = 5,
             max_staleness_days: int = 5) -> "ForwardCampaign":
        """Create and persist a fresh forward campaign (no prior state inherited).

        Explicitly does NOT load any SIMULATION checkpoint. The forward campaign
        starts with clean portfolio state (cash=starting_capital, no positions).
        Idempotent: if campaign_manifest.json already exists, raises if campaign_id
        differs (prevents accidental reinit of a running campaign).
        """
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        if not campaign_id:
            ts = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y%m%dT%H%M%SZ")
            campaign_id = f"FORWARD_{spec.strategy_id}_{spec.version}_{ts}"

        cfg = CampaignConfig(
            campaign_id=campaign_id,
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            universe=list(universe),
            starting_capital=starting_capital,
            fetch_window_days=fetch_window_days,
            max_staleness_days=max_staleness_days,
            data_dir=str(data_dir),
            account_id=account_id,
        )

        manifest_path = data_dir / "campaign_manifest.json"
        if manifest_path.exists():
            existing = json.loads(manifest_path.read_text())
            if existing.get("campaign_id") != campaign_id:
                raise ValueError(
                    f"campaign_manifest.json exists with campaign_id="
                    f"{existing['campaign_id']!r} — use resume() or provide "
                    f"matching campaign_id to re-open."
                )
        else:
            manifest_path.write_text(json.dumps({
                "campaign_id": campaign_id,
                "strategy_id": spec.strategy_id,
                "strategy_version": spec.version,
                "strategy_fingerprint": spec.configuration_fingerprint or spec.fingerprint(),
                "starting_capital": starting_capital,
                "mode": "PAPER_FORWARD",
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "universe": list(universe),
                "account_id": account_id,
                "data_limitation": (
                    "Yahoo Finance (yfinance) — free/public, NOT institutional/exchange-grade. "
                    "Retroactive adjustments may occur but sealed records are immutable."
                ),
                "governance": (
                    "EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED. "
                    "NO REAL CAPITAL DEPLOYED. STRATEGY UNMODIFIED."
                ),
            }, indent=2, default=str))

        (data_dir / cls._CYCLES_DIR).mkdir(exist_ok=True)

        campaign = cls(spec, logic, cfg)
        campaign._health = {
            "campaign_id": campaign_id,
            "strategy_fingerprint": spec.configuration_fingerprint or spec.fingerprint(),
            "mode": "PAPER_FORWARD",
            "cycle_count": 0,
            "successful_cycles": 0,
            "failed_cycles": 0,
            "skipped_cycles": 0,
            "already_sealed_skips": 0,
            "data_errors": 0,
            "last_nav": starting_capital,
            "last_evaluation_date": None,
            "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        }
        campaign._persist_health()
        return campaign

    @classmethod
    def resume(cls, spec, logic, data_dir: str | Path) -> "ForwardCampaign":
        """Re-open an existing campaign from its checkpoint.

        Restores all forward portfolio/accounting state from the campaign's own
        checkpoint. Never touches SIMULATION or other campaign checkpoints.
        """
        data_dir = Path(data_dir)
        manifest_path = data_dir / "campaign_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"No campaign manifest at {manifest_path}. Use init() first.")

        manifest = json.loads(manifest_path.read_text())
        cfg = CampaignConfig(
            campaign_id=manifest["campaign_id"],
            strategy_id=manifest["strategy_id"],
            strategy_version=manifest["strategy_version"],
            universe=manifest["universe"],
            starting_capital=manifest["starting_capital"],
            data_dir=str(data_dir),
            account_id=manifest.get("account_id", "paper-default"),
        )
        campaign = cls(spec, logic, cfg)
        health_path = data_dir / cls._HEALTH_FILE
        if health_path.exists():
            campaign._health = json.loads(health_path.read_text())
        return campaign

    # ── main entry point ──────────────────────────────────────────────────────

    def run(self, as_of: date, *, provider_records: list | None = None) -> CycleResult:
        """Evaluate one forward cycle for the given date.

        Idempotent: running twice for the same month returns ALREADY_SEALED.
        Delegates data fetching to LiveFeedBuilder unless provider_records is
        supplied (offline/test mode — no network calls).

        Args:
            as_of: Observation date. For monthly rebalancing, the year+month
                   uniquely identifies the cycle.
            provider_records: Optional offline Yahoo-shaped record list. If None,
                              real Yahoo Finance data is fetched via yfinance.
                              Supply this in tests to avoid network calls.

        Returns:
            CycleResult with status SUCCESS | SKIPPED | FAILED | ALREADY_SEALED.
        """
        start_time = datetime.now(timezone.utc).replace(tzinfo=None)
        cycle_id = make_forward_cycle_id(
            self._config.strategy_id, self._config.strategy_version, as_of)

        # ── Idempotency: refuse to re-run a sealed cycle ──────────────────────
        existing = self._load_sealed_record(cycle_id)
        if existing is not None:
            self._health["already_sealed_skips"] = (
                self._health.get("already_sealed_skips", 0) + 1)
            self._persist_health()
            return CycleResult(
                cycle_id=cycle_id,
                status=CycleStatus.ALREADY_SEALED,
                record=existing,
                message=f"Cycle {cycle_id} already sealed at {existing.sealed_at}. "
                        "No duplicate financial effect.",
            )

        # ── Build or restore loop (isolated from SIMULATION) ──────────────────
        loop = self._get_loop()
        rs = loop.runtime_state(self._config.strategy_id)

        # ── Schedule check ────────────────────────────────────────────────────
        spec = self._spec
        if not self._scheduler.is_due(spec, rs, as_of):
            rec = self._make_partial_record(cycle_id, as_of, start_time)
            rec.status = CycleStatus.SKIPPED
            rec.skip_reason = (
                f"not_due — monthly scheduler; last_eval_date={rs.last_eval_date}"
            )
            rec.end_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            self._seal_and_persist(rec, CycleStatus.SKIPPED)
            self._update_health(skipped=True)
            return CycleResult(
                cycle_id=cycle_id,
                status=CycleStatus.SKIPPED,
                record=rec,
                message=rec.skip_reason,
            )

        # ── Fetch / build snapshot ────────────────────────────────────────────
        rec = self._make_partial_record(cycle_id, as_of, start_time)
        rec.campaign_id = self._config.campaign_id

        t_fetch = time.monotonic()
        build_result = self._fetch_snapshot(as_of, provider_records)
        fetch_s = time.monotonic() - t_fetch
        rec.fetch_latency_s = fetch_s

        if build_result is None:
            rec.status = CycleStatus.FAILED
            rec.error_message = "Snapshot build failed: provider returned no usable data"
            rec.end_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            self._seal_and_persist(rec, CycleStatus.FAILED)
            self._update_health(failed=True)
            return CycleResult(
                cycle_id=cycle_id,
                status=CycleStatus.FAILED,
                record=rec,
                message=rec.error_message,
            )

        snap = build_result.snapshot

        # ── Data health gate (M26) ────────────────────────────────────────────
        # Enforce minimum universe coverage before allowing any paper trade.
        # min_universe_coverage=0.0 (default) disables the gate (backward compat).
        universe = list(self._config.universe)
        n_present = len(snap.spots) if hasattr(snap, "spots") else 0
        n_universe = len(universe)
        coverage = n_present / n_universe if n_universe > 0 else 1.0
        if (self._config.min_universe_coverage > 0.0 and
                coverage < self._config.min_universe_coverage):
            rec.status = CycleStatus.FAILED
            rec.error_message = (
                f"Data health gate failed: coverage {n_present}/{n_universe} "
                f"({coverage:.0%}) below minimum "
                f"{self._config.min_universe_coverage:.0%}"
            )
            rec.end_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            self._seal_and_persist(rec, CycleStatus.FAILED)
            self._update_health(failed=True)
            return CycleResult(
                cycle_id=cycle_id,
                status=CycleStatus.FAILED,
                record=rec,
                message=rec.error_message,
            )

        rec.snapshot_fingerprint = snap.fingerprint() if hasattr(snap, "fingerprint") else ""
        rec.observations_accepted = len(build_result.observations)

        # Count diagnostics
        n_input = sum(1 for _ in getattr(build_result, "raw_payloads_count", (None,)))
        pit_v = 0
        stale_v = 0
        for diag in getattr(build_result, "diagnostics", []):
            ds = str(diag).lower()
            if "look_ahead" in ds or "look-ahead" in ds:
                pit_v += 1
            elif "stale" in ds:
                stale_v += 1
        rec.pit_violations = pit_v
        rec.stale_observations = stale_v
        rec.universe = universe
        present = set(snap.spots.keys() if hasattr(snap, "spots") else {})
        rec.missing_securities = [s for s in universe if s not in present]

        # ── Execute via M23 PaperTradingLoop ──────────────────────────────────
        rec.starting_nav = loop.session(self._config.strategy_id).book.value()

        t_proc = time.monotonic()
        try:
            loop_result = loop.process_snapshot(snap)
        except Exception as exc:
            rec.status = CycleStatus.FAILED
            rec.error_message = f"Loop error: {exc}"
            rec.end_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            self._seal_and_persist(rec, CycleStatus.FAILED)
            self._update_health(failed=True)
            return CycleResult(
                cycle_id=cycle_id,
                status=CycleStatus.FAILED,
                record=rec,
                message=rec.error_message,
            )
        rec.processing_latency_s = time.monotonic() - t_proc

        sr = loop_result.result_for(self._config.strategy_id)

        # ── Handle loop-level skip (duplicate snapshot, etc.) ─────────────────
        if loop_result.skipped or (sr and sr.skipped):
            reason = (sr.skip_reason if sr else "") or loop_result.skip_reason or "loop_skipped"
            rec.status = CycleStatus.SKIPPED
            rec.skip_reason = reason
            rec.end_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            self._seal_and_persist(rec, CycleStatus.SKIPPED)
            self._update_health(skipped=True)
            return CycleResult(
                cycle_id=cycle_id,
                status=CycleStatus.SKIPPED,
                record=rec,
                message=reason,
                loop_result=loop_result,
            )

        # ── Handle loop error ─────────────────────────────────────────────────
        if sr and sr.error:
            rec.status = CycleStatus.FAILED
            rec.error_message = sr.error
            rec.end_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            self._seal_and_persist(rec, CycleStatus.FAILED)
            self._update_health(failed=True)
            return CycleResult(
                cycle_id=cycle_id,
                status=CycleStatus.FAILED,
                record=rec,
                message=rec.error_message,
                loop_result=loop_result,
            )

        # ── Populate record from evaluation results ───────────────────────────
        sess = loop.session(self._config.strategy_id)
        book = sess.book
        rec.ending_nav = float(book.value())
        rec.cash = float(book.cash)
        rec.realized_pnl = float(book.state.realized_pnl_total)
        rec.unrealized_pnl = float(book.state.unrealized_pnl())
        rec.gross_return = (
            (rec.ending_nav - rec.starting_nav) / rec.starting_nav
            if rec.starting_nav > 0 else 0.0
        )
        rec.net_return = rec.gross_return   # net = gross for paper (fees in slippage)

        # positions snapshot
        rec.positions = {
            sid: h.shares
            for sid, h in book.state.holdings.items()
            if h.shares != 0
        }

        # concentration = max position weight
        total_v = rec.ending_nav
        if total_v > 0 and rec.positions:
            spot_prices = {
                sid: (float(v.mid) if hasattr(v, "mid") else float(v))
                for sid, v in (snap.spots.items() if hasattr(snap, "spots") else {}.items())
            }
            weights = {
                sid: abs(shares * spot_prices.get(sid, 0)) / total_v
                for sid, shares in rec.positions.items()
                if spot_prices.get(sid, 0) != 0
            }
            rec.concentration = max(weights.values()) if weights else 0.0

        if sr:
            sync = sr.sync_event
            if sync:
                rec.orders_generated = sync.n_orders
                rec.fills = sync.n_fills
            rec.risk_approved = sr.risk_approved
            rec.risk_decision = str(
                getattr(sr, "evaluation", None) and
                getattr(sr.evaluation, "risk_decision", "")
            ) or ""
            if sr.evaluation:
                ev = sr.evaluation
                rec.evaluation_fingerprint = getattr(ev, "evaluation_fingerprint", "")
                rec.evaluation_id = getattr(ev, "evaluation_id", "")
                # signal outputs
                ss = getattr(ev, "signal_set", None)
                if ss:
                    rec.signal_outputs = dict(getattr(ss, "signals", {}))
                # portfolio weights
                pw = getattr(ev, "portfolio", None)
                if pw:
                    rec.portfolio_weights = dict(getattr(pw, "weights", {}))

        spec_tca = getattr(self._spec, "transaction_cost_assumption", {})
        rec.slippage_bps = float(spec_tca.get("slippage_bps", 0.0))

        rec.end_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        rec.knowledge_as_of = as_of

        # ── Checkpoint then seal ──────────────────────────────────────────────
        self._checkpoint_loop(loop)
        self._seal_and_persist(rec, CycleStatus.SUCCESS)
        self._update_health(nav=rec.ending_nav, eval_date=as_of)

        return CycleResult(
            cycle_id=cycle_id,
            status=CycleStatus.SUCCESS,
            record=rec,
            loop_result=loop_result,
        )

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Machine-readable current campaign state."""
        ledger = self.ledger
        latest = ledger.latest_cycle()
        all_cycles = ledger.list_cycles()

        # Compute next expected evaluation date (M26)
        next_expected: date | None = None
        if latest and latest.evaluation_date:
            next_expected = self._scheduler.next_due(
                self._spec,
                type("_S", (), {"last_eval_date": latest.evaluation_date})(),
            )

        return {
            "campaign_id": self._config.campaign_id,
            "strategy_id": self._config.strategy_id,
            "strategy_version": self._config.strategy_version,
            "strategy_fingerprint": self._spec.configuration_fingerprint or self._spec.fingerprint(),
            "mode": "PAPER_FORWARD",
            "n_sealed_cycles": len(all_cycles),
            "n_successful_cycles": sum(1 for c in all_cycles if c.status == CycleStatus.SUCCESS),
            "n_failed_cycles": sum(1 for c in all_cycles if c.status == CycleStatus.FAILED),
            "n_skipped_cycles": sum(1 for c in all_cycles if c.status == CycleStatus.SKIPPED),
            "current_nav": latest.ending_nav if latest else self._config.starting_capital,
            "last_evaluation_date": (
                latest.evaluation_date.isoformat() if latest and latest.evaluation_date else None
            ),
            "next_expected_cycle": (
                next_expected.isoformat() if next_expected else None
            ),
            "checkpoint_exists": self._checkpoint_path.exists(),
            "data_limitation": (
                "Yahoo Finance (yfinance) — free/public, NOT institutional/exchange-grade."
            ),
            "governance": (
                "EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED. "
                "NO REAL CAPITAL DEPLOYED."
            ),
            "real_market_data": "YES",
            "paper_execution": "YES",
            "live_execution": "NO",
            "health": self._health,
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _get_loop(self) -> PaperTradingLoop:
        """Return the M23 loop, restoring from campaign checkpoint if it exists.

        Never touches the SIMULATION checkpoint. The campaign checkpoint is at
        self._checkpoint_path — a completely separate path.
        """
        if self._loop is not None:
            return self._loop

        # Build fresh registry + loop
        registry = self._build_registry()
        runtime = StrategyRuntime()
        config = LoopConfig(
            initial_capital=self._config.starting_capital,
            permit_experimental=True,
            fail_closed=True,
            validate_readiness=True,
            mode="PAPER_FORWARD",
        )
        loop = PaperTradingLoop(runtime=runtime, registry=registry, config=config)
        loop.add_strategy(self._config.strategy_id, self._logic)

        # Restore from campaign checkpoint (NOT the shared SIMULATION checkpoint)
        if self._checkpoint_path.exists():
            try:
                ckpt = load_checkpoint(str(self._checkpoint_path))
                _restore_checkpoint(loop, ckpt)
            except Exception as exc:
                raise RuntimeError(
                    f"Campaign checkpoint at {self._checkpoint_path} is corrupted: {exc}. "
                    "Delete the checkpoint to start fresh (financial state will reset)."
                ) from exc

        self._loop = loop
        return loop

    def _build_registry(self) -> StrategyRegistry:
        reg = StrategyRegistry()
        reg.register(self._spec, StrategyState.DRAFT)
        reg.transition(self._spec.strategy_id, StrategyState.VALIDATING)
        reg.transition(self._spec.strategy_id, StrategyState.VALIDATED)
        return reg

    def _fetch_snapshot(self, as_of: date, provider_records: list | None):
        """Fetch snapshot. Uses offline records if supplied (for tests)."""
        feed_cfg = LiveFeedConfig(
            universe=tuple(self._config.universe),
            fetch_window_days=self._config.fetch_window_days,
            max_staleness_days=self._config.max_staleness_days,
        )
        feed = LiveFeedBuilder(feed_cfg)
        if provider_records is not None:
            return feed.fetch_snapshot_from_records(provider_records, as_of)
        return feed.fetch_snapshot(as_of)

    def _make_partial_record(self, cycle_id: str, as_of: date,
                             start_time: datetime) -> ForwardCycleRecord:
        return ForwardCycleRecord(
            cycle_id=cycle_id,
            strategy_id=self._config.strategy_id,
            strategy_version=self._config.strategy_version,
            strategy_fingerprint=self._spec.configuration_fingerprint or self._spec.fingerprint(),
            evaluation_date=date(as_of.year, as_of.month, 1),
            knowledge_as_of=as_of,
            account_id=self._config.account_id,
            campaign_id=self._config.campaign_id,
            mode="PAPER_FORWARD",
            start_time=start_time.isoformat(),
            status=CycleStatus.PARTIAL,
        )

    def _load_sealed_record(self, cycle_id: str) -> ForwardCycleRecord | None:
        """Return existing sealed record if it exists, else None."""
        p = self._cycles_dir / f"{cycle_id}.json"
        if not p.exists():
            return None
        try:
            rec = ForwardCycleRecord.from_dict(json.loads(p.read_text()))
            return rec if rec.is_sealed else None
        except Exception:
            return None

    def _seal_and_persist(self, rec: ForwardCycleRecord, status: str) -> None:
        """Seal the record and atomically write it to the cycles/ directory.

        Atomic write: write to .tmp file then rename. This ensures that a crash
        mid-write never produces a partial (corrupt) record file. If the target
        already exists (race or restart), the existing sealed record wins.
        """
        rec.seal(status)
        self._cycles_dir.mkdir(parents=True, exist_ok=True)
        target = self._cycles_dir / f"{rec.cycle_id}.json"
        if target.exists():
            return  # Sealed record already exists — never overwrite
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec.to_dict(), indent=2, default=str))
        tmp.rename(target)

    def _checkpoint_loop(self, loop: PaperTradingLoop) -> None:
        """Save campaign-specific checkpoint. Separate from SIMULATION checkpoint."""
        save_checkpoint(str(self._checkpoint_path), loop)

    def _update_health(self, *,
                       skipped: bool = False,
                       failed: bool = False,
                       nav: float = 0.0,
                       eval_date: date | None = None) -> None:
        self._health["cycle_count"] = self._health.get("cycle_count", 0) + 1
        if skipped:
            self._health["skipped_cycles"] = self._health.get("skipped_cycles", 0) + 1
        elif failed:
            self._health["failed_cycles"] = self._health.get("failed_cycles", 0) + 1
        else:
            self._health["successful_cycles"] = self._health.get("successful_cycles", 0) + 1
            if nav:
                self._health["last_nav"] = nav
            if eval_date:
                self._health["last_evaluation_date"] = eval_date.isoformat()
        self._persist_health()

    def _persist_health(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._health_path.write_text(json.dumps(self._health, indent=2, default=str))
