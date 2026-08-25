"""Load the feature panel into the wide arrays the simulator consumes.

Everything here is shape (T, N) with T sessions and N symbols. Symbols that
were never in the universe on a given day carry NaN, and `tradable` marks
the days a name may actually be held -- membership, price floor, and the
presence of a bar on that session, so a delisted name simply stops being
tradable on the day its bars stop.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .costs import corwin_schultz_spread, modelled_spread
from .portfolio import MarketPanel
from .strategies.base import FeatureCube

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")

PIVOT_COLS = [
    "p_open", "p_close", "p_1545", "prev_close", "hi", "lo", "addv60",
    "ret_on", "ret_id", "ret_cc", "rvol", "pre_rvol", "rvol_or30",
    "close_vol_share", "close_push", "close_vs_vwap", "gap_z", "id_z",
    "son5", "sid5", "son10", "sid10", "son21", "sid21", "son63", "sid63",
    "idup10", "onup10", "sd_on60", "sd_id60", "sd_cc20", "sd_cc60",
    "amihud20", "mom21", "mom63", "mom252", "rv_day", "rv_ratio", "clv",
    "range_pos20", "hi2", "lo2", "is_earn_day", "earn_surprise", "liq_rank",
]


@dataclass
class Dataset:
    dates: pd.DatetimeIndex
    symbols: np.ndarray
    cube: FeatureCube
    panel: MarketPanel
    beta: np.ndarray
    factor_loadings: np.ndarray
    benchmark: pd.Series
    vix: np.ndarray
    rf: pd.Series
    ret_cc_fwd: np.ndarray
    ret_on_fwd: np.ndarray


def _pivot(df: pd.DataFrame, col: str, dates, symbols) -> np.ndarray:
    m = df.pivot(index="d", columns="symbol", values=col)
    return m.reindex(index=dates, columns=symbols).to_numpy(dtype=float)


def load(
    *,
    features: str | Path = DATA / "features.parquet",
    macro: str | Path = DATA / "macro.parquet",
    start: str = "2016-01-01",
    end: str = "2026-08-24",
    tier: str = "core",
    benchmark_symbol: str = "SPY",
    earnings_window: int = 3,
    beta_window: int = 60,
    spread_scalar: float = 1.0,
) -> Dataset:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    cols = ", ".join(PIVOT_COLS)
    df = con.execute(
        f"""
        SELECT symbol, d, tier, {cols}
        FROM parquet_scan('{features}')
        WHERE d BETWEEN DATE '{start}' AND DATE '{end}'
          AND (tier = '{tier}' OR symbol = '{benchmark_symbol}')
        """
    ).fetchdf()
    df["d"] = pd.to_datetime(df["d"])

    dates = pd.DatetimeIndex(sorted(df["d"].unique()))
    symbols = np.array(sorted(df["symbol"].unique()))
    data = {c: _pivot(df, c, dates, symbols) for c in PIVOT_COLS}

    # ---- benchmark ---------------------------------------------------------
    bidx = np.where(symbols == benchmark_symbol)[0]
    if bidx.size == 0:
        raise ValueError(f"{benchmark_symbol} absent from the feature panel")
    b = int(bidx[0])
    bench_cc = pd.Series(data["ret_cc"][:, b], index=dates).astype(float)
    bench_simple = np.expm1(bench_cc)

    # ---- earnings proximity ------------------------------------------------
    is_earn = np.nan_to_num(data["is_earn_day"])
    near = np.zeros_like(is_earn)
    for k in range(-earnings_window, earnings_window + 1):
        near += np.roll(is_earn, k, axis=0)
    near[: earnings_window + 1] = 1.0
    near[-(earnings_window + 1):] = 1.0
    data["earn_near"] = near

    # ---- rolling beta to the benchmark ------------------------------------
    r = np.nan_to_num(data["ret_cc"])
    rb = np.nan_to_num(bench_cc.to_numpy())[:, None]
    w = beta_window
    def roll_sum(x):
        c = np.cumsum(np.vstack([np.zeros((1, x.shape[1])), x]), axis=0)
        out = np.full_like(x, np.nan)
        out[w:] = c[w + 1 : len(c)] - c[1 : len(c) - w]
        return out

    sxy = roll_sum(r * rb)
    sx = roll_sum(np.repeat(rb, r.shape[1], axis=1))
    sy = roll_sum(r)
    sxx = roll_sum(np.repeat(rb**2, r.shape[1], axis=1))
    cov = sxy / w - (sx / w) * (sy / w)
    var = sxx / w - (sx / w) ** 2
    beta = np.divide(cov, var, out=np.full_like(cov, 1.0), where=np.abs(var) > 1e-14)
    beta = np.clip(np.nan_to_num(beta, nan=1.0), -3.0, 4.0)
    # a beta may only use returns strictly before the decision date
    beta = np.vstack([np.full((1, beta.shape[1]), 1.0), beta[:-1]])

    # ---- style loadings used as a sector proxy -----------------------------
    def zrow(x):
        out = np.zeros_like(x)
        for t in range(x.shape[0]):
            v = x[t]
            m = np.isfinite(v)
            if m.sum() > 10:
                s = v[m].std(ddof=1)
                if s > 0:
                    out[t, m] = (v[m] - v[m].mean()) / s
        return out

    size = zrow(np.log(np.clip(data["addv60"], 1.0, None)))
    mom = zrow(data["mom63"])
    vol = zrow(data["sd_cc60"])
    factor_loadings = np.stack([size, mom, vol], axis=2)

    # ---- market panel ------------------------------------------------------
    daily_vol = np.nan_to_num(data["sd_cc60"], nan=float(np.nanmedian(data["sd_cc60"])))
    spread = modelled_spread(daily_vol, data["addv60"], data["p_close"], scalar=spread_scalar)
    tradable = (
        np.isfinite(data["p_close"])
        & np.isfinite(data["p_open"])
        & np.isfinite(data["prev_close"])
        & (np.nan_to_num(data["p_close"]) > 0)
        & np.isfinite(data["liq_rank"])
    )
    tradable[:, b] = tradable[:, b]  # benchmark stays tradable for hedging

    htb = np.zeros_like(tradable)
    am = data["amihud20"]
    for t in range(len(dates)):
        v = am[t]
        m = np.isfinite(v)
        if m.sum() > 50:
            htb[t] = m & (v >= np.quantile(v[m], 0.80))

    panel = MarketPanel(
        dates=dates,
        symbols=symbols,
        open_=data["p_open"],
        close=data["p_close"],
        prev_close=data["prev_close"],
        adv=data["addv60"],
        spread=spread,
        daily_vol=daily_vol,
        tradable=tradable,
        htb=htb,
    )

    # ---- macro -------------------------------------------------------------
    mac = pd.read_parquet(macro)
    vix = mac["VIX"].reindex(dates).ffill().to_numpy(dtype=float)
    rf = (mac["TBILL3M"].reindex(dates).ffill() / 100.0).fillna(0.0)

    # ---- forward segment returns used for the vol-targeting pre-pass -------
    ret_cc_fwd = np.vstack([np.expm1(np.nan_to_num(data["ret_cc"]))[1:], np.zeros((1, len(symbols)))])
    ret_on_fwd = np.vstack([np.expm1(np.nan_to_num(data["ret_on"]))[1:], np.zeros((1, len(symbols)))])

    return Dataset(
        dates=dates,
        symbols=symbols,
        cube=FeatureCube(dates=dates, symbols=symbols, data=data),
        panel=panel,
        beta=beta,
        factor_loadings=factor_loadings,
        benchmark=pd.Series(bench_simple, index=dates),
        vix=vix,
        rf=rf,
        ret_cc_fwd=ret_cc_fwd,
        ret_on_fwd=ret_on_fwd,
    )
