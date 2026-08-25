"""Compact console summary of a campaign, for reading the verdict off."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def f(x, spec=".2%"):
    return "n/a" if x is None else format(x, spec)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else (
        "/Users/idhantdoneria/mentisrex-capital/data/intraday/results/campaign.json"
    )
    c = json.loads(Path(path).read_text())
    u = c["universe"]
    print(f"UNIVERSE  {u['start']}..{u['end']}  {u['n_dates']} sessions  "
          f"{u['median_tradable_per_day']} tradable/day  push={u.get('lastlight_push_column')}")
    print(f"BENCHMARK CAGR {f(u['benchmark_cagr'])}  vol {f(u['benchmark_vol'])}")

    print("\nHEADLINE")
    for k, h in c.get("headline", {}).items():
        p, d = h["performance"], h.get("detail", {})
        print(f"  {k:10s} CAGR {f(p['cagr']):>8s}  Sharpe {f(p['sharpe'],'.2f'):>6s}  "
              f"vol {f(p['vol']):>7s}  DD {f(p['max_drawdown']):>8s}  "
              f"beta {f(p['beta'],'.3f'):>6s}  aT {f(p['alpha_t'],'.1f'):>6s}  "
              f"DSR {f(h['deflated_sharpe'],'.3f')}  NWt(ex) {f(h.get('newey_west_t_excess'),'.2f')}")
        if "gross_cagr" in d:
            print(f"             gross {f(d['gross_cagr']):>8s}  "
                  f"edge/rt {2*d['alpha_bps_per_turnover']:.2f}bps  "
                  f"cost/rt {2*d['cost_bps_per_turnover']:.2f}bps  "
                  f"ratio {d['alpha_bps_per_turnover']/max(d['cost_bps_per_turnover'],1e-9):.2f}  "
                  f"turn {d.get('turnover_annual', 0):.0f}")
        else:
            print(f"             trades {d.get('n_trades', 0):,}  "
                  f"hit {f(d.get('hit_rate_trade'),'.1%')}  "
                  f"payoff {f(d.get('payoff_ratio'),'.2f')}  "
                  f"cost {f(d.get('cost_bps_per_day'),'.2f')}bps/day")

    print("\nDESIGN vs HOLDOUT")
    for k, v in c.get("design_holdout", {}).items():
        for w, r in v.items():
            print(f"  {k:10s} {w:8s} n={r['n_days']:4d}  CAGR {f(r['cagr']):>8s}  "
                  f"Sharpe {f(r['sharpe'],'.2f'):>6s}  DD {f(r['max_drawdown']):>8s}")

    print("\nBREAKEVEN COST MULTIPLE")
    for k, v in c.get("cost_sweep", {}).items():
        print(f"  {k:10s} {v['breakeven_multiple']:.2f}x")

    print("\nAUM SWEEP (net CAGR)")
    for k, v in c.get("aum_sweep", {}).items():
        cells = "  ".join(f"${a}m:{f(r['cagr'],'+.2%')}" for a, r in
                          sorted(v.items(), key=lambda kv: float(kv[0])))
        print(f"  {k:10s} {cells}")

    if "intraday_continuation" in c:
        a = c["intraday_continuation"]["all"]
        print(f"\nINTRADAY CONTINUATION  mean {a['mean_signed_move']:+.4f}  "
              f"t {a['t_stat']:+.1f}  IC {a['rank_ic']:+.4f}  n {a['n']:,}")
    if "dayburn_parameter_sweep" in c:
        print(f"DAYBURN CHOSEN  {c['dayburn_parameter_sweep']['chosen']}")
    for k, v in (c.get("xs_parameter_sweep") or {}).items():
        print(f"{k.upper()} CHOSEN  {v['chosen']}")

    if "correlation" in c:
        print("\nCORRELATION")
        keys = list(c["correlation"])
        print("            " + "".join(f"{k[:9]:>10s}" for k in keys))
        for k in keys:
            print(f"  {k:10s}" + "".join(f"{c['correlation'][k][j]:>10.3f}" for j in keys))
    if "equal_risk_combination" in c:
        e = c["equal_risk_combination"]
        print(f"\nEQUAL-RISK COMBO  CAGR {f(e['cagr'])}  Sharpe {f(e['sharpe'],'.2f')}  "
              f"DD {f(e['max_drawdown'])}  beta {f(e['beta'],'.3f')}  NWt(ex) {f(e.get('newey_west_t_excess'),'.2f')}")
        print(f"  weights {({k: round(v, 3) for k, v in e['weights'].items()})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
