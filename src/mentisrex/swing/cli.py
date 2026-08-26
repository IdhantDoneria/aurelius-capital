"""Command-line entry points for the swing programme.

The point of `targets` is to be the seam between this research code and an
execution system: it emits the book to hold, for one date, as a flat table.
It deliberately produces *weights and shares*, not orders -- position sizing
is a strategy decision and belongs here, while order slicing, venue choice
and risk checks belong to the execution system that already exists.

    python -m mentisrex.swing.cli targets --strategy lastlight --equity 25e6

Timing contract: the row for date `d` is computed from information available
by 15:45 ET on `d`, and is the book to be *entered in that day's closing
auction*. For a sleeve that exits at the next open, the same call on the
following day returns a flat book for the names it is exiting.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .construction import OverlayConfig
from .data import load
from .execution import AlpacaSwingBroker, build_orders
from .strategies import Lastlight, LastlightConfig, Nightfall, NightfallConfig
from .strategies.base import StagingConfig

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")
EARNINGS_TAIL = 3
"""Sessions at the end of a historical panel that the forward earnings gate
cannot evaluate. Matches `data.load`'s `earnings_window`."""


def _build(name: str, ds, equity: float, overlay: OverlayConfig, warmup: int):
    staging = StagingConfig(hold_days=1, stage=False)
    common = dict(
        beta=ds.beta, factor_loadings=ds.factor_loadings, tradable=ds.panel.tradable,
        adv_dollar=ds.cube["addv60"], equity=equity, warmup_days=warmup,
    )
    if name == "nightfall":
        return Nightfall(ds.cube, overlay, staging,
                         config=NightfallConfig(mode="overnight"), **common)
    push = "close_push" if np.isfinite(ds.cube["close_push"]).any() else "close_push_daily"
    s = Lastlight(ds.cube, overlay, staging,
                  config=LastlightConfig(push_source=push), vix=ds.vix, **common)
    s.overnight_only = True
    return s


