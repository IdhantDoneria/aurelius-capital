"""Controlled forward paper-trading activation driver.

EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED.
NO REAL CAPITAL WAS DEPLOYED.
NO STRATEGY PARAMETERS WERE OPTIMIZED USING FORWARD DATA.
FORWARD RESULTS ARE OBSERVATIONAL EVIDENCE AND ARE NOT YET A
DEPLOYMENT OR PROFITABILITY DECISION.

Usage (SIMULATION / rehearsal mode):
    cd mentisrex-capital
    python scripts/forward_run/run_forward.py --mode SIMULATION --cycles 12

Usage (operational forward run with M20/M21 snapshot injection):
    Inject snapshots externally via the --snapshot-dir flag (see below) or
    call run_loop() programmatically with a snapshot stream from M20/M21.

Data quality limitation:
    SIMULATION mode uses synthetic deterministic price data.
    PAPER_LIVE_FEED mode requires caller-supplied snapshots built by M20/M21
    providers (not implemented in this script; wire via run_loop()).
    Neither mode is equivalent to Bloomberg / Refinitiv institutional data.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

# ── ensure src is importable when run as a script ─────────────────────────────
_repo = Path(__file__).resolve().parent.parent.parent
if str(_repo / "src") not in sys.path:
    sys.path.insert(0, str(_repo / "src"))

from mentisrex.research.paper_trading.checkpoint import save_checkpoint, load_checkpoint, _restore_checkpoint
from mentisrex.research.paper_trading.live_feed import LiveFeedBuilder, LiveFeedConfig
from mentisrex.research.paper_trading.loop import LoopConfig, PaperTradingLoop
from mentisrex.research.paper_trading.scheduler import FixedClock
from mentisrex.research.strategy_deployment.models import StrategyState, make_manifest
from mentisrex.research.strategy_deployment.registry import StrategyRegistry
from mentisrex.research.strategy_deployment.runtime import StrategyRuntime

# Import spec and logic (co-located in this package)
sys.path.insert(0, str(Path(__file__).parent))
from spec import SPEC, STARTING_CAPITAL, UNIVERSE
from logic import EqualWeightMomentumLogic

# ── forward run manifest constants ────────────────────────────────────────────
RUN_ID = "FORWARD_RUN_ew-momentum-exp_v1.0.0_20260812T000000Z"
FORWARD_DATA_DIR = _repo / "data" / "forward_runs" / RUN_ID
CHECKPOINT_PATH = FORWARD_DATA_DIR / "checkpoint.json"
RECORDS_PATH = FORWARD_DATA_DIR / "cycle_records.json"
MANIFEST_PATH = FORWARD_DATA_DIR / "run_manifest.json"
HEALTH_PATH = FORWARD_DATA_DIR / "run_health.json"


# ── synthetic snapshot (no network; SIMULATION mode only) ─────────────────────

@dataclass(frozen=True)
class _SyntheticSnapshot:
    """Deterministic fake snapshot for SIMULATION mode.

    Prices shift by +0.5% per monthly cycle so the portfolio has non-trivial
    movement for testing.  No real market data is used.
    """
    as_of: date
    spots: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        import hashlib, json as _json
        body = _json.dumps(
            {"as_of": str(self.as_of),
             "spots": {k: v for k, v in sorted(self.spots.items())}},
            sort_keys=True)
        return hashlib.blake2b(body.encode(), digest_size=16).hexdigest()


_BASE_PRICES = {
    "AAPL": 185.0, "MSFT": 415.0, "GOOGL": 172.0, "AMZN": 188.0,
    "META": 520.0, "NVDA": 875.0, "TSLA": 225.0, "JPM": 202.0,
    "JNJ": 148.0, "V": 278.0,
}


def _synthetic_snapshots(n_cycles: int, start: date) -> list[_SyntheticSnapshot]:
    """Generate n_cycles monthly snapshots. Prices drift +0.5%/month."""
    snaps = []
    for i in range(n_cycles):
        d = date(start.year + (start.month + i - 1) // 12,
                 (start.month + i - 1) % 12 + 1, 1)
        factor = 1.005 ** i
        spots = {sid: round(p * factor, 4) for sid, p in _BASE_PRICES.items()}
        snaps.append(_SyntheticSnapshot(as_of=d, spots=spots))
    return snaps


# ── registry builder ──────────────────────────────────────────────────────────

def build_registry() -> StrategyRegistry:
    """Register the experimental strategy up to VALIDATED state."""
    reg = StrategyRegistry()
    reg.register(SPEC, StrategyState.DRAFT)
    reg.transition(SPEC.strategy_id, StrategyState.VALIDATING)
    reg.transition(SPEC.strategy_id, StrategyState.VALIDATED)
    # EXPERIMENTAL_PAPER stays at VALIDATED; permit_experimental=True in LoopConfig
    return reg


# ── loop builder ──────────────────────────────────────────────────────────────

def build_loop(registry: StrategyRegistry,
               clock=None,
               initial_capital: float = STARTING_CAPITAL) -> PaperTradingLoop:
    """Create a configured PaperTradingLoop for the experimental paper run."""
    runtime = StrategyRuntime()
    config = LoopConfig(
        initial_capital=initial_capital,
        permit_experimental=True,
        fail_closed=True,
        validate_readiness=True,
        mode="SIMULATION",
    )
    loop = PaperTradingLoop(runtime=runtime, registry=registry,
                            config=config, clock=clock)
    loop.add_strategy(SPEC.strategy_id, EqualWeightMomentumLogic(UNIVERSE))
    return loop


# ── health tracker ────────────────────────────────────────────────────────────

@dataclass
class RunHealth:
    run_id: str = RUN_ID
    strategy_id: str = SPEC.strategy_id
    strategy_fingerprint: str = SPEC.configuration_fingerprint
    mode: str = "SIMULATION"
    start_time: str = ""
    cycle_count: int = 0
    successful_cycles: int = 0
    failed_cycles: int = 0
    skipped_cycles: int = 0
    snapshot_failures: int = 0
    risk_rejections: int = 0
    fills: int = 0
    checkpoint_count: int = 0
    restart_count: int = 0
    reconciliation_failures: int = 0
    last_nav: float = 0.0
    last_as_of: str = ""
    data_quality: str = "synthetic_simulation"
    data_limitation: str = (
        "SIMULATION mode uses deterministic synthetic prices. "
        "Not equivalent to Bloomberg / Refinitiv / institutional exchange data."
    )

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


def _update_health(health: RunHealth, loop: PaperTradingLoop) -> None:
    """Update health from loop state after each cycle."""
    rs = loop.runtime_state(SPEC.strategy_id)
    health.cycle_count = loop.cycle_count
    health.successful_cycles = rs.evaluation_count
    health.failed_cycles = rs.error_count
    health.last_as_of = str(rs.last_eval_date or "")
    # NAV from last cycle record
    recs = loop.strategy_records(SPEC.strategy_id)
    if recs:
        health.last_nav = recs[-1].nav
        health.fills += recs[-1].n_fills
        if not recs[-1].risk_approved:
            health.risk_rejections += 1


# ── main run loop ─────────────────────────────────────────────────────────────

def run_loop(snapshots, *, checkpoint_every: int = 4) -> PaperTradingLoop:
    """Run the forward loop over a snapshot stream.

    Saves a checkpoint every `checkpoint_every` evaluations.
    Returns the loop after processing all snapshots.
    """
    FORWARD_DATA_DIR.mkdir(parents=True, exist_ok=True)

    registry = build_registry()
    manifest = make_manifest(f"{RUN_ID}-manifest", SPEC)

    # Save run manifest
    manifest_dict = manifest.to_dict()
    manifest_dict.update({
        "run_id": RUN_ID,
        "starting_capital_usd": STARTING_CAPITAL,
        "data_source": "synthetic_simulation",
        "data_quality_limitation": (
            "Synthetic prices only. Not equivalent to institutional vendor data."
        ),
        "experimental_status": "EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED",
        "m23_version": "M23",
        "m24_compatibility_version": "M24",
        "no_real_capital": True,
        "no_strategy_parameter_optimization": True,
    })
    MANIFEST_PATH.write_text(json.dumps(manifest_dict, indent=2, default=str))

    loop = build_loop(registry)
    health = RunHealth(start_time=datetime.utcnow().isoformat())
    eval_count = 0

    for snapshot in snapshots:
        result = loop.process_snapshot(snapshot)
        if result.skipped:
            health.skipped_cycles += 1
            continue

        sr = result.result_for(SPEC.strategy_id)
        if sr and sr.error:
            health.failed_cycles += 1
            print(f"[WARN] cycle error on {result.as_of}: {sr.error}", flush=True)
        elif sr and not sr.skipped:
            eval_count += 1
            _update_health(health, loop)
            print(
                f"[cycle {result.cycle_id}] as_of={result.as_of} "
                f"NAV={health.last_nav:.0f} fills={sr.sync_event.n_fills if sr.sync_event else 0} "
                f"risk_ok={sr.risk_approved}",
                flush=True,
            )

            # Stop if critical failure
            if sr.sync_event and not sr.sync_event.reconciled:
                health.reconciliation_failures += 1
                print("[CRITICAL] Reconciliation failed — stopping run per stopping condition.",
                      flush=True)
                break

            # Checkpoint
            if eval_count % checkpoint_every == 0:
                save_checkpoint(str(CHECKPOINT_PATH), loop)
                health.checkpoint_count += 1
                print(f"[checkpoint] saved at eval {eval_count}", flush=True)

    # Final checkpoint
    save_checkpoint(str(CHECKPOINT_PATH), loop)
    health.checkpoint_count += 1

    # Persist cycle records
    records_data = [r.to_dict() for r in loop.strategy_records(SPEC.strategy_id)]
    RECORDS_PATH.write_text(json.dumps(records_data, indent=2, default=str))

    # Persist health
    HEALTH_PATH.write_text(json.dumps(health.to_dict(), indent=2))

    return loop


# ── real-data live cycle ──────────────────────────────────────────────────────

def run_live_cycle(as_of: date, *, checkpoint_every: int = 4) -> PaperTradingLoop:
    """Run one PAPER_LIVE_FEED cycle using real Yahoo Finance data.

    Fetches real market observations for `as_of`, builds an M18 snapshot
    through the M20/M19 pipeline, and passes it to the existing M23 loop.
    Restores from checkpoint if one exists (enables incremental operation).

    REAL MARKET DATA: YES
    PAPER EXECUTION: YES
    LIVE EXECUTION: NO
    NO REAL CAPITAL DEPLOYED.
    """
    FORWARD_DATA_DIR.mkdir(parents=True, exist_ok=True)

    feed_cfg = LiveFeedConfig(
        universe=tuple(UNIVERSE),
        fetch_window_days=5,
        max_staleness_days=5,
    )
    feed = LiveFeedBuilder(feed_cfg)

    print(f"[live-feed] fetching real market data for as_of={as_of} …", flush=True)
    result = feed.fetch_snapshot(as_of)

    if result is None:
        print(f"[live-feed] WARN: could not build snapshot for {as_of} — no cycle recorded",
              flush=True)
        return None

    snap = result.snapshot
    n_spots = len(snap.spots)
    print(f"[live-feed] snapshot built: {n_spots}/{len(UNIVERSE)} securities present  "
          f"fingerprint={snap.fingerprint()[:16]}…", flush=True)
    if n_spots < len(UNIVERSE):
        missing = [s for s in UNIVERSE if s not in snap.spots]
        print(f"[live-feed] WARN: missing securities: {missing}", flush=True)

    registry = build_registry()
    loop = build_loop(registry, initial_capital=STARTING_CAPITAL)
    loop._config = loop._config.__class__(
        initial_capital=loop._config.initial_capital,
        permit_experimental=loop._config.permit_experimental,
        fail_closed=loop._config.fail_closed,
        validate_readiness=loop._config.validate_readiness,
        mode="PAPER_LIVE_FEED",
    )

    # Restore checkpoint if available
    if CHECKPOINT_PATH.exists():
        ckpt = load_checkpoint(str(CHECKPOINT_PATH))
        _restore_checkpoint(loop, ckpt)
        recs = loop.strategy_records(SPEC.strategy_id)
        print(f"[live-feed] checkpoint restored: {len(recs)} prior cycles", flush=True)

    loop_result = loop.process_snapshot(snap)
    sr = loop_result.result_for(SPEC.strategy_id)

    if loop_result.skipped or (sr and sr.skipped):
        skip_reason = (sr.skip_reason if sr else "") or loop_result.skip_reason or "not_due"
        print(f"[live-feed] cycle skipped: {skip_reason}", flush=True)
    elif sr and sr.error:
        print(f"[WARN] cycle error: {sr.error}", flush=True)
    else:
        recs = loop.strategy_records(SPEC.strategy_id)
        last_nav = recs[-1].nav if recs else STARTING_CAPITAL
        fills = sr.sync_event.n_fills if sr and sr.sync_event else 0
        print(
            f"[live-feed] cycle completed: NAV={last_nav:.2f}  fills={fills}  "
            f"risk_ok={sr.risk_approved if sr else 'n/a'}",
            flush=True,
        )

        if sr and sr.sync_event and not sr.sync_event.reconciled:
            print("[CRITICAL] reconciliation failed — stopping per stopping condition.",
                  flush=True)

    # Checkpoint after every live cycle
    save_checkpoint(str(CHECKPOINT_PATH), loop)

    # Persist updated cycle records
    records_data = [r.to_dict() for r in loop.strategy_records(SPEC.strategy_id)]
    RECORDS_PATH.write_text(json.dumps(records_data, indent=2, default=str))

    # Persist feed metrics
    feed_metrics_path = FORWARD_DATA_DIR / "feed_metrics.json"
    feed_metrics_path.write_text(json.dumps(feed.metrics.report(), indent=2))

    # Print feed metrics summary
    rpt = feed.metrics.report()
    print()
    print("=== FEED METRICS ===")
    print(f"provider:              {rpt['provider']}")
    print(f"observations_received: {rpt['observations_received']}")
    print(f"observations_rejected: {rpt['observations_rejected']}")
    print(f"pit_violations:        {rpt['pit_violations']}")
    print(f"stale_observations:    {rpt['stale_observations']}")
    print(f"missing_securities:    {rpt['missing_securities']}")
    print(f"avg_fetch_latency_s:   {rpt['avg_fetch_latency_s']:.3f}")
    print(f"avg_build_latency_s:   {rpt['avg_build_latency_s']:.3f}")
    print()
    print("REAL MARKET DATA: YES")
    print("PAPER EXECUTION: YES")
    print("LIVE EXECUTION: NO")
    print("NO REAL CAPITAL DEPLOYED.")
    print("NO STRATEGY PARAMETERS WERE OPTIMIZED USING FORWARD DATA.")

    return loop


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Mentisrex forward paper-trading driver")
    p.add_argument("--mode", default="SIMULATION",
                   choices=["SIMULATION", "PAPER_LIVE_FEED"],
                   help="SIMULATION: synthetic prices. PAPER_LIVE_FEED: real Yahoo Finance data.")
    p.add_argument("--cycles", type=int, default=12,
                   help="[SIMULATION] Number of monthly cycles")
    p.add_argument("--start", default="2026-01-01",
                   help="[SIMULATION] Start date for synthetic snapshots (YYYY-MM-DD)")
    p.add_argument("--as-of", default=None,
                   help="[PAPER_LIVE_FEED] Observation date (YYYY-MM-DD). Defaults to today.")
    p.add_argument("--checkpoint-every", type=int, default=4,
                   help="[SIMULATION] Checkpoint interval (evaluations)")
    args = p.parse_args()

    print("=" * 60)
    print("MENTISREX CONTROLLED FORWARD PAPER-TRADING ACTIVATION")
    print("EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED")
    print("NO REAL CAPITAL DEPLOYED.")
    print("=" * 60)
    print(f"strategy_id         : {SPEC.strategy_id}")
    print(f"strategy_version    : {SPEC.version}")
    print(f"strategy_fingerprint: {SPEC.configuration_fingerprint}")
    print(f"run_id              : {RUN_ID}")
    print(f"mode                : {args.mode}")
    print(f"starting_capital    : {STARTING_CAPITAL:,.0f} USD (paper only)")
    print("=" * 60)

    if args.mode == "PAPER_LIVE_FEED":
        from datetime import date as _date
        as_of = _date.fromisoformat(args.as_of) if args.as_of else _date.today()
        print(f"data_source         : Yahoo Finance (real, public, no credentials)")
        print(f"data_limitation     : Free/public — NOT institutional/exchange-grade data")
        print(f"as_of               : {as_of}")
        print("=" * 60)
        run_live_cycle(as_of)

    else:  # SIMULATION
        print(f"cycles              : {args.cycles}")
        print(f"data_limitation     : Synthetic simulation — not institutional data")
        print("=" * 60)
        start = date.fromisoformat(args.start)
        snapshots = _synthetic_snapshots(args.cycles, start)
        loop = run_loop(snapshots, checkpoint_every=args.checkpoint_every)
        fpr = loop.forward_record(SPEC.strategy_id)
        m = fpr.metrics()

        print()
        print("=== FORWARD OBSERVATION RESULTS ===")
        print(f"cycles accumulated : {m.n_cycles}")
        print(f"total_return       : {m.total_return:.4%}")
        print(f"max_drawdown       : {m.max_drawdown:.4%}")
        print(f"fill_rate          : {m.fill_rate:.2%}")
        print(f"risk_approval_rate : {m.risk_approval_rate:.2%}")
        print()
        print("NOTE: Short-sample results are OBSERVATIONAL EVIDENCE ONLY.")
        print("Economic conclusions require extended forward observation.")
        print(f"Evidence stored at: {FORWARD_DATA_DIR}")


if __name__ == "__main__":
    main()
