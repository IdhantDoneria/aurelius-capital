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
from mentisrex.research.forward_campaign import ForwardCampaign
from mentisrex.research.forward_campaign.runner import ForwardOperationsRunner
from mentisrex.research.forward_campaign.benchmark import BenchmarkPortfolio, fetch_spy_price
from mentisrex.research.forward_campaign.evidence_report import EvidenceReportBuilder
from mentisrex.paper import (
    AlpacaPaperBroker,
    BrokerMode,
    LiveTradingBlockedError,
    PaperAccountVerificationError,
)

# Import spec and logic (co-located in this package)
sys.path.insert(0, str(Path(__file__).parent))
from spec import SPEC, STARTING_CAPITAL, UNIVERSE
from logic import EqualWeightMomentumLogic

# ── forward run manifest constants (SIMULATION / legacy PAPER_LIVE_FEED) ──────
RUN_ID = "FORWARD_RUN_ew-momentum-exp_v1.0.0_20260812T000000Z"
FORWARD_DATA_DIR = _repo / "data" / "forward_runs" / RUN_ID
CHECKPOINT_PATH = FORWARD_DATA_DIR / "checkpoint.json"
RECORDS_PATH = FORWARD_DATA_DIR / "cycle_records.json"
MANIFEST_PATH = FORWARD_DATA_DIR / "run_manifest.json"
HEALTH_PATH = FORWARD_DATA_DIR / "run_health.json"

# ── PAPER_FORWARD campaign directory (isolated from SIMULATION) ────────────────
CAMPAIGN_ID = "FORWARD_CAMPAIGN_ew-momentum-exp_v1.0.0_20260813"
FORWARD_CAMPAIGN_DIR = _repo / "data" / "forward_campaign" / CAMPAIGN_ID


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


# ── PAPER_FORWARD campaign functions ─────────────────────────────────────────

def forward_init(data_dir: Path = FORWARD_CAMPAIGN_DIR) -> ForwardCampaign:
    """Initialize a fresh PAPER_FORWARD campaign.

    Creates isolated campaign state — never loads SIMULATION checkpoint.
    Idempotent: safe to call again if campaign_manifest.json already exists
    with the same campaign_id.
    """
    return ForwardCampaign.init(
        SPEC,
        EqualWeightMomentumLogic(UNIVERSE),
        data_dir=data_dir,
        universe=UNIVERSE,
        starting_capital=STARTING_CAPITAL,
        campaign_id=CAMPAIGN_ID,
    )


def forward_run(as_of: date, data_dir: Path = FORWARD_CAMPAIGN_DIR):
    """Run one PAPER_FORWARD cycle for as_of using real Yahoo Finance data.

    Idempotent: running twice for the same month returns ALREADY_SEALED.
    Restores only from the campaign checkpoint — never from SIMULATION state.

    REAL MARKET DATA: YES
    PAPER EXECUTION:  YES
    LIVE EXECUTION:   NO
    """
    campaign = _get_or_init_campaign(data_dir)
    result = campaign.run(as_of)
    _print_cycle_result(result, as_of)
    return result


def forward_resume(as_of: date, data_dir: Path = FORWARD_CAMPAIGN_DIR):
    """Resume an existing PAPER_FORWARD campaign and run as_of cycle."""
    manifest_path = data_dir / "campaign_manifest.json"
    if not manifest_path.exists():
        print(f"[forward_resume] No campaign at {data_dir}. Running forward_init first.")
        return forward_run(as_of, data_dir)
    campaign = ForwardCampaign.resume(SPEC, EqualWeightMomentumLogic(UNIVERSE), data_dir)
    result = campaign.run(as_of)
    _print_cycle_result(result, as_of)
    return result