def cmd_targets(args) -> int:
    ds = load(features=args.features, start=args.start, end=args.end, tier=args.tier)
    overlay = OverlayConfig(
        target_vol=args.target_vol, gross_cap=args.gross_cap,
        max_weight=args.max_weight, n_stat_factors=3,
        max_participation=args.max_participation,
    )
    strat = _build(args.strategy, ds, args.equity, overlay, args.warmup)

    asof = pd.Timestamp(args.date) if args.date else ds.dates[-1]
    idx = int(np.searchsorted(ds.dates, asof))
    if idx >= len(ds.dates) or ds.dates[idx] != asof:
        raise SystemExit(f"{asof.date()} is not a session in the feature panel")
    if idx < strat.warmup():
        raise SystemExit(f"{asof.date()} is inside the {strat.warmup()}-session warm-up")

    # The staging queue and the volatility estimate are path-dependent, so the
    # book has to be walked forward to the requested date rather than computed
    # at it. Cheap enough to do on every call, and it removes a whole class of
    # "why is live different from the backtest" question.
    for t in range(strat.warmup(), idx + 1):
        w = strat._target(t)

    # The earnings gate needs to look a few sessions *forward*, which a
    # historical file cannot do at its own end: `load` conservatively marks
    # the final sessions as "near earnings", so they gate to an empty book.
    # In live use the forward calendar is available and this does not arise --
    # but an empty book must say why rather than look like a flat signal.
    tail = ds.dates[-(EARNINGS_TAIL + 1):]
    if not np.any(w != 0.0) and asof in tail:
        raise SystemExit(
            f"{asof.date()} falls in the last {EARNINGS_TAIL + 1} sessions of the "
            "feature panel, where the forward earnings gate cannot be evaluated and "
            "every name is suppressed. Re-run with a forward-looking earnings file, "
            "or request an earlier date."
        )

    px = ds.panel.close[idx]
    live = np.isfinite(w) & (w != 0.0)
    out = pd.DataFrame({
        "symbol": ds.symbols[live],
        "weight": w[live],
        "notional": w[live] * args.equity,
        "reference_price": px[live],
    })
    out["shares"] = (out["notional"] / out["reference_price"]).round().astype("Int64")
    out = out.reindex(out["weight"].abs().sort_values(ascending=False).index)
    out.insert(0, "date", asof.date())
    out.insert(1, "strategy", args.strategy)
    out.insert(2, "venue", "closing_auction")

    meta = {
        "date": str(asof.date()),
        "strategy": args.strategy,
        "equity": args.equity,
        "n_positions": int(len(out)),
        "gross": float(np.abs(w).sum()),
        "net": float(w.sum()),
        "long_notional": float(out.loc[out["weight"] > 0, "notional"].sum()),
        "short_notional": float(-out.loc[out["weight"] < 0, "notional"].sum()),
        "max_abs_weight": float(np.abs(w).max()),
        "reference_price_note": (
            "reference_price is the session close; the decision was made on the "
            "15:45 print, so fills will differ"
        ),
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(args.out, index=False)
        Path(args.out).with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
        print(f"wrote {args.out} ({len(out)} positions)")
    else:
        print(json.dumps(meta, indent=2))
        print(out.to_string(index=False))
    return 0


def cmd_submit(args) -> int:
    """Diff a target book (CSV from `targets`) against the live paper account
    and submit market-on-close orders for the delta.

    Always prints the order preview. Orders are only sent to Alpaca when
    `--confirm` is passed -- without it this is a dry run: it authenticates
    and reads the account (so credential and connectivity problems surface
    early) but places nothing.
    """
    book = pd.read_csv(args.book)
    if book.empty:
        print("target book is empty; nothing to do")
        return 0
    strategy = str(book["strategy"].iloc[0])
    as_of = pd.Timestamp(book["date"].iloc[0])

    broker = AlpacaSwingBroker(strategy_id=f"swing-{strategy}")
    nav = broker.nav()
    current = broker.positions()

    order_set = build_orders(book, current, nav, strategy=strategy, as_of=as_of)

    print(f"as_of={order_set.as_of.date()} strategy={order_set.strategy} nav=${nav:,.2f}")
    print(f"orders={len(order_set.orders)} suppressed={len(order_set.suppressed)} "
          f"missing_price={len(order_set.missing_price)} gross={order_set.gross:.3f} net={order_set.net:.3f}")
    for o in order_set.orders:
        print(f"  {o.side:4s} {abs(o.quantity):>8d} {o.symbol:<8s} notional=${o.notional:,.2f} "
              f"target_weight={o.target_weight:+.4f}")

    if not order_set.orders:
        print("no orders to submit")
        return 0

    if not args.confirm:
        print("\nDRY RUN -- no orders submitted. Re-run with --confirm to send these to Alpaca paper.")
        return 0

    order_ids = broker.submit_moc(order_set.orders)
    print(f"\nsubmitted {len(order_ids)}/{len(order_set.orders)} orders")
    return 0 if len(order_ids) == len(order_set.orders) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mentisrex.swing.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("targets", help="emit the target book for one session")
    t.add_argument("--strategy", required=True, choices=("nightfall", "lastlight"))
    t.add_argument("--equity", type=float, required=True)
    t.add_argument("--date", default=None, help="ET session date; default is the last available")
    t.add_argument("--features", default=str(DATA / "features.parquet"))
    t.add_argument("--start", default="2020-01-01")
    t.add_argument("--end", default="2026-12-31")
    t.add_argument("--tier", default="core")
    t.add_argument("--target-vol", type=float, default=0.10)
    t.add_argument("--gross-cap", type=float, default=3.0)
    t.add_argument("--max-weight", type=float, default=0.015)
    t.add_argument("--max-participation", type=float, default=0.0)
    t.add_argument("--warmup", type=int, default=120)
    t.add_argument("--out", default=None, help="CSV path; prints to stdout if omitted")
    t.set_defaults(func=cmd_targets)

    s = sub.add_parser("submit", help="diff a target book against the live paper account and submit MOC orders")
    s.add_argument("--book", required=True, help="CSV produced by `targets --out ...`")
    s.add_argument("--confirm", action="store_true", help="actually submit; omit for a dry run")
    s.set_defaults(func=cmd_submit)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
