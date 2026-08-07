"""Visualization data + plotting code (AIDP M9).

The platform has no image stack, so per the spec this emits the *underlying data*
for every chart plus a standalone matplotlib script that renders them. Deterministic
JSON-serializable series; no plotting library imported here.
"""

from __future__ import annotations

import numpy as np

from aurelius.research.validation.significance import sharpe


def _rolling(returns, window, fn):
    r = np.asarray(returns, dtype=float)
    if r.size < window:
        return []
    return [float(fn(r[i - window:i])) for i in range(window, r.size + 1)]


def build_visualizations(pm, *, summaries: dict, window: int = 63) -> dict:
    r = list(pm.daily_returns or [])
    charts = {
        "equity_curve": [(p.timestamp.isoformat(), p.equity) for p in (pm.equity_curve or [])],
        "drawdown_curve": [(t.isoformat(), d) for t, d in (pm.drawdown_series or [])],
        "rolling_sharpe": _rolling(r, window, sharpe),
        "rolling_volatility": _rolling(r, window, lambda x: float(np.std(x, ddof=1) * np.sqrt(252))),
        "turnover": {"annual_turnover": pm.annual_turnover,
                     "holding_days": [t.holding_days for t in (pm.round_trips or [])]},
    }
    boot = summaries.get("bootstrap", {}).get("distribution")
    if boot is not None:
        charts["bootstrap_distribution"] = _histogram(boot)
    mc = summaries.get("monte_carlo", {}).get("distribution")
    if mc is not None:
        charts["monte_carlo_distribution"] = _histogram(mc)
    stab = summaries.get("stability", {})
    if "surface" in stab:
        charts["stability_surface"] = {"xs": stab.get("xs"), "ys": stab.get("ys"),
                                       "surface": stab.get("surface")}
    elif "metrics" in stab:
        charts["stability_curve"] = {"values": stab.get("values"), "metrics": stab.get("metrics")}
    cap = summaries.get("capacity", {})
    if cap.get("estimated_capacity_aum"):
        charts["capacity_curve"] = {"aum": cap["aum"], "capacity_aum": cap["estimated_capacity_aum"],
                                    "adv_utilisation": cap.get("adv_utilisation")}
    return {"charts": charts, "plotting_code": _PLOTTING_CODE}


def _histogram(dist, bins: int = 30) -> dict:
    a = np.asarray(dist, dtype=float)
    counts, edges = np.histogram(a, bins=bins)
    return {"counts": counts.tolist(), "bin_edges": edges.tolist(),
            "p05": float(np.percentile(a, 5)), "p95": float(np.percentile(a, 95))}


_PLOTTING_CODE = '''\
"""Render validation charts from validation_visuals.json. Run: python this_file.py"""
import json, sys
import matplotlib.pyplot as plt

data = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "validation_visuals.json"))
charts = data["charts"]

if charts.get("equity_curve"):
    ts, eq = zip(*charts["equity_curve"])
    plt.figure(); plt.plot(range(len(eq)), eq); plt.title("Equity Curve"); plt.savefig("equity_curve.png")
if charts.get("drawdown_curve"):
    ts, dd = zip(*charts["drawdown_curve"])
    plt.figure(); plt.fill_between(range(len(dd)), dd, 0); plt.title("Drawdown"); plt.savefig("drawdown.png")
if charts.get("rolling_sharpe"):
    plt.figure(); plt.plot(charts["rolling_sharpe"]); plt.title("Rolling Sharpe"); plt.savefig("rolling_sharpe.png")
if charts.get("rolling_volatility"):
    plt.figure(); plt.plot(charts["rolling_volatility"]); plt.title("Rolling Volatility"); plt.savefig("rolling_vol.png")
for key in ("bootstrap_distribution", "monte_carlo_distribution"):
    h = charts.get(key)
    if h:
        plt.figure(); plt.bar(h["bin_edges"][:-1], h["counts"], width=(h["bin_edges"][1]-h["bin_edges"][0]))
        plt.title(key); plt.savefig(key + ".png")
if charts.get("stability_surface"):
    s = charts["stability_surface"]
    plt.figure(); plt.imshow(s["surface"], aspect="auto"); plt.colorbar(); plt.title("Stability Surface")
    plt.savefig("stability_surface.png")
print("charts written")
'''