def forward_status(data_dir: Path = FORWARD_CAMPAIGN_DIR) -> dict:
    """Print and return current campaign status."""
    manifest_path = data_dir / "campaign_manifest.json"
    if not manifest_path.exists():
        print("[forward_status] No campaign initialized at", data_dir)
        return {}
    campaign = ForwardCampaign.resume(SPEC, EqualWeightMomentumLogic(UNIVERSE), data_dir)
    st = campaign.status()
    print()
    print("=== PAPER_FORWARD CAMPAIGN STATUS ===")
    print(f"campaign_id          : {st['campaign_id']}")
    print(f"strategy_id          : {st['strategy_id']}")
    print(f"strategy_fingerprint : {st['strategy_fingerprint']}")
    print(f"mode                 : {st['mode']}")
    print(f"n_sealed_cycles      : {st['n_sealed_cycles']}")
    print(f"n_successful_cycles  : {st['n_successful_cycles']}")
    print(f"n_failed_cycles      : {st['n_failed_cycles']}")
    print(f"n_skipped_cycles     : {st['n_skipped_cycles']}")
    print(f"current_nav          : {st['current_nav']:,.2f} USD")
    print(f"last_evaluation_date : {st['last_evaluation_date']}")
    print(f"checkpoint_exists    : {st['checkpoint_exists']}")
    print()
    print(f"REAL MARKET DATA: {st['real_market_data']}")
    print(f"PAPER EXECUTION:  {st['paper_execution']}")
    print(f"LIVE EXECUTION:   {st['live_execution']}")
    print()

    # performance summary
    from mentisrex.research.forward_campaign.ledger import ForwardLedger
    ledger = ForwardLedger(data_dir)
    summary = ledger.performance_summary()
    print("=== PERFORMANCE SUMMARY ===")
    print(f"cumulative_return    : {summary.cumulative_return:.4%}")
    print(f"max_drawdown         : {summary.max_drawdown:.4%}")
    print(f"annualized_return    : "
          f"{summary.annualized_return:.4%} [{summary.annualized_return_label}]"
          if summary.annualized_return is not None
          else f"annualized_return    : N/A [{summary.annualized_return_label}]")
    print(f"sharpe               : "
          f"{summary.sharpe:.3f} [{summary.sharpe_label}]"
          if summary.sharpe is not None
          else f"sharpe               : N/A [{summary.sharpe_label}]")
    print(f"total_fills          : {summary.total_fills}")
    print(f"pit_violations       : {summary.total_pit_violations}")
    print()
    print("NOTE: Observational evidence only. Economic validity requires extended forward observation.")
    return st


def forward_benchmark(as_of: date, data_dir: Path = FORWARD_CAMPAIGN_DIR, *,
                      spy_price: float | None = None) -> None:
    """Run benchmark evaluation for as_of using real SPY price (or supplied price).

    Idempotent: if a sealed benchmark record for this cycle already exists,
    the existing record is returned and no new record is written.

    REAL MARKET DATA: YES (SPY via yfinance unless spy_price is supplied)
    PAPER EXECUTION:  YES
    LIVE EXECUTION:   NO
    NO REAL CAPITAL DEPLOYED.
    """
    from mentisrex.research.forward_campaign.record import make_forward_cycle_id
    cycle_id = make_forward_cycle_id(SPEC.strategy_id, SPEC.version, as_of)
    manifest_path = data_dir / "campaign_manifest.json"
    if not manifest_path.exists():
        print(f"[forward_benchmark] No campaign at {data_dir}. Run forward_init first.")
        return

    manifest = json.loads(manifest_path.read_text())
    campaign_id = manifest["campaign_id"]

    # fetch SPY price
    if spy_price is None:
        print(f"[forward_benchmark] fetching SPY price for {as_of} …", flush=True)
        spy_price = fetch_spy_price(as_of)
    if spy_price is None or spy_price <= 0:
        print(f"[forward_benchmark] WARN: could not fetch SPY price for {as_of} — skipping.")
        return

    print(f"[forward_benchmark] SPY price as_of={as_of}: ${spy_price:.2f}", flush=True)
    bp = BenchmarkPortfolio(data_dir, inception_nav=STARTING_CAPITAL)
    rec = bp.evaluate(cycle_id, as_of=as_of, spy_price=spy_price,
                      campaign_id=campaign_id)
    print()
    print("=== BENCHMARK CYCLE RESULT ===")
    print(f"cycle_id         : {rec.cycle_id}")
    print(f"benchmark_symbol : {rec.benchmark_symbol}")
    print(f"as_of            : {as_of}")
    print(f"spy_price        : ${rec.spy_price:.2f}")
    print(f"shares           : {rec.shares:.4f}")
    print(f"ending_nav       : ${rec.ending_nav:,.2f}")
    print(f"period_return    : {rec.period_return:.4%}")
    print(f"cumulative_return: {rec.cumulative_return:.4%}")
    print(f"sealed_at        : {rec.sealed_at}")
    print(f"is_inception     : {rec.is_inception_cycle}")
    print()
    print("NOTE: Price return only.  SPY dividends are NOT captured.")
    print("NO REAL CAPITAL DEPLOYED.")


