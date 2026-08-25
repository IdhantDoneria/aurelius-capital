"""Run the full three-strategy campaign and write every number the two
strategy documents quote.

One entry point, so that the comparison is genuinely like-for-like: the same
universe, the same window, the same risk overlay and the same cost model for
all three books. Anything that differs between them is a difference in
signal or in holding period, not in how generously each was simulated.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mentisrex.swing.construction import OverlayConfig  # noqa: E402
from mentisrex.swing.costs import CostConfig  # noqa: E402
from mentisrex.swing.data import load  # noqa: E402
from mentisrex.swing.metrics import (  # noqa: E402
    deflated_sharpe, evaluate, newey_west_t, stationary_bootstrap,
)
from mentisrex.swing.run import (  # noqa: E402
    dayburn_inputs, run_cross_sectional, run_dayburn,
)
from mentisrex.swing.strategies import (  # noqa: E402
    DayburnConfig, Lastlight, LastlightConfig, Nightfall, NightfallConfig,
)
from mentisrex.swing.strategies.dayburn import prepare_bars, prepare_cone  # noqa: E402
from mentisrex.swing.strategies.base import StagingConfig  # noqa: E402
from mentisrex.swing.validation import (  # noqa: E402
    breakeven_cost_multiple, regime_split, signal_decay, subperiods,
)

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")
OUT = DATA / "results"


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, pd.DataFrame):
        return jsonable(o.to_dict("index"))
    if isinstance(o, pd.Series):
        return jsonable(o.to_dict())
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (pd.Timestamp,)):
        return str(o.date())
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


# ---------------------------------------------------------------- builders
def build_nightfall(ds, aum, *, overlay=None, cfg=None, hold=1, warmup=260):
    return Nightfall(
        ds.cube,
        overlay or OverlayConfig(target_vol=0.10, gross_cap=3.0, max_weight=0.015,
                                 n_stat_factors=3, max_participation=0.0),
        StagingConfig(hold_days=hold, stage=hold > 1),
        beta=ds.beta, factor_loadings=ds.factor_loadings, tradable=ds.panel.tradable,
        adv_dollar=ds.cube["addv60"], equity=aum,
        config=cfg or NightfallConfig(mode="overnight"),
        warmup_days=warmup,
    )


def lastlight_push_column(ds) -> str:
    """Use the intraday displacement when the panel has it, the daily-VWAP
    fallback otherwise -- and say which, rather than silently trading a
    column of NaNs."""
    return "close_push" if np.isfinite(ds.cube["close_push"]).any() else "close_push_daily"


def build_lastlight(ds, aum, *, overlay=None, cfg=None, push=None, warmup=260):
    push = push or lastlight_push_column(ds)
    s = Lastlight(
        ds.cube,
        overlay or OverlayConfig(target_vol=0.10, gross_cap=3.0, max_weight=0.015,
                                 n_stat_factors=3, max_participation=0.0),
        StagingConfig(hold_days=1, stage=False),
        beta=ds.beta, factor_loadings=ds.factor_loadings, tradable=ds.panel.tradable,
        adv_dollar=ds.cube["addv60"], equity=aum,
        config=cfg or LastlightConfig(push_source=push), vix=ds.vix,
        warmup_days=warmup,
    )
    s.overnight_only = True
    return s


def excess(ret, ds):
    """Return in excess of the risk-free rate.

    Every significance statement in this campaign is made on this series,
    not on the raw one. Since the simulator credits interest on idle cash,
    a raw-return t-statistic on a book that is mostly cash measures the
    Treasury bill, not the strategy.
    """
    rf_d = ds.rf.reindex(ret.index).ffill().fillna(0.0) / 252.0
    return ret - rf_d


def xs_record(ds, res, perf, aum):
    e0 = res["equity"].shift(1).fillna(aum)
    g = res["pnl_gross"] / e0
    gross_cagr = float((1.0 + g).prod() ** (252 / len(res)) - 1.0)
    turn = max(perf.turnover_annual, 1e-9)
    return {
        **perf.to_dict(),
        "gross_cagr": gross_cagr,
        "alpha_bps_per_turnover": gross_cagr / turn * 1e4,
        "cost_bps_per_turnover": float(res["cost_bps"].mean() / (turn / 252)),
        "cost_bps_per_day": float(res["cost_bps"].mean()),
        "financing_bps_per_day": float((res["financing"] / e0).mean() * 1e4),
        "newey_west_t_excess": newey_west_t(excess(res["ret"], ds)),
    }


def deep_dive(name, ret, ds, n_trials, extra=None, res=None):
    perf = evaluate(
        ret, benchmark=ds.benchmark, rf=ds.rf,
        gross=None if res is None else res.get("gross"),
        net=None if res is None else res.get("net"),
        turnover=None if res is None else res.get("turnover"),
    )
    boot = stationary_bootstrap(ret, n_paths=4000, mean_block=10)
    dsr, sr0 = deflated_sharpe(perf.sharpe, ret, n_trials=n_trials)
    vix = pd.Series(ds.vix, index=ds.dates)
    return {
        "name": name,
        "performance": perf.to_dict(),
        "newey_west_t_excess": newey_west_t(excess(ret, ds)),
        "deflated_sharpe": dsr,
        "deflation_benchmark_sharpe": sr0,
        "n_trials_assumed": n_trials,
        "bootstrap": {
            "sharpe_p05": float(boot["sharpe"].quantile(0.05)),
            "sharpe_median": float(boot["sharpe"].median()),
            "sharpe_p95": float(boot["sharpe"].quantile(0.95)),
            "prob_sharpe_below_zero": float((boot["sharpe"] < 0).mean()),
            "maxdd_median": float(boot["max_drawdown"].median()),
            "maxdd_p05": float(boot["max_drawdown"].quantile(0.05)),
        },
        "annual": jsonable(subperiods(ret, benchmark=ds.benchmark, rf=ds.rf)),
        "vix_regime": jsonable(
            regime_split(ret, vix, n_buckets=3, labels=("low_vol", "mid_vol", "high_vol"))
        ),
        **(extra or {}),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=str(DATA / "features.parquet"))
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-08-24")
    ap.add_argument("--tier", default="core")
    ap.add_argument("--aum", type=float, default=50e6)
    ap.add_argument("--exploration-allowance", type=int, default=25,
                    help=("configurations examined outside the recorded grid, added to "
                          "each sleeve's grid size for Sharpe deflation. Counting only "
                          "the grid understates the search; this is a deliberate, "
                          "stated over-estimate rather than a flattering one."))
    ap.add_argument("--skip-dayburn", action="store_true")
    ap.add_argument("--only", default="all", choices=("all", "xs", "dayburn"),
                    help="run a subset of the campaign, for iteration")
    ap.add_argument("--cone", default=str(DATA / "cone.parquet"))
    ap.add_argument("--warmup", type=int, default=120,
                    help=("sessions of the feature panel skipped before trading. The "
                          "panel itself already discards the first 60 sessions of each "
                          "name, and the longest window any live signal depends on is "
                          "63 sessions, so 120 is comfortably sufficient. A year-long "
                          "warm-up on top of the panel's own would silently discard the "
                          "first year of an already short intraday sample."))
    ap.add_argument("--design-end", default="2023-12-31",
                    help="last date of the design window; everything after is holdout")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"config": vars(args), "generated": time.strftime("%Y-%m-%d %H:%M")}

    print("loading dataset ...", flush=True)
    ds = load(features=args.features, start=args.start, end=args.end, tier=args.tier)
    push_col = lastlight_push_column(ds)
    print(f"  lastlight displacement column: {push_col}", flush=True)
    report["universe"] = {
        "lastlight_push_column": push_col,
        "intraday_features_available": bool(np.isfinite(ds.cube["close_push"]).any()),
        "n_dates": len(ds.dates), "n_symbols": int(len(ds.symbols)),
        "start": str(ds.dates[0].date()), "end": str(ds.dates[-1].date()),
        "median_tradable_per_day": int(np.median(ds.panel.tradable.sum(axis=1))),
        "benchmark_cagr": float((1 + ds.benchmark).prod() ** (252 / len(ds.dates)) - 1),
        "benchmark_vol": float(ds.benchmark.std(ddof=1) * np.sqrt(252)),
    }
    print(f"  {report['universe']}", flush=True)

    # ---------------- signal diagnostics ---------------------------------
    print("signal decay ...", flush=True)
    C, TR = ds.cube, ds.panel.tradable
    rt = np.sqrt(10.0)
    div = np.nan_to_num(C["sid10"] / np.maximum(C["sd_id60"] * rt, 1e-6)) - np.nan_to_num(
        C["son10"] / np.maximum(C["sd_on60"] * rt, 1e-6)
    )
    push = -np.nan_to_num(C["close_push"] if np.isfinite(C["close_push"]).any() else C["close_push_daily"])

    def fwd(mat, h):
        a = np.nan_to_num(mat)
        o = np.zeros_like(a)
        for k in range(1, h + 1):
            o[:-k] += a[k:]
        return o

    decay = {}
    for sname, sig in (("nightfall_divergence", div), ("lastlight_push_fade", push)):
        sig = np.where(TR, sig, np.nan)
        decay[sname] = {
            tname: jsonable(signal_decay(sig, fwd(tgt, 1), horizons=(1,)))
            for tname, tgt in (
                ("fwd_overnight", C["ret_on"]),
                ("fwd_intraday", C["ret_id"]),
                ("fwd_close_to_close", C["ret_cc"]),
            )
        }
        decay[sname]["multi_horizon_close_to_close"] = jsonable(
            signal_decay(sig, np.nan_to_num(C["ret_cc"]), horizons=(1, 2, 3, 5, 10, 21))
        )
    report["signal_decay"] = decay

    # ---------------- cross-sectional sleeves ----------------------------
    # ---------------- design-window parameter choice, all sleeves --------
    # Dayburn has fitted parameters, so the other two are given the same
    # courtesy on the same window. Tuning one book and not the others would
    # make the comparison a statement about tuning rather than about signal.
    design = pd.Timestamp(args.design_end)
    design_mask = ds.dates <= design

    MIN_DEPLOYED_GROSS = 0.25

    def score_on_design(strategy_factory, aum):
        """Design-window Sharpe, subject to actually deploying capital.

        Without the deployment floor the optimiser has a degenerate optimum:
        when a sleeve's net alpha is negative, the highest-Sharpe
        configuration is the one that trades least, because Sharpe is
        measured against cash. That is a true statement about the sleeve and
        a useless one about its parameters, so configurations that leave the
        book essentially flat are excluded and the finding is reported in
        prose instead.
        """
        strat = strategy_factory(aum)
        res, perf = run_cross_sectional(ds, strat, initial_equity=aum)
        r = res["ret"][res.index <= design]
        g = res["gross"][res.index <= design]
        if len(r) < 100 or r.std(ddof=1) <= 0:
            return -np.inf
        if float(g.mean()) < MIN_DEPLOYED_GROSS:
            return -np.inf
        # Excess of the risk-free rate, not the raw return. Now that idle
        # cash earns interest, a total-return objective would reward a
        # configuration for holding cash during the 2023-2026 high-rate
        # period rather than for having a better signal.
        rf_d = ds.rf.reindex(r.index).ffill().fillna(0.0) / 252.0
        ex = r - rf_d
        return float(ex.mean() / r.std(ddof=1) * np.sqrt(252))

    xs_grids = {
        "nightfall": [
            {"max_participation": mp, "lookback": lb, "mode": md}
            for mp in (0.0, 0.0003, 0.0001)
            for lb in ("5", "10", "21")
            for md in ("overnight",)
        ],
        # `min_close_vol_share` is in the grid because the signal diagnostic
        # says it should be: the fade's rank IC against the next overnight
        # return is about -5.7% unconditionally and about -7.9% restricted to
        # sessions where the last half hour carried an unusually high share of
        # the day's volume. A filter is a stronger instrument than the weight
        # the sleeve already applies, and with the participation cap binding it
        # reduces gross without raising per-name impact.
        "lastlight": [
            {"max_participation": mp, "vix_beta": vb, "max_rvol": mr,
             "min_close_vol_share": cs}
            for mp in (0.0003, 0.0001)
            for vb in (0.0, 0.5)
            for mr in (2.0, 3.0)
            for cs in (0.06, 0.15, 0.20)
        ],
    }

    def make(name, params, aum, overlay=None):
        """Build a sleeve from a parameter dict.

        `overlay` overrides the overlay the parameters would imply, which is
        what the participation and AUM sweeps need. It is a real argument and
        not a courtesy: a wrapper that quietly swallowed it would leave those
        sweeps reporting the same book under different labels.
        """
        ov = overlay or OverlayConfig(
            target_vol=0.10, gross_cap=3.0, max_weight=0.015, n_stat_factors=3,
            max_participation=params.get("max_participation", 0.0),
        )
        if name == "nightfall":
            cfg = NightfallConfig(mode=params.get("mode", "overnight"),
                                  lookback=params.get("lookback", "10"))
            return build_nightfall(ds, aum, overlay=ov, cfg=cfg, warmup=args.warmup)
        cfg = LastlightConfig(
            push_source=push_col,
            vix_beta=params.get("vix_beta", 0.5),
            vix_scaling=params.get("vix_beta", 0.5) > 0,
            max_rvol=params.get("max_rvol", 3.0),
            min_close_vol_share=params.get("min_close_vol_share", 0.06),
        )
        return build_lastlight(ds, aum, overlay=ov, cfg=cfg, push=push_col,
                               warmup=args.warmup)

    xs_chosen: dict[str, dict] = {}
    n_trials_by_sleeve: dict[str, int] = {}
    if args.only != "dayburn":
        for name, grid in xs_grids.items():
            rows, best, best_obj = [], None, -np.inf
            for g in grid:
                sc = score_on_design(lambda a, n=name, gg=g: make(n, gg, a), args.aum)
                rows.append({**g, "design_sharpe": sc})
                print(f"  {name} grid {g} -> design sharpe {sc:.2f}", flush=True)
                if sc > best_obj:
                    best_obj, best = sc, g
            xs_chosen[name] = best or {}
            n_trials_by_sleeve[name] = len(grid) + args.exploration_allowance
            if best is None:
                print(f"  {name}: no configuration deployed enough capital to score",
                      flush=True)
            report.setdefault("xs_parameter_sweep", {})[name] = jsonable({
                "design_window": [args.start, str(design.date())],
                "grid": jsonable(pd.DataFrame(rows)),
                "chosen": best,
            })

    xs_pairs = () if args.only == "dayburn" else (
        ("nightfall", build_nightfall), ("lastlight", build_lastlight)
    )
    for name, builder in xs_pairs:
        builder = (
            lambda n: lambda d, a, overlay=None, **kw: make(
                n, xs_chosen.get(n, {}), a, overlay=overlay
            )
        )(name)
        print(f"{name}: aum sweep ...", flush=True)
        rows = {}
        for aum in (5e6, 10e6, 25e6, 50e6, 100e6, 250e6):
            res, perf = run_cross_sectional(ds, builder(ds, aum), initial_equity=aum)
            rows[f"{aum/1e6:.0f}"] = xs_record(ds, res, perf, aum)
        report.setdefault("aum_sweep", {})[name] = jsonable(rows)

        print(f"{name}: participation sweep ...", flush=True)
        rows = {}
        for part in (0.0, 0.001, 0.0003, 0.0001, 0.00003):
            ov = OverlayConfig(target_vol=0.10, gross_cap=3.0, max_weight=0.015,
                               n_stat_factors=3, max_participation=part)
            res, perf = run_cross_sectional(
                ds, builder(ds, args.aum, overlay=ov), initial_equity=args.aum
            )
            rows[f"{part:.5f}"] = xs_record(ds, res, perf, args.aum)
        report.setdefault("participation_sweep", {})[name] = jsonable(rows)

        print(f"{name}: cost sweep ...", flush=True)
        rows = []
        for m in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0):
            cost = CostConfig(
                commission_cps=0.10 * m, auction_fee_cps=0.10 * m,
                sec_fee_bps=0.25 * m, taf_cps=0.0166 * m,
                impact_eta_continuous=0.50 * m, impact_eta_auction=0.40 * m,
                spread_scalar=max(m, 1e-9),
            )
            res, perf = run_cross_sectional(
                ds, builder(ds, args.aum), initial_equity=args.aum, cost=cost
            )
            rows.append({"cost_multiple": m, "cagr": perf.cagr, "sharpe": perf.sharpe,
                         "max_dd": perf.max_drawdown})
        t = pd.DataFrame(rows)
        report.setdefault("cost_sweep", {})[name] = {
            "table": jsonable(t), "breakeven_multiple": breakeven_cost_multiple(t),
        }

        print(f"{name}: headline ...", flush=True)
        res, perf = run_cross_sectional(ds, builder(ds, args.aum), initial_equity=args.aum)
        res.to_parquet(out / f"{name}_daily.parquet")
        report.setdefault("headline", {})[name] = jsonable(
            deep_dive(name, res["ret"], ds,
                      n_trials_by_sleeve.get(name, args.exploration_allowance), res=res,
                      extra={"detail": xs_record(ds, res, perf, args.aum)})
        )

    # ---------------- intraday sleeve ------------------------------------
    if not args.skip_dayburn and args.only != "xs":
        print("dayburn: loading bars ...", flush=True)
        f, b, c = dayburn_inputs(features=args.features, cone=args.cone,
                                 start=args.start, end=args.end, tier=args.tier)
        print(f"  {len(f):,} sessions, {len(b):,} bars, {len(c):,} cone rows", flush=True)
        # Built once and reused by every configuration below: a groupby over
        # this many rows costs far more than the simulation it feeds.
        t_prep = time.time()
        pb_all, pc_all = prepare_bars(b), prepare_cone(c)
        pb_design = {k: v for k, v in pb_all.items() if k[0] <= pd.Timestamp(args.design_end).date()}
        print(f"  prepared {len(pb_all):,} sessions in {time.time() - t_prep:.0f}s", flush=True)

        # ---- does an intraday move continue or revert here? ---------------
        # Measured before any simulation, because it is the premise the whole
        # sleeve rests on and a backtest would confound it with execution.
        dd = f[(f["p_open"] > 0) & (f["p_1000"] > 0) & (f["p_1545"] > 0) & (f["sd_cc60"] > 0)].copy()
        dd["x"] = np.log(dd["p_1000"] / dd["p_open"]) / dd["sd_cc60"]
        dd["y"] = np.log(dd["p_1545"] / dd["p_1000"]) / dd["sd_cc60"]
        dd["signed"] = np.sign(dd["x"]) * dd["y"]

        def cont(g):
            if len(g) < 50:
                return None
            s_ = g["signed"]
            return {
                "n": int(len(g)),
                "mean_signed_move": float(s_.mean()),
                "t_stat": float(s_.mean() / (s_.std(ddof=1) / np.sqrt(len(s_)))),
                "rank_ic": float(g["x"].rank().corr(g["y"].rank())),
                "hit_rate": float((s_ > 0).mean()),
            }

        cont_all = {"all": cont(dd)}
        dd["q"] = pd.qcut(dd["x"].abs(), 5, labels=False, duplicates="drop")
        for q in sorted(dd["q"].dropna().unique()):
            cont_all[f"move_quintile_{int(q) + 1}"] = cont(dd[dd["q"] == q])
        dd["year"] = pd.to_datetime(dd["d"]).dt.year
        for y in sorted(dd["year"].unique()):
            cont_all[f"year_{y}"] = cont(dd[dd["year"] == y])
        report["intraday_continuation"] = jsonable(
            {k: v for k, v in cont_all.items() if v is not None}
        )
        print(f"  intraday continuation (all): {cont_all['all']}", flush=True)

        # ---- parameter choice on the design window only -------------------
        design_date = pd.Timestamp(args.design_end).date()
        fd = f[f["d"] <= design_date]
        bd = b[b["d"] <= design_date]
        # The grid spans the four things that actually change this sleeve's
        # economics: which way it trades a breach, how far the price has to
        # move to count as one, how much room the stop gives it, and how wide
        # a name it is willing to cross. The last is included because this
        # sleeve pays the spread twice per trade, which is the single largest
        # component of its cost.
        # The grid spans the five things that change this sleeve's economics:
        # which way it trades a breach, how far the price must move to count
        # as one, how much room the stop gives it, how wide a name it will
        # cross, and how large each position is.
        #
        # The last is not redundant with leverage. For the cross-sectional
        # books, scaling gross scales P&L and cost together and cannot change
        # the sign of net alpha. Here it can, because impact is concave in
        # order size: halving the position roughly divides its impact by the
        # square root of two while leaving the edge per unit notional
        # untouched. Position size is a cost lever, not just a risk lever.
        grid = [
            {"cone_k": k, "atr_stop_mult": m, "n_in_play": n, "vwap_trail": v,
             "direction": dr, "max_spread_bps": sp, "risk_per_trade": rp,
             "cone_vol_source": "trailing"}
            for dr in (1, -1)
            for k in (1.5, 2.5)
            for m in (1.0, 3.0)
            for v in (True, False)
            for sp in (8.0, 3.0)
            for rp in (0.0010, 0.0003)
            for n in (10,)
        ]
        sweep = []
        best, best_obj = None, -np.inf
        for g in grid:
            cfg = DayburnConfig(n_in_play=g["n_in_play"],
                                cone_vol_source=g["cone_vol_source"],
                                max_spread_bps=g["max_spread_bps"])
            cfg.rules.cone_k = g["cone_k"]
            cfg.rules.atr_stop_mult = g["atr_stop_mult"]
            cfg.rules.vwap_trail = g["vwap_trail"]
            cfg.rules.direction = g["direction"]
            cfg.rules.risk_per_trade = g["risk_per_trade"]
            try:
                tr, dl, pf = run_dayburn(
                    fd, bd, c, config=cfg, initial_equity=args.aum,
                    benchmark=ds.benchmark[ds.benchmark.index <= design],
                    rf=ds.rf, prepared_bars=pb_design, prepared_cone=pc_all,
                )
            except RuntimeError:
                continue
            row = {**g, "cagr": pf.cagr, "sharpe": pf.sharpe, "max_dd": pf.max_drawdown,
                   "n_trades": int(len(tr)),
                   "hit_rate": float((tr["gross_ret"] > 0).mean())}
            sweep.append(row)
            print(f"  grid {g} -> sharpe {pf.sharpe:.2f} trades {len(tr)}", flush=True)
            if np.isfinite(pf.sharpe) and pf.sharpe > best_obj:
                best_obj, best = pf.sharpe, g
        n_trials_by_sleeve["dayburn"] = len(grid) + args.exploration_allowance
        report["dayburn_parameter_sweep"] = {
            "design_window": [args.start, str(design_date)],
            "grid": jsonable(pd.DataFrame(sweep)),
            "chosen": best,
            "note": "chosen on the design window only; the holdout below never informed it",
        }
        b_ = best or {}
        chosen = DayburnConfig(n_in_play=b_.get("n_in_play", 20),
                               cone_vol_source=b_.get("cone_vol_source", "trailing"),
                               max_spread_bps=b_.get("max_spread_bps", 8.0))
        chosen.rules.cone_k = b_.get("cone_k", 1.0)
        chosen.rules.atr_stop_mult = b_.get("atr_stop_mult", 2.0)
        chosen.rules.vwap_trail = b_.get("vwap_trail", True)
        chosen.rules.direction = b_.get("direction", 1)
        chosen.rules.risk_per_trade = b_.get("risk_per_trade", 0.0010)

        rows = {}
        for aum in (10e6, 25e6, 50e6, 100e6):
            trades, daily, perf = run_dayburn(
                f, b, c, config=chosen, initial_equity=aum,
                benchmark=ds.benchmark, rf=ds.rf,
                prepared_bars=pb_all, prepared_cone=pc_all,
            )
            rows[f"{aum/1e6:.0f}"] = jsonable({
                **perf.to_dict(),
                "n_trades": int(len(trades)),
                "hit_rate_trade": float((trades["gross_ret"] > 0).mean()),
                "avg_win": float(trades.loc[trades["gross_ret"] > 0, "gross_ret"].mean()),
                "avg_loss": float(trades.loc[trades["gross_ret"] <= 0, "gross_ret"].mean()),
                "exit_reasons": jsonable(trades["reason"].value_counts(normalize=True)),
            })
        report.setdefault("aum_sweep", {})["dayburn"] = rows

        trades, daily, perf = run_dayburn(
            f, b, c, config=chosen, initial_equity=args.aum,
            benchmark=ds.benchmark, rf=ds.rf,
            prepared_bars=pb_all, prepared_cone=pc_all,
        )
        trades.to_parquet(out / "dayburn_trades.parquet")
        daily.to_parquet(out / "dayburn_daily.parquet")
        ret = daily["ret"].reindex(ds.dates).fillna(0.0)  # already aligned; belt and braces
        # ---- execution-style sensitivity ---------------------------------
        # This sleeve crosses the spread twice per trade, so how much of the
        # spread it actually pays is the assumption its viability turns on.
        # A fade strategy can in principle work passively and earn the spread
        # instead, but fill probability cannot be validated without quote
        # data, so the dependence is reported rather than assumed away.
        rows = []
        for cap in (1.0, 0.5, 0.25, 0.0):
            cost = CostConfig(spread_capture=cap)
            try:
                tr2, dl2, pf2 = run_dayburn(
                    f, b, c, config=chosen, cost=cost, initial_equity=args.aum,
                    benchmark=ds.benchmark, rf=ds.rf,
                    prepared_bars=pb_all, prepared_cone=pc_all,
                )
            except RuntimeError:
                continue
            rows.append({"spread_capture": cap, "cagr": pf2.cagr, "sharpe": pf2.sharpe,
                         "max_dd": pf2.max_drawdown})
        report["dayburn_execution_style"] = jsonable(pd.DataFrame(rows))

        report.setdefault("headline", {})["dayburn"] = jsonable(
            deep_dive("dayburn", ret, ds,
                      n_trials_by_sleeve.get("dayburn", args.exploration_allowance),
                      res=daily, extra={"detail": {
                "n_trades": int(len(trades)),
                "trades_per_day": float(len(trades) / max(len(daily), 1)),
                "hit_rate_trade": float((trades["gross_ret"] > 0).mean()),
                "avg_win": float(trades.loc[trades["gross_ret"] > 0, "gross_ret"].mean()),
                "avg_loss": float(trades.loc[trades["gross_ret"] <= 0, "gross_ret"].mean()),
                "payoff_ratio": float(
                    trades.loc[trades["gross_ret"] > 0, "gross_ret"].mean()
                    / abs(trades.loc[trades["gross_ret"] <= 0, "gross_ret"].mean())
                ),
                "exit_reasons": jsonable(trades["reason"].value_counts(normalize=True)),
                "cost_bps_per_day": float(daily["cost"].sum() / daily["equity"].mean()
                                          / len(daily) * 1e4),
            }})
        )

    # ---------------- design / holdout split -----------------------------
    # Reported for every sleeve, so the holdout numbers are comparable.
    split = {}
    for k in ("nightfall", "lastlight", "dayburn"):
        fp = out / f"{k}_daily.parquet"
        if not fp.exists():
            continue
        r = pd.read_parquet(fp)["ret"]
        for label, sub in (("design", r[r.index <= design]), ("holdout", r[r.index > design])):
            if len(sub) < 40:
                continue
            split.setdefault(k, {})[label] = jsonable({
                **evaluate(sub, benchmark=ds.benchmark.reindex(sub.index),
                           rf=ds.rf.reindex(sub.index)).to_dict(),
                "newey_west_t_excess": newey_west_t(excess(sub, ds)),
            })
    report["design_holdout"] = split
    report["n_trials_by_sleeve"] = n_trials_by_sleeve

    # ---------------- cross-strategy correlation -------------------------
    series = {}
    for k in ("nightfall", "lastlight"):
        f = out / f"{k}_daily.parquet"
        if f.exists():
            series[k] = pd.read_parquet(f)["ret"]
    f = out / "dayburn_daily.parquet"
    if f.exists():
        series["dayburn"] = pd.read_parquet(f)["ret"]
    if len(series) > 1:
        M = pd.DataFrame(series).reindex(ds.dates).fillna(0.0)
        M["benchmark"] = ds.benchmark
        report["correlation"] = jsonable(M.corr())
        eq = M.drop(columns=["benchmark"])
        w = eq.std(ddof=1).rdiv(1.0)
        w = w / w.sum()
        combo = (eq * w).sum(axis=1)
        report["equal_risk_combination"] = jsonable({
            "weights": w.to_dict(),
            **evaluate(combo, benchmark=ds.benchmark, rf=ds.rf).to_dict(),
            "newey_west_t_excess": newey_west_t(excess(combo, ds)),
        })

    (Path(args.out) / "campaign.json").write_text(json.dumps(jsonable(report), indent=2, default=str))
    print(f"\nwrote {Path(args.out) / 'campaign.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
