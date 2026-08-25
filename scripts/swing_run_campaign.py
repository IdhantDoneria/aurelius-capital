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
def build_nightfall(ds, aum, *, overlay=None, cfg=None, hold=1):
    return Nightfall(
        ds.cube,
        overlay or OverlayConfig(target_vol=0.10, gross_cap=3.0, max_weight=0.015,
                                 n_stat_factors=3, max_participation=0.0),
        StagingConfig(hold_days=hold, stage=hold > 1),
        beta=ds.beta, factor_loadings=ds.factor_loadings, tradable=ds.panel.tradable,
        adv_dollar=ds.cube["addv60"], equity=aum,
        config=cfg or NightfallConfig(mode="overnight"),
    )


def lastlight_push_column(ds) -> str:
    """Use the intraday displacement when the panel has it, the daily-VWAP
    fallback otherwise -- and say which, rather than silently trading a
    column of NaNs."""
    return "close_push" if np.isfinite(ds.cube["close_push"]).any() else "close_push_daily"


def build_lastlight(ds, aum, *, overlay=None, cfg=None, push=None):
    push = push or lastlight_push_column(ds)
    s = Lastlight(
        ds.cube,
        overlay or OverlayConfig(target_vol=0.10, gross_cap=3.0, max_weight=0.015,
                                 n_stat_factors=3, max_participation=0.0),
        StagingConfig(hold_days=1, stage=False),
        beta=ds.beta, factor_loadings=ds.factor_loadings, tradable=ds.panel.tradable,
        adv_dollar=ds.cube["addv60"], equity=aum,
        config=cfg or LastlightConfig(push_source=push), vix=ds.vix,
    )
    s.overnight_only = True
    return s


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
        "newey_west_t": newey_west_t(res["ret"]),
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
        "newey_west_t": newey_west_t(ret),
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
    ap.add_argument("--n-trials", type=int, default=40,
                    help="configurations examined, for Sharpe deflation")
    ap.add_argument("--skip-dayburn", action="store_true")
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
    for name, builder in (("nightfall", build_nightfall), ("lastlight", build_lastlight)):
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
            deep_dive(name, res["ret"], ds, args.n_trials, res=res,
                      extra={"detail": xs_record(ds, res, perf, args.aum)})
        )

    # ---------------- intraday sleeve ------------------------------------
    if not args.skip_dayburn:
        print("dayburn: loading bars ...", flush=True)
        f, b, c = dayburn_inputs(features=args.features, start=args.start, end=args.end,
                                 tier=args.tier)
        print(f"  {len(f):,} sessions, {len(b):,} bars, {len(c):,} cone rows", flush=True)
        rows = {}
        for aum in (10e6, 25e6, 50e6, 100e6):
            trades, daily, perf = run_dayburn(
                f, b, c, initial_equity=aum, benchmark=ds.benchmark, rf=ds.rf
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
            f, b, c, initial_equity=args.aum, benchmark=ds.benchmark, rf=ds.rf
        )
        trades.to_parquet(out / "dayburn_trades.parquet")
        daily.to_parquet(out / "dayburn_daily.parquet")
        ret = daily["ret"].reindex(ds.dates).fillna(0.0)
        report.setdefault("headline", {})["dayburn"] = jsonable(
            deep_dive("dayburn", ret, ds, args.n_trials, res=daily, extra={"detail": {
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
            "newey_west_t": newey_west_t(combo),
        })

    (Path(args.out) / "campaign.json").write_text(json.dumps(jsonable(report), indent=2, default=str))
    print(f"\nwrote {Path(args.out) / 'campaign.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