def forward_evidence_report(data_dir: Path = FORWARD_CAMPAIGN_DIR):  # -> ForwardEvidenceReport
    """Generate and print the M27 forward evidence report."""
    manifest_path = data_dir / "campaign_manifest.json"
    if not manifest_path.exists():
        print(f"[forward_evidence_report] No campaign at {data_dir}.")
        return None
    builder = EvidenceReportBuilder(
        campaign_dir=data_dir,
        strategy_id=SPEC.strategy_id,
        strategy_version=SPEC.version,
        strategy_fingerprint=SPEC.configuration_fingerprint,
        universe=UNIVERSE,
        initial_capital=STARTING_CAPITAL,
    )
    report = builder.build()
    report.print_summary()
    # persist report JSON
    report_path = data_dir / "forward_evidence_report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, default=str))
    print(f"\nReport saved to: {report_path}")
    return report


# ── M28 Alpaca paper broker CLI functions ─────────────────────────────────────


def alpaca_paper_status() -> dict:
    """Connect to Alpaca PAPER account and print non-credential status report.

    REAL ALPACA PAPER ACCOUNT: YES (if credentials present)
    LIVE EXECUTION:            NO
    REAL CAPITAL:              NO

    Required env vars:
        ALPACA_PAPER_API_KEY
        ALPACA_PAPER_API_SECRET
    """
    print()
    print("=== ALPACA PAPER BROKER STATUS (M28) ===")
    print(f"broker    : ALPACA")
    print(f"mode      : PAPER (paper-api.alpaca.markets)")
    print(f"live exec : NO")
    print(f"real cap  : NO")
    print()

    key = Path("/dev/null").parent  # sentinel; real check below
    missing = []
    if not __import__("os").environ.get("ALPACA_PAPER_API_KEY", ""):
        missing.append("ALPACA_PAPER_API_KEY")
    if not __import__("os").environ.get("ALPACA_PAPER_API_SECRET", ""):
        missing.append("ALPACA_PAPER_API_SECRET")

    if missing:
        print(f"ALPACA CONNECTIVITY: NOT VERIFIED")
        print(f"REASON: Missing env vars: {', '.join(missing)}")
        print()
        print("To enable Alpaca paper connectivity:")
        for var in missing:
            print(f"    export {var}=<your-paper-{var.lower()}>")
        print()
        print("Paper credentials are available at https://app.alpaca.markets/paper-trading")
        return {"connectivity": "NOT_VERIFIED", "missing_credentials": missing}

    try:
        broker = AlpacaPaperBroker(
            strategy_id=SPEC.strategy_id,
            strategy_fingerprint=SPEC.configuration_fingerprint,
        )
        report = broker.status_report()
        broker.close()

        print(f"ALPACA CONNECTIVITY:     {report.get('connectivity', 'OK')}")
        print(f"ALPACA ENVIRONMENT:      {report.get('environment', 'PAPER')}")
        print(f"ACCOUNT VERIFIED (PAPER): {'YES' if report.get('paper_verified') else 'NO'}")
        print(f"account_id           : {report.get('account_id', 'N/A')}")
        print(f"account_status       : {report.get('account_status', 'N/A')}")
        print(f"equity               : {report.get('equity', 'N/A')}")
        print(f"cash                 : {report.get('cash', 'N/A')}")
        print(f"buying_power         : {report.get('buying_power', 'N/A')}")
        print(f"open_orders          : {report.get('open_orders', 'N/A')}")
        print()
        print(f"LIVE EXECUTION:          {report.get('live_execution', 'NO')}")
        print(f"REAL CAPITAL:            {report.get('real_capital', 'NO')}")
        print(f"LIVE ENDPOINT SUPPORTED: {report.get('live_endpoint_supported', 'NO')}")
        return report

    except PaperAccountVerificationError as e:
        print(f"ALPACA CONNECTIVITY: FAILED")
        print(f"REASON: {e}")
        print()
        print("Verify ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET are paper credentials.")
        return {"connectivity": "FAILED", "error": str(e)}

    except LiveTradingBlockedError as e:
        print(f"ALPACA CONNECTIVITY: BLOCKED")
        print(f"REASON: {e}")
        return {"connectivity": "BLOCKED", "error": str(e)}


