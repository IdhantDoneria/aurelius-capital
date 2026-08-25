"""Render the campaign's results tables into the two strategy documents.

The documents carry prose plus `<!-- TABLE:name -->` markers; this fills the
markers from `campaign.json`. Numbers in the documents are therefore always
the numbers the campaign actually produced, and a stale figure is impossible
rather than merely unlikely.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")
NAMES = {"nightfall": "Nightfall", "lastlight": "Lastlight", "dayburn": "Dayburn"}


def pct(x, d=2):
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def num(x, d=2):
    return "n/a" if x is None else f"{x:.{d}f}"


def md_table(headers: list[str], rows: list[list[str]], align: str | None = None) -> str:
    sep = align or ("---|" * len(headers)).rstrip("|")
    out = ["| " + " | ".join(headers) + " |", "|" + sep + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def t_headline(c) -> str:
    rows = []
    for k, label in NAMES.items():
        h = c.get("headline", {}).get(k)
        if not h:
            continue
        p, d = h["performance"], h.get("detail", {})
        # Sharpe x vol is exactly the annualised mean excess return, which is
        # the number a CAGR hides when most of the book is in Treasury bills.
        exc = (p["sharpe"] * p["vol"]) if (p["sharpe"] is not None and p["vol"]) else None
        rows.append([
            label, pct(p["cagr"]), pct(exc), pct(p["vol"]), num(p["sharpe"]), num(p["sortino"]),
            pct(p["max_drawdown"]), num(p["beta"], 3), pct(p["alpha_annual"]),
            num(p["alpha_t"], 1), num(p["turnover_annual"], 0),
            num(h["deflated_sharpe"], 3), int(h.get("n_trials_assumed", 0)),
        ])
    return md_table(
        ["Strategy", "CAGR", "Excess of cash", "Vol", "Sharpe", "Sortino",
         "Max DD", "Beta", "Alpha (ann.)", "Alpha t", "Turnover", "DSR", "Trials"],
        rows, ":--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:",
    )


def t_economics(c) -> str:
    rows = []
    for k, label in NAMES.items():
        h = c.get("headline", {}).get(k)
        if not h:
            continue
        d = h.get("detail", {})
        if "alpha_bps_per_turnover" in d:
            a = d["alpha_bps_per_turnover"] * 2
            cst = d["cost_bps_per_turnover"] * 2
            rows.append([label, pct(d.get("gross_cagr")), num(a, 2), num(cst, 2),
                         num(a / cst, 2) if cst else "n/a",
                         num(c["cost_sweep"][k]["breakeven_multiple"], 2)
                         if k in c.get("cost_sweep", {}) else "n/a"])
        else:
            rows.append([label, "n/a", "n/a", "n/a", "n/a", "n/a"])
    return md_table(
        ["Strategy", "Gross CAGR", "Edge per round trip (bps)",
         "Cost per round trip (bps)", "Edge / cost", "Breakeven cost multiple"],
        rows, ":--|--:|--:|--:|--:|--:",
    )


def t_aum(c, key) -> str:
    s = c.get("aum_sweep", {}).get(key, {})
    if not s:
        return "_Not run._"
    if key == "dayburn":
        rows = []
        for aum, r in sorted(s.items(), key=lambda kv: float(kv[0])):
            rows.append([f"${aum}M", pct(r["cagr"]), num(r["sharpe"]),
                         pct(r["max_drawdown"]), num(r.get("beta"), 3),
                         f"{int(r.get('n_trades', 0)):,}",
                         pct(r.get("hit_rate_trade"), 1),
                         pct(r.get("avg_win"), 2), pct(r.get("avg_loss"), 2)])
        return md_table(["Equity", "CAGR", "Sharpe", "Max DD", "Beta", "Trades",
                         "Hit rate", "Avg win", "Avg loss"], rows,
                        ":--|--:|--:|--:|--:|--:|--:|--:|--:")
    rows = []
    for aum, r in sorted(s.items(), key=lambda kv: float(kv[0])):
        rows.append([f"${aum}M", pct(r.get("gross_cagr")), pct(r["cagr"]),
                     pct(_excess(r)), num(r["sharpe"]), pct(r["max_drawdown"]),
                     num(r.get("cost_bps_per_day"), 2), num(r.get("turnover_annual"), 0)])
    return md_table(["Equity", "Gross CAGR", "Net CAGR", "Excess of cash", "Sharpe",
                     "Max DD", "Cost (bps/day)", "Turnover"], rows,
                    ":--|--:|--:|--:|--:|--:|--:|--:")


def t_participation(c, key) -> str:
    s = c.get("participation_sweep", {}).get(key, {})
    rows = []
    for part, r in sorted(s.items(), key=lambda kv: -float(kv[0])):
        lbl = "uncapped" if float(part) == 0 else f"{float(part) * 100:.3f}% of ADV"
        rows.append([lbl, pct(r.get("gross_cagr")), pct(r["cagr"]), pct(_excess(r)),
                     num(r["sharpe"]), pct(r["max_drawdown"]),
                     num(r.get("avg_gross"), 2), num(r.get("turnover_annual"), 0)])
    return md_table(["Per-name cap", "Gross CAGR", "Net CAGR", "Excess of cash",
                     "Sharpe", "Max DD", "Avg gross", "Turnover"], rows,
                    ":--|--:|--:|--:|--:|--:|--:|--:")


def t_cost(c, key) -> str:
    s = c.get("cost_sweep", {}).get(key, {}).get("table", {})
    rows = []
    for _, r in sorted(s.items(), key=lambda kv: r_key(kv[1])):
        rows.append([f"{r['cost_multiple']:.2f}x", pct(r["cagr"]), num(r["sharpe"]),
                     pct(r["max_dd"])])
    return md_table(["Cost multiple", "CAGR", "Sharpe", "Max DD"], rows, ":--|--:|--:|--:")


def r_key(r):
    return r["cost_multiple"]


def t_annual(c, key) -> str:
    a = c.get("headline", {}).get(key, {}).get("annual", {})
    rows = []
    for yr, r in sorted(a.items()):
        rows.append([yr[:4], pct(r["cagr"]), pct(r["vol"]), num(r["sharpe"]),
                     pct(r["max_drawdown"]), num(r["hit_rate"] * 100, 1) + "%"])
    return md_table(["Year", "Return", "Vol", "Sharpe", "Max DD",
                     "Days beating cash"], rows, ":--|--:|--:|--:|--:|--:")


def t_regime(c, key) -> str:
    a = c.get("headline", {}).get(key, {}).get("vix_regime", {})
    rows = []
    for lbl in ("low_vol", "mid_vol", "high_vol"):
        r = a.get(lbl)
        if not r:
            continue
        rows.append([lbl.replace("_", " "), int(r["n_days"]), pct(r["mean_ann"]),
                     pct(r["vol_ann"]), num(r["sharpe"]), num(r["nw_t"], 2)])
    return md_table(["VIX regime", "Days", "Return (ann.)", "Vol", "Sharpe", "NW t"],
                    rows, ":--|--:|--:|--:|--:|--:")


def t_bootstrap(c) -> str:
    rows = []
    for k, label in NAMES.items():
        h = c.get("headline", {}).get(k)
        if not h:
            continue
        b = h["bootstrap"]
        rows.append([label, num(h["performance"]["sharpe"]), num(b["sharpe_p05"]),
                     num(b["sharpe_median"]), num(b["sharpe_p95"]),
                     pct(b["prob_sharpe_below_zero"], 1), pct(b["maxdd_median"]),
                     pct(b["maxdd_p05"])])
    return md_table(["Strategy", "Realised Sharpe", "5th pct", "Median", "95th pct",
                     "P(Sharpe<0)", "Median max DD", "5th pct max DD"], rows,
                    ":--|--:|--:|--:|--:|--:|--:|--:")


def t_decay(c, key) -> str:
    d = c.get("signal_decay", {}).get(key, {})
    rows = []
    for seg, label in (("fwd_overnight", "next overnight (close to open)"),
                       ("fwd_intraday", "next session (open to close)"),
                       ("fwd_close_to_close", "next close to close")):
        t = d.get(seg, {})
        for _, r in t.items():
            rows.append([label, num(r["mean_ic"] * 100, 2) + "%",
                         num(r["t_stat"], 1), int(r["n_obs"])])
    return md_table(["Forward segment", "Mean rank IC", "t-stat", "Days"], rows,
                    ":--|--:|--:|--:")


def t_decay_horizon(c, key) -> str:
    t = c.get("signal_decay", {}).get(key, {}).get("multi_horizon_close_to_close", {})
    rows = []
    for _, r in sorted(t.items(), key=lambda kv: kv[1]["horizon_days"]):
        rows.append([int(r["horizon_days"]), num(r["mean_ic"] * 100, 2) + "%",
                     num(r["ic_ir"], 3), num(r["t_stat"], 1)])
    return md_table(["Horizon (days)", "Mean rank IC", "IC IR", "t-stat"], rows,
                    ":--|--:|--:|--:")


def t_dayburn_trades(c) -> str:
    d = c.get("headline", {}).get("dayburn", {}).get("detail", {})
    if not d:
        return "_Dayburn did not run._"
    rows = [
        ["Trades", f"{d.get('n_trades', 0):,}"],
        ["Trades per session", num(d.get("trades_per_day"), 1)],
        ["Hit rate (per trade)", pct(d.get("hit_rate_trade"), 1)],
        ["Average winner", pct(d.get("avg_win"), 2)],
        ["Average loser", pct(d.get("avg_loss"), 2)],
        ["Payoff ratio", num(d.get("payoff_ratio"), 2)],
        ["Cost (bps/day)", num(d.get("cost_bps_per_day"), 2)],
    ]
    for reason, share in (d.get("exit_reasons") or {}).items():
        rows.append([f"Exits: {reason}", pct(share, 1)])
    return md_table(["Metric", "Value"], rows, ":--|--:")


def t_universe(c) -> str:
    u = c["universe"]
    rows = [
        ["Sessions", f"{u['n_dates']:,}"],
        ["Symbols with data", f"{u['n_symbols']:,}"],
        ["Median tradable per session", f"{u['median_tradable_per_day']:,}"],
        ["Window", f"{u['start']} to {u['end']}"],
        ["Benchmark (SPY) CAGR", pct(u["benchmark_cagr"])],
        ["Benchmark volatility", pct(u["benchmark_vol"])],
        ["Intraday features available", str(u.get("intraday_features_available"))],
        ["Lastlight displacement column", str(u.get("lastlight_push_column"))],
    ]
    return md_table(["Property", "Value"], rows, ":--|--:")


def t_correlation(c) -> str:
    m = c.get("correlation")
    if not m:
        return "_Not enough strategies ran to compute a correlation matrix._"
    keys = list(m.keys())
    rows = [[k] + [num(m[k][j], 3) for j in keys] for k in keys]
    return md_table(["", *keys], rows, ":--|" + "--:|" * len(keys))


def t_combination(c) -> str:
    k = c.get("equal_risk_combination")
    if not k:
        return "_No combination computed._"
    rows = [
        ["Weights", ", ".join(f"{a} {b:.0%}" for a, b in k["weights"].items())],
        ["CAGR", pct(k["cagr"])],
        ["Volatility", pct(k["vol"])],
        ["Sharpe", num(k["sharpe"])],
        ["Max drawdown", pct(k["max_drawdown"])],
        ["Beta to SPY", num(k["beta"], 3)],
        ["Newey-West t (excess)", num(k.get("newey_west_t_excess"), 2)],
    ]
    return md_table(["Metric", "Value"], rows, ":--|--:")


def t_holdout(c) -> str:
    d = c.get("design_holdout", {})
    if not d:
        return "_No design/holdout split available._"
    rows = []
    for k, label in NAMES.items():
        for w in ("design", "holdout"):
            r = d.get(k, {}).get(w)
            if not r:
                continue
            rows.append([label, w, r["n_days"], pct(r["cagr"]), num(r["sharpe"]),
                         pct(r["max_drawdown"]), num(r.get("newey_west_t_excess"), 2)])
    return md_table(["Strategy", "Window", "Days", "CAGR", "Sharpe", "Max DD", "NW t"],
                    rows, ":--|:--|--:|--:|--:|--:|--:")


def t_dayburn_grid(c) -> str:
    g = c.get("dayburn_parameter_sweep")
    if not g:
        return "_Dayburn parameter sweep not run._"
    rows = []
    ordered = sorted(g["grid"].values(), key=lambda r: -r.get("sharpe", -1e9))[:20]
    for r in ordered:
        rows.append(["fade" if r.get("direction", 1) < 0 else "trend",
                     num(r["cone_k"], 2), num(r["atr_stop_mult"], 1),
                     "yes" if r.get("vwap_trail") else "no",
                     num(r.get("max_spread_bps", 8.0), 1),
                     num(r.get("risk_per_trade", 0.001) * 1e4, 1),
                     int(r["n_in_play"]),
                     f"{int(r['n_trades']):,}", pct(r["hit_rate"], 1), pct(r["cagr"]),
                     num(r["sharpe"]), pct(r["max_dd"])])
    chosen = g.get("chosen")
    tbl = md_table(["Side", "Cone k", "Stop mult", "VWAP trail", "Max spread bps",
                    "Risk/trade bps", "Names", "Trades", "Hit rate", "CAGR",
                    "Sharpe", "Max DD"], rows,
                   ":--|--:|--:|:--|--:|--:|--:|--:|--:|--:|--:|--:")
    return tbl + f"\n\nChosen on the design window ({g['design_window'][0]} to "\
                 f"{g['design_window'][1]}): `{chosen}`."


def t_dayburn_exec(c) -> str:
    d = c.get("dayburn_execution_style")
    if not d:
        return "_Not run._"
    rows = []
    for _, r in sorted(d.items(), key=lambda kv: -kv[1]["spread_capture"]):
        lbl = {1.0: "full spread (fully aggressive)", 0.5: "half spread (marketable)",
               0.25: "quarter spread (mixed)", 0.0: "no spread (fully passive)"}.get(
                   r["spread_capture"], str(r["spread_capture"]))
        rows.append([lbl, pct(r["cagr"]), num(r["sharpe"]), pct(r["max_dd"])])
    return md_table(["Execution style", "CAGR", "Sharpe", "Max DD"], rows, ":--|--:|--:|--:")


def t_continuation(c) -> str:
    d = c.get("intraday_continuation")
    if not d:
        return "_Not computed._"
    rows = []
    for k, r in d.items():
        if r is None:
            continue
        rows.append([k.replace("_", " "), f"{int(r['n']):,}",
                     num(r["mean_signed_move"], 4), num(r["t_stat"], 1),
                     num(r["rank_ic"], 4), pct(r["hit_rate"], 1)])
    return md_table(["Slice", "Observations", "Mean signed follow-through",
                     "t-stat", "Rank IC", "Hit rate"], rows, ":--|--:|--:|--:|--:|--:")


def _zero_crossing(xs, ys):
    """Interpolate where `ys` crosses zero as `xs` increases."""
    pts = sorted(zip(xs, ys))
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if y0 > 0 >= y1:
            return x0 + (x1 - x0) * y0 / (y0 - y1)
    return pts[-1][0] if pts[-1][1] > 0 else 0.0


def _excess(r):
    """Annualised mean excess return: Sharpe x volatility."""
    sh, v = r.get("sharpe"), r.get("vol")
    return None if (sh is None or not v) else sh * v


def t_capacity(c) -> str:
    """Equity at which each sleeve stops beating cash.

    Measured on **excess** return, not CAGR. A capacity table built on CAGR
    would credit a capacity-constrained book for the Treasury bills it is
    forced to hold and report a break-even size for a strategy that never
    beats cash at any size.
    """
    rows = []
    for k, label in NAMES.items():
        s = c.get("aum_sweep", {}).get(k, {})
        if not s:
            continue
        xs = [float(a) for a in s]
        ys = [(_excess(s[a]) if _excess(s[a]) is not None else -1.0) for a in s]
        smallest = min(xs)
        if all(y <= 0 for y in ys):
            cap = "none (below cash at every size tested)"
        else:
            z = _zero_crossing(xs, ys)
            cap = f"~${z:.0f}m" if z > smallest else f"below ${smallest:.0f}m"
        best = max(zip(ys, xs))
        rows.append([label, cap, f"${best[1]:.0f}m", pct(best[0])])
    return md_table(["Strategy", "Size at which it stops beating cash",
                     "Best size tested", "Excess of cash at that size"], rows,
                    ":--|--:|--:|--:")


def t_walkforward(c) -> str:
    w = c.get("walk_forward")
    if not w:
        return "_Walk-forward not run._"
    rows = []
    for k, label in NAMES.items():
        r = w.get(k)
        if not r:
            continue
        exc = (r["sharpe"] * r["vol"]) if (r["sharpe"] is not None and r["vol"]) else None
        rows.append([label, len(r.get("folds", {})), r["n_days"], pct(r["cagr"]),
                     pct(exc), num(r["sharpe"]), pct(r["max_drawdown"]),
                     num(r.get("newey_west_t_excess"), 2)])
    return md_table(["Strategy", "Folds", "OOS days", "CAGR", "Excess of cash",
                     "Sharpe", "Max DD", "NW t (excess)"], rows,
                    ":--|--:|--:|--:|--:|--:|--:|--:")


def t_walkforward_folds(c) -> str:
    w = c.get("walk_forward") or {}
    rows = []
    for k, label in NAMES.items():
        f = (w.get(k) or {}).get("folds") or {}
        for _, r in sorted(f.items(), key=lambda kv: str(kv[1].get("test_start"))):
            rows.append([label, str(r["train_start"]), str(r["train_end"]),
                         str(r["test_start"]), str(r["test_end"]),
                         num(r["train_obj"], 2), num(r["test_obj"], 2),
                         str(r["chosen"])])
    if not rows:
        return "_No folds._"
    return md_table(["Strategy", "Train from", "Train to", "Test from", "Test to",
                     "Train Sharpe", "Test Sharpe", "Chosen"], rows,
                    ":--|:--|:--|:--|:--|--:|--:|:--")


BUILDERS = {
    "walkforward": t_walkforward,
    "walkforward_folds": t_walkforward_folds,
    "capacity": t_capacity,
    "dayburn_exec": t_dayburn_exec,
    "continuation": t_continuation,
    "holdout": t_holdout,
    "dayburn_grid": t_dayburn_grid,
    "correlation": t_correlation,
    "combination": t_combination,
    "headline": t_headline,
    "economics": t_economics,
    "bootstrap": t_bootstrap,
    "universe": t_universe,
    "dayburn_trades": t_dayburn_trades,
}
for _k in NAMES:
    BUILDERS[f"aum_{_k}"] = (lambda k: lambda c: t_aum(c, k))(_k)
    BUILDERS[f"participation_{_k}"] = (lambda k: lambda c: t_participation(c, k))(_k)
    BUILDERS[f"cost_{_k}"] = (lambda k: lambda c: t_cost(c, k))(_k)
    BUILDERS[f"annual_{_k}"] = (lambda k: lambda c: t_annual(c, k))(_k)
    BUILDERS[f"regime_{_k}"] = (lambda k: lambda c: t_regime(c, k))(_k)
for _k in ("nightfall_divergence", "lastlight_push_fade"):
    BUILDERS[f"decay_{_k}"] = (lambda k: lambda c: t_decay(c, k))(_k)
    BUILDERS[f"decayh_{_k}"] = (lambda k: lambda c: t_decay_horizon(c, k))(_k)


def render(text: str, campaign: dict) -> str:
    import re

    def sub(m):
        name = m.group(1)
        fn = BUILDERS.get(name)
        if fn is None:
            return f"_(no table builder named `{name}`)_"
        try:
            return fn(campaign)
        except Exception as exc:  # noqa: BLE001 - surfaced in the document
            return f"_(table `{name}` failed: {exc})_"

    return re.sub(r"<!--\s*TABLE:([a-z0-9_]+)\s*-->", sub, text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default=str(DATA / "results" / "campaign.json"))
    ap.add_argument("--templates", nargs="+", required=True)
    args = ap.parse_args()
    campaign = json.loads(Path(args.campaign).read_text())
    for t in args.templates:
        src = Path(t)
        dst = src.with_name(src.name.replace(".template", ""))
        dst.write_text(render(src.read_text(), campaign))
        print(f"{src} -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
