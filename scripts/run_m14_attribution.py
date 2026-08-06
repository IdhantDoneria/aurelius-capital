#!/usr/bin/env python
"""M14 factor attribution — decompose the M13 long-only low-vol return vs beta.

ATTRIBUTION ONLY. No strategy change: same certified M13 canonical LowVolStrategy
(long-only, lookback 252, quantile 0.10, monthly rebalance, M8 bounded construction),
same US canonical panel, same engine/execution. This script only regresses the
already-certified portfolio return against risk factors.

Factors buildable from the M6 price+volume panel:
  MARKET   — equal-weight universe daily return (breadth proxy; no cap weights,
             because shares-outstanding data does not exist in the panel).
  MOMENTUM — WML: trailing 12-1 (252d skip last 21d) top-decile EW return minus
             bottom-decile, monthly rebalance.

NOT buildable (M6 data ceiling) — skipped, documented in the report:
  SIZE  — needs market cap = shares outstanding x price; shares outstanding absent.
  VALUE — needs book value / fundamentals (Compustat); absent.
  SECTOR attribution — needs sector/industry classification metadata; absent.

Phases: 1 factor exposures; 2 single-factor market OLS (alpha/beta/R2/CIs);
3 rolling 126d beta; 5 residual performance after stripping beta*market.

    uv run python scripts/run_m14_attribution.py
Output: campaign/lowvol_longonly/m14/attribution.json
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb
import numpy as np

from aurelius.backtesting.data.feed import BarData
from aurelius.market_data.storage.isolation import validated_universe_filter
from aurelius.research.runner import research_config
from aurelius.research.templates import LowVolStrategy
from aurelius.research.validation import run_backtest

STORE_DB = "./data/analytics.duckdb"
US_PRED = "frequency='1d' AND symbol NOT LIKE '%.%'"
BASE = dict(lookback=252, quantile=0.10, rebalance_days=21, allow_short=False,
            equal_weight=True, min_price=5.0, invariant_construction=True)
COST = (10, 5, 10)
RF_ANNUAL, TD = 0.05, 252
RF_D = RF_ANNUAL / TD
MOM_LB, MOM_SKIP, MOM_REB, Q = 252, 21, 21, 0.10
ROLL_WIN = 126
Z95 = 1.96  # large-sample normal approx (~2900 daily obs); scipy not required


def load_rows() -> list[tuple]:
    pred = validated_universe_filter(US_PRED)
    conn = duckdb.connect(STORE_DB, read_only=True)
    rows = conn.execute(
        "SELECT symbol,timestamp,open,high,low,close,volume,frequency "
        f"FROM ohlcv WHERE {pred} ORDER BY timestamp,symbol").fetchall()
    conn.close()
    return rows


def bars_from(rows) -> list[BarData]:
    return [BarData(symbol=r[0], timestamp=r[1], open=Decimal(str(r[2])),
                    high=Decimal(str(r[3])), low=Decimal(str(r[4])),
                    close=Decimal(str(r[5])), volume=Decimal(str(r[6])),
                    frequency=r[7]) for r in rows]


def portfolio_returns(rows) -> dict:
    """Run the certified M13 canonical book, return {date: daily_return}."""
    bars = bars_from(rows)
    cfg = research_config(max_position_pct=Decimal("1.0"),
                          commission_rate=Decimal(COST[0]) / Decimal(10000),
                          spread_bps=Decimal(COST[1]),
                          slippage_impact_bps=Decimal(COST[2]))
    m = run_backtest(lambda: LowVolStrategy(**BASE), bars, cfg)
    daily: dict = {}
    for p in m.equity_curve:            # last equity per calendar date (engine rule)
        daily[p.timestamp.date()] = p.equity
    dates = sorted(daily)
    return {dates[i]: daily[dates[i]] / daily[dates[i - 1]] - 1
            for i in range(1, len(dates))}, m


def price_panel(rows) -> tuple[list, dict]:
    """{symbol: {date: close}} and sorted unique dates."""
    by: dict = {}
    dates = set()
    for r in rows:
        sym, ts, close = r[0], r[1], float(r[5])
        d = ts.date()
        by.setdefault(sym, {})[d] = close
        dates.add(d)
    return sorted(dates), by


def market_returns(dates, panel) -> dict:
    """Equal-weight universe daily return by date."""
    out: dict = {}
    for i in range(1, len(dates)):
        d0, d1 = dates[i - 1], dates[i]
        rets = [panel[s][d1] / panel[s][d0] - 1
                for s in panel if d0 in panel[s] and d1 in panel[s] and panel[s][d0]]
        if rets:
            out[d1] = float(np.mean(rets))
    return out


def momentum_returns(dates, panel) -> dict:
    """WML: monthly-rebalanced top-decile minus bottom-decile 12-1 momentum, daily EW."""
    idx = {d: i for i, d in enumerate(dates)}
    longs: list[str] = []
    shorts: list[str] = []
    out: dict = {}
    for i in range(1, len(dates)):
        d0, d1 = dates[i - 1], dates[i]
        if (i - 1) % MOM_REB == 0:       # rebalance at prior close
            scores = []
            for s, px in panel.items():
                if d0 not in px:
                    continue
                j = idx[d0]
                if j - MOM_LB < 0:
                    continue
                past, recent = dates[j - MOM_LB], dates[j - MOM_SKIP]
                if past in px and recent in px and px[past]:
                    scores.append((px[recent] / px[past] - 1, s))
            if len(scores) >= 20:
                scores.sort()
                k = max(1, int(Q * len(scores)))
                shorts = [s for _, s in scores[:k]]
                longs = [s for _, s in scores[-k:]]
        if longs and shorts:
            lr = [panel[s][d1] / panel[s][d0] - 1 for s in longs
                  if d0 in panel[s] and d1 in panel[s] and panel[s][d0]]
            sr = [panel[s][d1] / panel[s][d0] - 1 for s in shorts
                  if d0 in panel[s] and d1 in panel[s] and panel[s][d0]]
            if lr and sr:
                out[d1] = float(np.mean(lr) - np.mean(sr))
    return out


def ols(y: np.ndarray, X: np.ndarray) -> dict:
    """OLS with intercept prepended. Returns coefs, SEs, t, 95% CI, R2."""
    Xd = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(Xd, y, rcond=None)
    resid = y - Xd @ beta
    n, k = Xd.shape
    rss = float(resid @ resid)
    sigma2 = rss / (n - k)
    cov = sigma2 * np.linalg.inv(Xd.T @ Xd)
    se = np.sqrt(np.diag(cov))
    t = beta / se
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - rss / tss if tss else 0.0
    return {"coef": beta, "se": se, "t": t, "r2": r2, "resid": resid, "n": n}


def perf(returns: np.ndarray) -> dict:
    """Annualized CAGR, Sharpe, max drawdown from a daily return series."""
    eq = np.cumprod(1 + returns)
    n = len(returns)
    cagr = float(eq[-1] ** (TD / n) - 1) if n else 0.0
    sd = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / sd * np.sqrt(TD)) if sd else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1).min())
    return {"cagr": round(cagr, 4), "sharpe": round(sharpe, 4),
            "max_drawdown": round(mdd, 4), "total_return": round(float(eq[-1] - 1), 4)}


def main() -> None:
    out = Path("campaign/lowvol_longonly/m14/attribution.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    (pret, m) = portfolio_returns(rows)
    dates, panel = price_panel(rows)
    mret = market_returns(dates, panel)
    wml = momentum_returns(dates, panel)

    common = sorted(set(pret) & set(mret) & set(wml))
    rp = np.array([pret[d] for d in common])
    rm = np.array([mret[d] for d in common])
    rw = np.array([wml[d] for d in common])
    y = rp - RF_D                 # portfolio excess
    xm = rm - RF_D                # market excess

    # Phase 2 — single-factor market model (the certifying regression)
    m1 = ols(y, xm.reshape(-1, 1))
    a_d, b = m1["coef"]
    a_ann = a_d * TD
    a_se_ann = m1["se"][0] * TD
    single = {
        "alpha_annual": round(float(a_ann), 4),
        "alpha_annual_ci95": [round(float(a_ann - Z95 * a_se_ann), 4),
                              round(float(a_ann + Z95 * a_se_ann), 4)],
        "alpha_t": round(float(m1["t"][0]), 3),
        "beta": round(float(b), 4),
        "beta_ci95": [round(float(b - Z95 * m1["se"][1]), 4),
                      round(float(b + Z95 * m1["se"][1]), 4)],
        "beta_t": round(float(m1["t"][1]), 3),
        "r2": round(m1["r2"], 4),
        "n_obs": m1["n"],
        "alpha_significant_5pct": bool(abs(m1["t"][0]) > Z95),
    }

    # Phase 1 — factor exposures (market + momentum; size/value unavailable)
    m2 = ols(y, np.column_stack([xm, rw]))
    two = {
        "alpha_annual": round(float(m2["coef"][0] * TD), 4),
        "alpha_t": round(float(m2["t"][0]), 3),
        "market_beta": round(float(m2["coef"][1]), 4),
        "market_t": round(float(m2["t"][1]), 3),
        "momentum_beta": round(float(m2["coef"][2]), 4),
        "momentum_t": round(float(m2["t"][2]), 3),
        "r2": round(m2["r2"], 4),
        "alpha_significant_5pct": bool(abs(m2["t"][0]) > Z95),
    }

    # Phase 3 — rolling 126d single-factor beta
    betas = []
    for i in range(ROLL_WIN, len(y) + 1):
        yy, xx = y[i - ROLL_WIN:i], xm[i - ROLL_WIN:i]
        v = float(((xx - xx.mean()) ** 2).sum())
        betas.append(float(((xx - xx.mean()) * (yy - yy.mean())).sum() / v) if v else 0.0)
    ba = np.array(betas)
    rolling = {"window": ROLL_WIN, "n": len(betas),
               "beta_min": round(float(ba.min()), 4), "beta_max": round(float(ba.max()), 4),
               "beta_mean": round(float(ba.mean()), 4), "beta_std": round(float(ba.std()), 4)}

    # Phase 5 — residual performance after stripping beta*market
    resid_daily = y - b * xm      # = alpha + epsilon; market component removed
    residual = perf(resid_daily)
    raw = perf(rp)

    result = {
        "portfolio": "M13 canonical long-only low-vol (unchanged)",
        "n_obs": len(common), "date_start": str(common[0]), "date_end": str(common[-1]),
        "risk_free_annual": RF_ANNUAL,
        "raw_full_sample": {**raw, "engine_total_return": round(float(m.total_return), 4),
                            "engine_max_drawdown": round(float(m.max_drawdown), 4)},
        "phase2_single_factor_market": single,
        "phase1_two_factor_market_momentum": two,
        "phase3_rolling_beta": rolling,
        "phase5_residual_after_market": residual,
        "factors_unavailable": {
            "size": "no shares-outstanding data -> no market cap (M6 price+volume panel)",
            "value": "no book value / fundamentals (Compustat absent, M6)",
            "sector": "no sector/industry classification metadata (M6)",
        },
    }
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    print(f"\nOutput: {out}", flush=True)


if __name__ == "__main__":
    main()