def alpaca_paper_order(
    symbol: str,
    side: str,
    quantity: str,
    order_type: str = "market",
    cycle_id: str = "smoke-test",
) -> dict:
    """Submit one controlled paper order to Alpaca (M28 smoke test).

    REAL PAPER ORDER: YES (if credentials present)
    LIVE EXECUTION:   NO
    REAL CAPITAL:     NO

    Cancels the order after submission if order type is market (immediate fill
    not guaranteed). For testing purposes only.

    Required env vars:
        ALPACA_PAPER_API_KEY
        ALPACA_PAPER_API_SECRET
    """
    from decimal import Decimal as _D

    print()
    print("=== ALPACA PAPER ORDER SMOKE TEST (M28) ===")
    print(f"symbol     : {symbol}")
    print(f"side       : {side}")
    print(f"quantity   : {quantity}")
    print(f"order_type : {order_type}")
    print(f"cycle_id   : {cycle_id}")
    print()

    missing = []
    import os as _os
    if not _os.environ.get("ALPACA_PAPER_API_KEY", ""):
        missing.append("ALPACA_PAPER_API_KEY")
    if not _os.environ.get("ALPACA_PAPER_API_SECRET", ""):
        missing.append("ALPACA_PAPER_API_SECRET")
    if missing:
        print(f"PAPER ORDER SUBMITTED: NOT VERIFIED")
        print(f"REASON: Missing env vars: {', '.join(missing)}")
        return {"submitted": False, "reason": "missing_credentials", "missing": missing}

    try:
        broker = AlpacaPaperBroker(
            strategy_id=SPEC.strategy_id,
            strategy_fingerprint=SPEC.configuration_fingerprint,
        )

        rec = broker.submit_order(
            symbol=symbol,
            side=side,
            quantity=_D(quantity),
            order_type=order_type,
            cycle_id=cycle_id,
            risk_approved=True,
        )

        print(f"PAPER ORDER SUBMITTED:    YES")
        print(f"alpaca_order_id      : {rec.alpaca_order_id}")
        print(f"client_order_id      : {rec.client_order_id}")
        print(f"status               : {rec.status}")
        print(f"broker               : {rec.broker}")
        print(f"environment          : {rec.environment}")
        print(f"submitted_at         : {rec.submitted_at}")
        print()

        # Poll for status
        status_data = broker.get_order_status(rec.alpaca_order_id)
        current_status = status_data.get("status", "?")
        print(f"CURRENT STATUS:          {current_status}")

        # Retrieve fills if filled
        fills = broker.get_fills(rec.alpaca_order_id)
        if fills:
            f = fills[0]
            print(f"FILL:                    qty={f.quantity} @ ${f.fill_price:.4f}")
            print()
            print(f"PAPER ORDER RECONCILED:  YES")
        else:
            print(f"FILLS:                   pending / none yet")
            print()
            print(f"PAPER ORDER RECONCILED:  PENDING (order not yet filled)")

        # Cancel if still open (smoke test cleanup)
        if current_status in ("new", "pending_new", "accepted"):
            cancelled = broker.cancel_order(rec.alpaca_order_id)
            print(f"ORDER CANCELLED (cleanup): {'YES' if cancelled else 'NO'}")

        # Account reconciliation
        acc = broker.get_account()
        print()
        print(f"ACCOUNT AFTER ORDER:")
        print(f"  equity       : {acc['equity']}")
        print(f"  cash         : {acc['cash']}")
        print(f"  open_orders  : {acc['open_orders']}")
        print()
        print(f"LIVE EXECUTION: NO")
        print(f"REAL CAPITAL:   NO")

        broker.close()
        return {
            "submitted": True,
            "alpaca_order_id": rec.alpaca_order_id,
            "client_order_id": rec.client_order_id,
            "status": current_status,
            "fills": len(fills),
            "live_execution": "NO",
            "real_capital": "NO",
        }

    except (PaperAccountVerificationError, LiveTradingBlockedError) as e:
        print(f"PAPER ORDER SUBMITTED: NO")
        print(f"REASON: {e}")
        return {"submitted": False, "reason": str(e)}

    except RuntimeError as e:
        print(f"PAPER ORDER SUBMITTED: NO")
        print(f"REASON: {e}")
        return {"submitted": False, "reason": str(e)}


