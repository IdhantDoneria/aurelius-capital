"""M38 — real-data cross-sectional factor sweep.

Runs genuine factors through the M34-M37 machinery on the analytics.duckdb OHLCV
panel (Indian equities, daily, 2014-2026). Symbol-keyed (identity.duckdb not
populated); universe per rebalance = top-N by trailing-12m dollar volume among
names with >=13 months of history — a liquidity screen with no forward info.

NOT the frozen ew-momentum-exp: this is independent cross-sectional factor IC
research, a different construct on the same data. No fabricated numbers — every
statistic is computed from real closes.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from mentisrex.research.ensemble import combine
from mentisrex.research.factor_campaign import FactorCampaign

TOP_N = 500
DB = "data/analytics.duckdb"


def load_monthly():
    c = duckdb.connect(DB, read_only=True)
    df = c.execute(
        "SELECT symbol, CAST(timestamp AS DATE) d, close, "
        "close*volume AS dv FROM ohlcv WHERE frequency='1d'"
    ).fetch_df()
    c.close()
    df["close"] = df["close"].astype(float)
    df["dv"] = df["dv"].astype(float)
    df["d"] = pd.to_datetime(df["d"])
    close = df.pivot_table(index="d", columns="symbol", values="close").sort_index()
    # month-end panels
    me_close = close.resample("ME").last()
    dv = df.pivot_table(index="d", columns="symbol", values="dv").sort_index()
    me_dv = dv.resample("ME").sum(min_count=1)
    return me_close, me_dv


def universe_at(me_close, me_dv, i):
    """Top-N liquid names with >=13 months of prior history at rebalance i."""
    if i < 12:
        return []
    hist = me_close.iloc[i - 12:i + 1]
    liquid = me_dv.iloc[i - 12:i + 1].mean()
    valid = hist.notna().all(axis=0)
    liquid = liquid[valid].dropna()
    return list(liquid.nlargest(TOP_N).index)


def build_panels(me_close, me_dv, signal_fn):
    signals, fwd = [], []
    n = len(me_close)
    for i in range(12, n - 1):
        names = universe_at(me_close, me_dv, i)
        if len(names) < 30:
            continue
        sig = {}
        for s in names:
            v = signal_fn(me_close[s], i)
            if v is not None and np.isfinite(v):
                sig[s] = v
        f = {}
        for s in sig:
            c0, c1 = me_close[s].iloc[i], me_close[s].iloc[i + 1]
            if np.isfinite(c0) and np.isfinite(c1) and c0 > 0:
                f[s] = c1 / c0 - 1.0
        if len(sig) >= 30:
            signals.append(sig)
            fwd.append(f)
    return signals, fwd


def mom_12_1(series, i):
    a, b = series.iloc[i - 12], series.iloc[i - 1]
    return (b / a - 1.0) if (np.isfinite(a) and np.isfinite(b) and a > 0) else None


def rev_1m(series, i):
    a, b = series.iloc[i - 1], series.iloc[i]
    return (-(b / a - 1.0)) if (np.isfinite(a) and np.isfinite(b) and a > 0) else None


def low_vol(series, i):
    w = series.iloc[i - 6:i + 1].astype(float)
    r = w.pct_change().dropna()
    return -float(r.std()) if len(r) >= 3 else None


def main():
    print("loading OHLCV -> monthly panels ...")
    me_close, me_dv = load_monthly()
    print(f"months: {len(me_close)}  symbols: {me_close.shape[1]}")

    camp = FactorCampaign("data/factor_library.duckdb", t_min=2.0,
                          redundancy_threshold=0.8)
    factors = {"mom_12_1": mom_12_1, "rev_1m": rev_1m, "low_vol_6m": low_vol}
    for name, fn in factors.items():
        sig, fwd = build_panels(me_close, me_dv, fn)
        res = camp.run(name, name.split("_")[0], sig, fwd, periods_per_year=12)
        r = res.report
        print(f"\n{name}: status={res.status}  periods={r.n_periods}  "
              f"avg_breadth={r.avg_breadth:.0f}")
        print(f"  IC mean={r.ic_mean:.4f}  IC-IR={r.ic_ir:.3f}  "
              f"HAC t={r.ic_t_stat:.2f} p={r.ic_p_value:.4f}  hit={r.ic_hit_rate:.2f}")
        print(f"  long-short Sharpe={r.ls_sharpe:.2f}  turnover={r.turnover:.2f}")
        if res.redundant_with:
            print(f"  REDUNDANT with {res.redundant_with}")

    series = camp.return_series(status="PROMISING")
    print(f"\nPROMISING factors: {list(series)}")
    if len(series) >= 2:
        e = combine(series, method="equal")
        print(f"ensemble(equal): Sharpe={e.sharpe:.2f}  HAC t={e.t_stat:.2f}  "
              f"eff_bets={e.effective_bets:.2f}  avg_corr={e.avg_correlation:.3f}  "
              f"div_ratio={e.diversification_ratio:.2f}")
    camp.close()


if __name__ == "__main__":
    main()
