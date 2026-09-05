"""Daily runner, status, restart, backtest, and universe construction.

This is the one module in the package where printing to stdout is correct:
everything here is operator-facing. Structured events still go through
`get_logger`, and the config fingerprint is logged on every run so a change in
behaviour can be attributed to a parameter change or ruled out.

The order of operations in `run` comes from specification Table 27 and is not
to be reordered. The reason the risk gate sits at step 5, strictly before order
construction at step 7, is that a HALT drives the effective cap to zero and
therefore produces no orders at all — a gate evaluated after the orders were
built would be a report, not a control.

Exit codes: 0 OK, 2 quality fatal, 3 risk halt, 4 broker error.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from mentisrex.core.logging import get_logger
from mentisrex.programme import (
    allocator,
    backtest,
    data,
    execution,
    rates,
    reconcile,
    risk,
    sleeves,
)
from mentisrex.programme.config import RUNGS, ProgrammeConfig, ProgrammeError, load_config
from mentisrex.programme.state import StateStore, halt, restart

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_QUALITY_FATAL = 2
EXIT_RISK_HALT = 3
EXIT_BROKER_ERROR = 4

_DEFAULT_START = "2017-01-01"


# ── helpers ───────────────────────────────────────────────────────────────────


def _rule(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 70 - len(title)))


def _kv(label: str, value: object, width: int = 34) -> None:
    print(f"  {label:<{width}} {value}")


def _config_for(args: argparse.Namespace) -> ProgrammeConfig:
    cfg = load_config(getattr(args, "config", None), rung=getattr(args, "rung", "recommended"))
    if getattr(args, "state_dir", None):
        cfg = cfg.with_overrides(**{"state_dir": args.state_dir})
    return cfg


def _end_date(args: argparse.Namespace) -> str:
    return getattr(args, "end", None) or datetime.now(UTC).date().isoformat()


def _panel_and_mask(
    config: ProgrammeConfig, args: argparse.Namespace
) -> tuple[data.PricePanel, pd.DataFrame]:
    panel = data.build_panel(
        config,
        source=None,
        start=getattr(args, "start", None) or _DEFAULT_START,
        end=_end_date(args),
        db_path=getattr(args, "db", None),
    )
    mask = data.eligibility_mask(panel, config.universe)
    return panel, mask


def _broker_for(mode: str, panel: data.PricePanel, nav: float) -> execution.Broker:
    """`dryrun` never touches the network; `paper` and `live` both go to Alpaca.

    Alpaca's paper endpoint is a real broker API with real order semantics, so
    the only difference between the two here is which account the credentials
    resolve to. That is deliberate: the point of paper trading is to exercise
    exactly the path live trading will take.
    """
    if mode == "dryrun":
        return execution.DryRunBroker(starting_nav=nav, closes=panel.close.iloc[-1])
    return execution.AlpacaProgrammeBroker()


def _gate_as_of(args: argparse.Namespace, panel: data.PricePanel) -> pd.Timestamp | None:
    """Which instant the staleness check measures against.

    `--as-of` wins when given. Otherwise `paper` and `live` measure against
    wall-clock now, which is the only correct answer when real orders are about
    to be placed: a panel three weeks old must stop the run.

    `dryrun` defaults to the panel's own last bar instead. A dryrun exists to
    exercise the sequence over whatever history is on hand, and failing it at
    step three because the archive does not extend to today would mean the
    remaining six steps could never be exercised at all. The staleness of the
    data is still reported either way — it is just not fatal when nothing can
    be traded.
    """
    if getattr(args, "as_of", None):
        return pd.Timestamp(args.as_of)
    if getattr(args, "mode", None) == "dryrun":
        return panel.index[-1]
    return None


# ── run: the daily sequence (spec Table 27) ───────────────────────────────────


def cmd_run(args: argparse.Namespace) -> int:
    config = _config_for(args)
    store = StateStore(config.state_dir)
    state = store.load()
    fingerprint = config.fingerprint()
    logger.info(
        "programme_run_start",
        mode=args.mode,
        rung=args.rung,
        nav=args.nav,
        config_fingerprint=fingerprint,
    )
    _rule(f"MENTIS REX PROGRAMME v{config.version}  ·  {args.mode}  ·  rung={args.rung}")
    _kv("config fingerprint", fingerprint)

    if state.halted and args.mode != "dryrun":
        print(f"\n  HALTED: {state.halt_reason}")
        print("  A halt requires a human restart. There is no automatic path back.")
        print('  mrx restart --operator "<name>" --note "<written justification>"')
        return EXIT_RISK_HALT

    # 2 · 09:00 — build the panel (done before reconciliation so prices exist)
    _rule("09:00  panel")
    panel, mask = _panel_and_mask(config, args)
    _kv("dates", f"{panel.index.min().date()} .. {panel.index.max().date()}")
    _kv("rows / columns", f"{len(panel.index)} / {len(panel.columns)}")

    # 3 · 09:15 — quality gate. Any fatal means no orders and the book is held.
    _rule("09:15  quality gate")
    report = data.quality_gate(panel, mask, config, as_of=_gate_as_of(args, panel))
    _kv("eligible names", report.n_eligible)
    _kv("staleness (trading days)", report.staleness_days)
    _kv("missing fraction", f"{report.missing_fraction:.1%}")
    for warning in report.warnings:
        print(f"  WARN  {warning}")
    if not report.ok:
        for fatal in report.fatal:
            print(f"  FATAL {fatal}")
        print("\n  No orders today. The existing book is held. Never trade on old prices.")
        store.append_audit(
            {
                "event": "quality_fatal",
                "fatal": list(report.fatal),
                "config_fingerprint": fingerprint,
            }
        )
        return EXIT_QUALITY_FATAL

    # 1 · 08:30 — reconcile yesterday against target (needs prices, so it runs here)
    _rule("08:30  reconciliation")
    nav = float(args.nav)
    broker = _broker_for(args.mode, panel, nav)
    try:
        positions = broker.positions()
        if args.mode != "dryrun":
            nav = broker.nav()
    except NotImplementedError as exc:
        print(f"  broker cannot report positions: {exc}")
        positions = {}
    prices = panel.close.iloc[-1]
    prior_target = _load_prior_target(config)
    recon = reconcile.reconcile(
        target=prior_target if prior_target is not None else pd.Series(dtype="float64"),
        positions=positions,
        prices=prices,
        nav=nav,
        config=config,
        as_of=panel.index[-1],
    )
    _kv("positions held", recon.n_positions)
    _kv("total drift (bps of NAV)", f"{recon.total_drift_bps:.1f}")
    if recon.drifts:
        for drift in recon.drifts[:10]:
            print(f"  DRIFT {drift.symbol:<8} {drift.drift_bps:+.1f} bp")
        if args.mode != "dryrun":
            print("\n  Drift beyond 25 bp per name is investigated before trading.")
            return EXIT_QUALITY_FATAL

    # 4 · 15:30 — signals, sleeves, combine at the ramp's effective cap
    _rule("15:30  signals, sleeves, allocation")
    built = sleeves.build_sleeves(panel, mask, config)
    base_cap = min(risk.deployment_cap(state.quarters_live), config.allocator.gross_cap)
    multipliers = risk.sleeve_health(
        {name: sleeve.gross_returns for name, sleeve in built.items()},
        panel.index[-1],
        config.risk,
    )
    book = allocator.combine(
        built, panel, config, effective_cap=base_cap, sleeve_multipliers=multipliers
    )
    _kv("deployment cap (ramp)", f"{base_cap:.2f}x  (quarter {state.quarters_live + 1})")
    _kv("gross / net", f"{book.gross.iloc[-1]:.3f}x / {book.net.iloc[-1]:.3f}x")
    _kv("long / short", f"{book.long_exposure.iloc[-1]:.3f}x / {book.short_exposure.iloc[-1]:.3f}x")
    for name, mult in sorted(multipliers.items()):
        if mult != 1.0:
            print(f"  SLEEVE {name} de-risked to {mult:.0%} on rolling 12m Sharpe")

    # 5 · 15:35 — risk gate. Thirteen checks, before any order is built.
    _rule("15:35  risk gate")
    target = book.target_weights.iloc[-1]
    non_bench = target.drop(labels=[config.universe.benchmark], errors="ignore")
    # The daily-loss breakers need the book's most recent REALISED net return,
    # not a placeholder. Computing the return series here is cheap relative to
    # building the sleeves and is the only honest way to arm DAILY_LOSS_WARN and
    # DAILY_LOSS_HALT — a hard-coded zero would leave both permanently disarmed.
    realised = allocator.book_returns(
        book, panel, rates.policy_rate_path(panel.index), config
    ).net.dropna()
    inputs = risk.RiskInputs(
        as_of=panel.index[-1],
        drawdown=state.drawdown,
        daily_return=float(realised.iloc[-1]) if len(realised) else 0.0,
        realised_vol_21d=_realised_vol(panel, config),
        proposed_gross=float(book.gross.iloc[-1]),
        proposed_net=float(book.net.iloc[-1]),
        max_abs_position=float(non_bench.abs().max()),
        proposed_turnover=float(book.turnover.iloc[-1]),
        n_eligible=report.n_eligible,
        panel_staleness_days=report.staleness_days,
        realised_cost_bps=recon.realised_cost_bps,
        base_cap=base_cap,
    )
    verdict = risk.evaluate(inputs, config.risk)
    for breach in verdict.breaches:
        print(
            f"  {breach.severity.value:<6} {breach.code:<20} "
            f"observed {breach.observed:.4f} vs {breach.threshold:.4f}"
        )
    if not verdict.breaches:
        print("  clean — no breaker fired")
    _kv("effective cap", f"{verdict.effective_cap:.3f}x")

    if verdict.halted:
        halt(store, "; ".join(b.code for b in verdict.breaches if b.severity.value == "HALT"))
        print("\n  HALT. Flatten to cash. Manual restart required, with a written justification.")
        return EXIT_RISK_HALT
    if verdict.derisked:
        book = allocator.combine(
            built,
            panel,
            config,
            effective_cap=verdict.effective_cap,
            sleeve_multipliers=multipliers,
        )
        target = book.target_weights.iloc[-1]
        print(f"  DERISK applied — book rebuilt at {verdict.effective_cap:.3f}x")

    # 6 · 15:40 — borrow filter. Neutrality is preserved; gross is surrendered.
    _rule("15:40  borrow filter")
    shorts = [s for s in target.index if target[s] < 0]
    try:
        shortable = broker.shortable(shorts)
    except NotImplementedError as exc:
        logger.warning("borrow_availability_unavailable", error=str(exc))
        print(f"  borrow availability unavailable ({exc.__class__.__name__});")
        print("  assuming every short is borrowable — this is optimistic, see the build report")
        shortable = dict.fromkeys(shorts, True)
    gross_before = float(target.abs().sum())
    target = execution.borrow_filter(target, shortable, config, config.universe.benchmark)
    blocked = [s for s in shorts if not shortable.get(s, False)]
    _kv("shorts proposed / blocked", f"{len(shorts)} / {len(blocked)}")
    _kv("gross before / after", f"{gross_before:.3f}x / {float(target.abs().sum()):.3f}x")

    # 7 · 15:42 — orders, suppressing anything under $250
    _rule("15:42  orders")
    current = _current_weights(positions, prices, nav)
    order_set = execution.build_orders(target, current, nav, prices, config, panel.index[-1])
    buys = sum(1 for o in order_set.orders if o.side == "BUY")
    sells = len(order_set.orders) - buys
    _kv("orders (buy / sell)", f"{len(order_set.orders)}  ({buys} / {sells})")
    _kv("suppressed under $250", len(order_set.suppressed))
    _kv("gross / net after filter", f"{order_set.gross:.3f}x / {order_set.net:.3f}x")
    if inputs.proposed_turnover > config.risk.turnover_spike:
        print("\n  TURNOVER_SPIKE — order set held for manual review, nothing submitted.")
        return EXIT_OK

    # 8 · 15:45 — submit
    _rule("15:45  submit")
    if args.mode == "dryrun":
        for order in order_set.orders[:20]:
            print(
                f"  {order.side:<4} {order.symbol:<8} {order.quantity:>8} sh  "
                f"${order.notional:>12,.0f}  target {order.target_weight:+.4f}"
            )
        if len(order_set.orders) > 20:
            print(f"  ... and {len(order_set.orders) - 20} more")
        print("\n  dryrun — nothing submitted.")
    else:
        try:
            ids = broker.submit_moc(order_set.orders)
            _kv("submitted (MOC, tif=cls)", len(ids))
        except Exception as exc:
            logger.error("broker_submit_failed", error=str(exc))
            print(f"  broker error: {exc}")
            return EXIT_BROKER_ERROR

    # 9 · 16:15 — persist state atomically, append the audit record
    _rule("16:15  state and audit")
    state.nav = nav
    state.high_water_mark = max(state.high_water_mark, nav)
    state.last_run_date = str(panel.index[-1].date())
    state.config_fingerprint = fingerprint
    state.sleeve_health = multipliers
    if state.first_trade_date is None and args.mode != "dryrun":
        state.first_trade_date = state.last_run_date
    if args.mode != "dryrun":
        store.save(state)
        _save_target(config, target)
    store.append_audit(
        {
            "event": "run",
            "mode": args.mode,
            "rung": args.rung,
            "config_fingerprint": fingerprint,
            "nav": nav,
            "gross": float(order_set.gross),
            "net": float(order_set.net),
            "n_orders": len(order_set.orders),
            "breaches": [b.code for b in verdict.breaches],
        }
    )
    _kv("state written", "yes" if args.mode != "dryrun" else "no (dryrun)")
    print()
    return EXIT_OK


def _realised_vol(panel: data.PricePanel, config: ProgrammeConfig) -> float:
    window = config.risk.vol_ceiling_window
    rets = panel.benchmark_returns.tail(window).dropna()
    if len(rets) < 2:
        return 0.0
    return float(rets.std(ddof=1) * (252.0**0.5))


def _current_weights(positions: dict[str, float], prices: pd.Series, nav: float) -> pd.Series:
    if nav <= 0 or not positions:
        return pd.Series(0.0, index=prices.index, dtype="float64")
    held = pd.Series(positions, dtype="float64").reindex(prices.index).fillna(0.0)
    return (held * prices.astype("float64")).fillna(0.0) / nav


def _target_path(config: ProgrammeConfig) -> Path:
    return Path(config.state_dir) / "last_target.json"


def _save_target(config: ProgrammeConfig, target: pd.Series) -> None:
    path = _target_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: float(v) for k, v in target.items()}, indent=2))


def _load_prior_target(config: ProgrammeConfig) -> pd.Series | None:
    path = _target_path(config)
    if not path.exists():
        return None
    return pd.Series(json.loads(path.read_text()), dtype="float64")


# ── other commands ────────────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> int:
    config = _config_for(args)
    state = StateStore(config.state_dir).load()
    cap = min(risk.deployment_cap(state.quarters_live), config.allocator.gross_cap)
    _rule("STATUS")
    _kv("config fingerprint", config.fingerprint())
    _kv("version / rung", f"{config.version} / {args.rung}")
    _kv("NAV", f"${state.nav:,.0f}")
    _kv("high-water mark", f"${state.high_water_mark:,.0f}")
    _kv("drawdown", f"{state.drawdown:.2%}")
    _kv("quarters live", state.quarters_live)
    _kv("deployment cap", f"{cap:.2f}x of a {config.allocator.gross_cap:.2f}x target")
    _kv("first trade / last run", f"{state.first_trade_date} / {state.last_run_date}")
    _kv("halted", f"YES — {state.halt_reason}" if state.halted else "no")
    if state.sleeve_health:
        derisked = {k: v for k, v in state.sleeve_health.items() if v != 1.0}
        _kv("sleeves de-risked", derisked or "none")
    print()
    return EXIT_OK


def cmd_restart(args: argparse.Namespace) -> int:
    config = _config_for(args)
    store = StateStore(config.state_dir)
    try:
        restart(store, args.operator, args.note)
    except ProgrammeError as exc:
        print(f"  refused: {exc}")
        return EXIT_RISK_HALT
    print(f"  restarted by {args.operator}: {args.note}")
    return EXIT_OK


def cmd_quality(args: argparse.Namespace) -> int:
    config = _config_for(args)
    panel, mask = _panel_and_mask(config, args)
    report = data.quality_gate(panel, mask, config, as_of=_gate_as_of(args, panel))
    _rule("QUALITY GATE")
    _kv("as of", report.as_of.date())
    _kv("eligible names", report.n_eligible)
    _kv("staleness (trading days)", report.staleness_days)
    _kv("missing fraction", f"{report.missing_fraction:.1%}")
    for warning in report.warnings:
        print(f"  WARN  {warning}")
    for fatal in report.fatal:
        print(f"  FATAL {fatal}")
    print(f"\n  {'OK — clear to trade' if report.ok else 'FATAL — no orders, hold the book'}\n")
    return EXIT_OK if report.ok else EXIT_QUALITY_FATAL


def cmd_ingest(args: argparse.Namespace) -> int:
    config = _config_for(args)
    panel, _ = _panel_and_mask(config, args)
    _rule("INGEST")
    _kv("dates", f"{panel.index.min().date()} .. {panel.index.max().date()}")
    _kv("rows / columns", f"{len(panel.index)} / {len(panel.columns)}")
    _kv("cached under", Path(config.data_dir) / "ohlcv")
    print()
    return EXIT_OK


def cmd_universe(args: argparse.Namespace) -> int:
    """Materialise the ticker file (ADDENDUM A.5 of the module contract).

    Committed rather than computed at run time, so a run is reproducible and a
    change of universe is a reviewable diff rather than a silent drift.
    """
    config = _config_for(args)
    source = data.DuckDBSource(args.db, config.universe.benchmark)
    inventory = source.available_symbols(min_bars=args.min_bars)
    last = pd.Timestamp(inventory["last_date"].max())
    keep = inventory[
        (inventory["n_bars"] >= args.min_bars)
        & (inventory["median_dollar_volume"] >= config.universe.min_dollar_volume)
        & (inventory["last_date"] >= last - pd.Timedelta(days=args.max_stale_days))
    ].head(args.limit)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "# Mentis Rex Programme — US single-name universe",
        f"# generated {generated} by `mrx universe`",
        f"# source: {source.db_path}",
        f"# filter: n_bars >= {args.min_bars}, median dollar volume >= "
        f"${config.universe.min_dollar_volume:,.0f}, last bar within "
        f"{args.max_stale_days} days of {last.date()}",
        f"# {len(keep)} names, sorted by median dollar volume descending",
        f"# benchmark {config.universe.benchmark} is NOT listed here — it is not in the",
        "# store and is fetched separately; see data.py's BENCHMARK note.",
        "",
    ]
    lines.extend(str(sym) for sym in keep["symbol"])
    out.write_text("\n".join(lines) + "\n")

    _rule("UNIVERSE")
    _kv("inventory (>= min_bars)", len(inventory))
    _kv("passing all filters", len(keep))
    _kv("written to", out)
    if len(keep) < 500:
        print(
            f"\n  NOTE  the specification's own study used 657 tickers (median 593 "
            f"eligible).\n        This universe is {len(keep)}. A smaller universe raises "
            "return and\n        worsens drawdown — see Table 17's universe-shrinkage row."
        )
    print()
    return EXIT_OK


def cmd_reconcile(args: argparse.Namespace) -> int:
    config = _config_for(args)
    panel, _ = _panel_and_mask(config, args)
    broker = _broker_for(args.mode, panel, float(args.nav))
    prior = _load_prior_target(config)
    if prior is None:
        print("  no prior target on file — nothing to reconcile against.")
        return EXIT_OK
    report = reconcile.reconcile(
        target=prior,
        positions=broker.positions(),
        prices=panel.close.iloc[-1],
        nav=float(args.nav),
        config=config,
        as_of=panel.index[-1],
    )
    _rule("RECONCILIATION")
    _kv("positions", report.n_positions)
    _kv("total drift (bps of NAV)", f"{report.total_drift_bps:.1f}")
    _kv("realised / modelled cost", f"{report.realised_cost_bps} / {report.modelled_cost_bps}")
    for drift in report.drifts:
        print(
            f"  DRIFT {drift.symbol:<8} target {drift.target_weight:+.4f} "
            f"actual {drift.actual_weight:+.4f}  {drift.drift_bps:+.1f} bp"
        )
    print(f"\n  {'OK' if report.ok else 'investigate before trading'}\n")
    return EXIT_OK


def cmd_backtest(args: argparse.Namespace) -> int:
    config = _config_for(args)
    panel, _ = _panel_and_mask(config, args)
    policy = rates.policy_rate_path(panel.index, source=args.rates)
    result = backtest.run_backtest(config, panel, policy)
    _rule(f"BACKTEST  ·  rung={args.rung}  ·  fingerprint={result.config_fingerprint}")
    for key, value in result.stats.items():
        _kv(key, f"{value:,.4f}" if isinstance(value, float) else value)
    print("\n  Backtested means hypothetical: simulated results on a survivorship-biased")
    print("  sample, produced with full knowledge of what happened in the period.\n")
    return EXIT_OK


# ── argument parsing ──────────────────────────────────────────────────────────


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, help="TOML/JSON overrides, dotted paths")
    parser.add_argument(
        "--rung",
        default="recommended",
        choices=sorted(RUNGS),
        help="deployment rung (spec Table 7)",
    )
    parser.add_argument("--db", default=None, help="path to analytics.duckdb")
    parser.add_argument("--start", default=None, help=f"panel start (default {_DEFAULT_START})")
    parser.add_argument("--end", default=None, help="panel end (default: today)")
    parser.add_argument("--state-dir", default=None, help="override the state directory")
    parser.add_argument(
        "--as-of",
        default=None,
        help="evaluate the quality gate as of this date (default: now; "
        "dryrun defaults to the panel's last bar)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mrx",
        description="Mentis Rex Capital — US Equity Systematic Programme v3.0",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="the daily sequence (spec Table 27)")
    _add_common(run)
    run.add_argument("--mode", default="dryrun", choices=["dryrun", "paper", "live"])
    run.add_argument("--nav", type=float, default=1_000_000.0)
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="persisted state, drawdown, ramp, halt")
    _add_common(status)
    status.set_defaults(func=cmd_status)

    rst = sub.add_parser("restart", help="clear a halt (requires operator and note)")
    _add_common(rst)
    rst.add_argument("--operator", required=True)
    rst.add_argument("--note", required=True)
    rst.set_defaults(func=cmd_restart)

    qual = sub.add_parser("quality", help="run the quality gate alone")
    _add_common(qual)
    qual.set_defaults(func=cmd_quality)

    ing = sub.add_parser("ingest", help="refresh the panel cache")
    _add_common(ing)
    ing.set_defaults(func=cmd_ingest)

    uni = sub.add_parser("universe", help="regenerate the ticker file")
    _add_common(uni)
    uni.add_argument("--limit", type=int, default=700)
    uni.add_argument("--min-bars", type=int, default=756, help="3 years of trading days")
    uni.add_argument("--max-stale-days", type=int, default=30)
    uni.add_argument("--out", default="config/universe_us.txt")
    uni.set_defaults(func=cmd_universe)

    rec = sub.add_parser("reconcile", help="target versus actual")
    _add_common(rec)
    rec.add_argument("--mode", default="dryrun", choices=["dryrun", "paper", "live"])
    rec.add_argument("--nav", type=float, default=1_000_000.0)
    rec.set_defaults(func=cmd_reconcile)

    bt = sub.add_parser("backtest", help="run the research harness")
    _add_common(bt)
    bt.add_argument("--rates", default="embedded", choices=["embedded", "fred"])
    bt.set_defaults(func=cmd_backtest)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Any = args.func
    try:
        return int(handler(args))
    except ProgrammeError as exc:
        logger.error("programme_command_failed", command=args.command, error=str(exc))
        print(f"\n  {type(exc).__name__}: {exc}")
        return EXIT_QUALITY_FATAL


if __name__ == "__main__":
    raise SystemExit(main())