def _get_or_init_campaign(data_dir: Path) -> ForwardCampaign:
    """Resume if campaign exists, else init."""
    manifest_path = data_dir / "campaign_manifest.json"
    if manifest_path.exists():
        try:
            return ForwardCampaign.resume(SPEC, EqualWeightMomentumLogic(UNIVERSE), data_dir)
        except Exception:
            pass
    return forward_init(data_dir)


def _print_cycle_result(result, as_of: date) -> None:
    from mentisrex.research.forward_campaign.record import CycleStatus
    print()
    print("=== PAPER_FORWARD CYCLE RESULT ===")
    print(f"cycle_id  : {result.cycle_id}")
    print(f"as_of     : {as_of}")
    print(f"status    : {result.status}")
    if result.record:
        r = result.record
        print(f"ending_nav: {r.ending_nav:,.2f} USD")
        print(f"fills     : {r.fills}")
        print(f"risk_ok   : {r.risk_approved}")
        print(f"sealed_at : {r.sealed_at}")
    print()
    print(f"REAL MARKET DATA: YES")
    print(f"PAPER EXECUTION:  YES")
    print(f"LIVE EXECUTION:   NO")
    print(f"NO REAL CAPITAL DEPLOYED.")
    if result.status == CycleStatus.ALREADY_SEALED:
        print(f"NOTE: Cycle already sealed. No duplicate financial effect.")
    elif result.status == CycleStatus.SKIPPED:
        print(f"NOTE: Strategy not due. {result.message}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Mentisrex forward paper-trading driver")
    sub = p.add_subparsers(dest="subcommand")

    # forward_init
    pi = sub.add_parser("forward_init", help="Initialize a new PAPER_FORWARD campaign")
    pi.add_argument("--data-dir", default=str(FORWARD_CAMPAIGN_DIR))

    # forward_run
    pr = sub.add_parser("forward_run", help="Run one PAPER_FORWARD cycle (real data)")
    pr.add_argument("--as-of", default=None,
                    help="Observation date (YYYY-MM-DD). Defaults to today.")
    pr.add_argument("--data-dir", default=str(FORWARD_CAMPAIGN_DIR))

    # forward_resume
    pre = sub.add_parser("forward_resume", help="Resume PAPER_FORWARD campaign")
    pre.add_argument("--as-of", default=None)
    pre.add_argument("--data-dir", default=str(FORWARD_CAMPAIGN_DIR))

    # forward_status
    ps = sub.add_parser("forward_status", help="Show PAPER_FORWARD campaign status")
    ps.add_argument("--data-dir", default=str(FORWARD_CAMPAIGN_DIR))

    # forward_benchmark (M27): run benchmark evaluation for as_of
    pbm = sub.add_parser("forward_benchmark",
                         help="Run SPY benchmark evaluation for as_of (M27)")
    pbm.add_argument("--as-of", default=None)
    pbm.add_argument("--data-dir", default=str(FORWARD_CAMPAIGN_DIR))
    pbm.add_argument("--spy-price", type=float, default=None,
                     help="Override SPY price (offline use only)")

    # forward_evidence_report (M27): generate evidence report
    per = sub.add_parser("forward_evidence_report",
                         help="Generate M27 forward evidence report")
    per.add_argument("--data-dir", default=str(FORWARD_CAMPAIGN_DIR))

    # alpaca_paper_status (M28): Alpaca paper account status
    sub.add_parser(
        "alpaca_paper_status",
        help="Show Alpaca PAPER account status (M28). No orders submitted.",
    )

    # alpaca_paper_order (M28): controlled paper order smoke test
    pao = sub.add_parser(
        "alpaca_paper_order",
        help="Submit one controlled Alpaca PAPER order (M28 smoke test).",
    )
    pao.add_argument("--symbol", default="SPY", help="Security symbol (default: SPY)")
    pao.add_argument("--side", default="buy", choices=["buy", "sell"])
    pao.add_argument("--quantity", default="1", help="Share quantity (default: 1)")
    pao.add_argument("--order-type", default="market", choices=["market", "limit"],
                     dest="order_type")
    pao.add_argument("--cycle-id", default="smoke-test", dest="cycle_id")

    # forward_auto (M26): cron-safe check-and-run
    pau = sub.add_parser("forward_auto",
                         help="Check if cycle due and run it (cron-safe, idempotent)")
    pau.add_argument("--as-of", default=None,
                     help="Observation date (YYYY-MM-DD). Defaults to today.")
    pau.add_argument("--data-dir", default=str(FORWARD_CAMPAIGN_DIR))

    # legacy SIMULATION / PAPER_LIVE_FEED via --mode (backward compat)
    p.add_argument("--mode", default=None,
                   choices=["SIMULATION", "PAPER_LIVE_FEED"],
                   help="Legacy: SIMULATION or PAPER_LIVE_FEED mode")
    p.add_argument("--cycles", type=int, default=12)
    p.add_argument("--start", default="2026-01-01")
    p.add_argument("--as-of", default=None)
    p.add_argument("--checkpoint-every", type=int, default=4)
    args = p.parse_args()

    print("=" * 60)
    print("MENTISREX CONTROLLED FORWARD PAPER-TRADING ACTIVATION")
    print("EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED")
    print("NO REAL CAPITAL DEPLOYED.")
    print("=" * 60)
    print(f"strategy_id         : {SPEC.strategy_id}")
    print(f"strategy_version    : {SPEC.version}")
    print(f"strategy_fingerprint: {SPEC.configuration_fingerprint}")
    print("=" * 60)

    # ── M28 Alpaca paper broker subcommands ───────────────────────────────────
    if args.subcommand == "alpaca_paper_status":
        alpaca_paper_status()
        return

    if args.subcommand == "alpaca_paper_order":
        alpaca_paper_order(
            symbol=args.symbol,
            side=args.side,
            quantity=args.quantity,
            order_type=args.order_type,
            cycle_id=args.cycle_id,
        )
        return

    # ── PAPER_FORWARD subcommands ─────────────────────────────────────────────
    if args.subcommand == "forward_init":
        campaign = forward_init(Path(args.data_dir))
        print(f"[forward_init] Campaign initialized at: {args.data_dir}")
        print(f"campaign_id: {campaign._config.campaign_id}")
        return

    if args.subcommand in ("forward_run", "forward_resume"):
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
        print(f"data_source : Yahoo Finance (real, public, no credentials)")
        print(f"as_of       : {as_of}")
        print("=" * 60)
        if args.subcommand == "forward_run":
            forward_run(as_of, Path(args.data_dir))
        else:
            forward_resume(as_of, Path(args.data_dir))
        return

    if args.subcommand == "forward_status":
        forward_status(Path(args.data_dir))
        return

    if args.subcommand == "forward_benchmark":
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
        forward_benchmark(as_of, Path(args.data_dir), spy_price=args.spy_price)
        return

    if args.subcommand == "forward_evidence_report":
        forward_evidence_report(Path(args.data_dir))
        return

    if args.subcommand == "forward_auto":
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
        print(f"data_source : Yahoo Finance (real, public, no credentials)")
        print(f"as_of       : {as_of}")
        print("=" * 60)
        runner = ForwardOperationsRunner(
            SPEC,
            EqualWeightMomentumLogic(UNIVERSE),
            Path(args.data_dir),
            universe=UNIVERSE,
            starting_capital=STARTING_CAPITAL,
            campaign_id=CAMPAIGN_ID,
        )
        result = runner.check_and_run(as_of)
        _print_cycle_result(result, as_of)
        # show enriched operational status
        op = runner.operational_status()
        print("=== OPERATIONAL STATUS ===")
        print(f"runner_state          : {op.get('runner_state')}")
        print(f"next_expected_cycle   : {op.get('next_expected_cycle')}")
        if op.get("last_error"):
            print(f"last_error            : {op['last_error']}")
        return

    # ── Legacy --mode path (backward compat) ─────────────────────────────────
    mode = args.mode or "SIMULATION"
    print(f"mode                : {mode}")
    print(f"starting_capital    : {STARTING_CAPITAL:,.0f} USD (paper only)")
    print("=" * 60)

    if mode == "PAPER_LIVE_FEED":
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
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
