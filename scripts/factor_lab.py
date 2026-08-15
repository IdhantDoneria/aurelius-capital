"""Clean, market-split wide factor sweep (data-hygiene + wide battery).

Fixes the M38 contamination (US megacaps + Indian mid-caps mixed in one dollar-
volume ranking) by evaluating ONE market at a time. Runs a wide, PIT-correct
signal battery across horizons through the DoF-corrected, net-of-cost gate
(M31-M39). Every number here is still SURVIVORSHIP-SUSPECT until the Priority-1
data in docs/DATA_ACQUISITION_BRIEF.md lands — labelled as such.

Usage: python scripts/factor_lab.py [NS|US]   (default NS = India)
"""

from __future__ import annotations

import sys

import duckdb
import numpy as np
import pandas as pd

from mentisrex.research.factor_campaign import FactorCampaign
from mentisrex.research.portfolio.costs import TransactionCostModel

DB = "data/analytics.duckdb"
TOP_N = 300          # per-market liquid universe


def load_market(suffix: str):
    c = duckdb.connect(DB, read_only=True)
    if suffix == "NS":
        where = "symbol LIKE '%.NS'"
    else:  # US = everything not Indian
        where = "symbol NOT LIKE '%.NS' AND symbol NOT LIKE '%.BO'"
    df = c.execute(
        f"SELECT symbol, CAST(timestamp AS DATE) d, close, close*volume dv "
        f"FROM ohlcv WHERE frequency='1d' AND {where}"
    ).fetch_df()
    c.close()
    df["close"] = df["close"].astype(float)
    df["dv"] = df["dv"].astype(float)
    df["d"] = pd.to_datetime(df["d"])
    close = df.pivot_table(index="d", columns="symbol", values="close").sort_index()
    dv = df.pivot_table(index="d", columns="symbol", values="dv").sort_index()
    return close.resample("ME").last(), dv.resample("ME").sum(min_count=1)


def universe_at(me_close, me_dv, i, lookback=12):
    if i < lookback:
        return []
    hist = me_close.iloc[i - lookback:i + 1]
    liquid = me_dv.iloc[i - lookback:i + 1].mean()
    valid = hist.notna().all(axis=0)
    liquid = liquid[valid].dropna()
    return list(liquid.nlargest(TOP_N).index)


# ── PIT signal battery (each uses only bars <= i) ────────────────────────────

def _ret(series, i, k):
    a, b = series.iloc[i - k], series.iloc[i]
    return (b / a - 1.0) if (a and np.isfinite(a) and np.isfinite(b) and a > 0) else None


def mom_1m(s, i, dv=None):  return _ret(s, i, 1)
def mom_3m(s, i, dv=None):  return _ret(s, i, 3)
def mom_6m(s, i, dv=None):  return _ret(s, i, 6)
def mom_12m(s, i, dv=None): return _ret(s, i, 12)


def mom_12_1(s, i, dv=None):
    a, b = s.iloc[i - 12], s.iloc[i - 1]
    return (b / a - 1.0) if (a and np.isfinite(a) and np.isfinite(b) and a > 0) else None


def rev_1m(s, i, dv=None):
    r = _ret(s, i, 1)
    return -r if r is not None else None


def _vol(s, i, w):
    win = s.iloc[i - w:i + 1].astype(float)
    r = win.pct_change().dropna()
    return -float(r.std()) if len(r) >= 3 else None   # low-vol => higher signal


def low_vol_3m(s, i, dv=None): return _vol(s, i, 3)
def low_vol_6m(s, i, dv=None): return _vol(s, i, 6)


def high_52w(s, i, dv=None):
    win = s.iloc[i - 11:i + 1].astype(float)
    hi = win.max()
    return float(s.iloc[i] / hi) if (hi and np.isfinite(hi) and hi > 0) else None


SIGNALS = {
    "mom_1m": mom_1m, "mom_3m": mom_3m, "mom_6m": mom_6m, "mom_12m": mom_12m,
    "mom_12_1": mom_12_1, "rev_1m": rev_1m,
    "low_vol_3m": low_vol_3m, "low_vol_6m": low_vol_6m, "high_52w": high_52w,
}


def build_panels(me_close, me_dv, fn):
    signals, fwd = [], []
    n = len(me_close)
    for i in range(12, n - 1):
        names = universe_at(me_close, me_dv, i)
        if len(names) < 30:
            continue
        sig, f = {}, {}
        for s in names:
            v = fn(me_close[s], i)
            if v is not None and np.isfinite(v):
                sig[s] = v
        for s in sig:
            c0, c1 = me_close[s].iloc[i], me_close[s].iloc[i + 1]
            if np.isfinite(c0) and np.isfinite(c1) and c0 > 0:
                f[s] = c1 / c0 - 1.0
        if len(sig) >= 30:
            signals.append(sig)
            fwd.append(f)
    return signals, fwd


def main():
    market = sys.argv[1] if len(sys.argv) > 1 else "NS"
    label = "India (NSE)" if market == "NS" else "US/other"
    print(f"=== market: {label}  [SURVIVORSHIP-SUSPECT] ===")
    me_close, me_dv = load_market(market)
    print(f"months={len(me_close)}  symbols={me_close.shape[1]}  universe/mo<= {TOP_N}")

    cm = TransactionCostModel(commission_bps=1.0, spread_bps=3.0, slippage_bps=2.0)  # 4.5 bps
    camp = FactorCampaign(f"data/factor_library_{market}.duckdb", t_min=2.0,
                          redundancy_threshold=0.8)
    rows = []
    for name, fn in SIGNALS.items():
        sig, fwd = build_panels(me_close, me_dv, fn)
        if len(sig) < 24:
            print(f"{name:12s} insufficient periods ({len(sig)})"); continue
        res = camp.run(name, name.split("_")[0], sig, fwd, periods_per_year=12, cost_model=cm)
        r = res.report
        rows.append((name, r.ic_mean, r.ic_ir, r.ic_t_stat, r.ls_sharpe,
                     r.net_ls_sharpe, r.net_ls_t_stat, r.turnover, res.status))
    print(f"\n{'signal':12s} {'IC':>7} {'IC-IR':>6} {'IC t':>6} {'grossS':>7} "
          f"{'netS':>6} {'net t':>6} {'turn':>5}  status")
    for n, ic, ir, t, gs, ns, nt, tu, st in sorted(rows, key=lambda x: -abs(x[3])):
        print(f"{n:12s} {ic:7.4f} {ir:6.3f} {t:6.2f} {gs:7.2f} {ns:6.2f} "
              f"{nt:6.2f} {tu:5.2f}  {st}")

    series = camp.return_series(status="PROMISING")
    print(f"\nPROMISING & non-redundant: {list(series)}")
    if len(series) >= 2:
        from mentisrex.research.ensemble import combine
        e = combine(series, method="equal")
        print(f"ensemble: net-naive Sharpe={e.sharpe:.2f} HACt={e.t_stat:.2f} "
              f"eff_bets={e.effective_bets:.2f} avg_corr={e.avg_correlation:.3f}")
    camp.close()


if __name__ == "__main__":
    main()
