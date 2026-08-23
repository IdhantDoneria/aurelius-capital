#!/usr/bin/env python
"""Run the locked India momentum-quality programme (M42) against real NSE
price data and print the final, verified performance numbers.

Data dependency, stated plainly: this script does NOT bundle the ~110MB NSE
price panel or the fundamentals/sector caches in the repo (data/ is
gitignored, and these are too large and too fast-changing to belong in git).
It reads them from the local acquisition pipeline built during this
programme's research phase. To reproduce on a fresh machine, point
--cache-dir at a directory containing:
    nse_panel.parquet, nse_panel_extension_2010_2014.parquet, nifty50.csv,
    fundamentals_real.csv, sector_map.csv
(see docs/MENTISREX_M42_INDIA_TRADING_HANDBOOK.md, "Reproducing this
backtest," for exactly how each of those was built and from what source.)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from mentisrex.programme_india.backtest import QualityLookup, run_backtest
from mentisrex.programme_india.config import DEFAULT_CONFIG, IndiaConfig
from mentisrex.programme_india.metrics import beta_alpha, cagr_from_returns, drawdown_stats, sharpe

REPO_BY_YEAR = {
    2008: 0.0800, 2009: 0.0500, 2010: 0.0575, 2011: 0.0750, 2012: 0.0800,
    2013: 0.0775, 2014: 0.0800, 2015: 0.0725, 2016: 0.0650, 2017: 0.0625,
    2018: 0.0650, 2019: 0.0565, 2020: 0.0425, 2021: 0.0400, 2022: 0.0525,
    2023: 0.0650, 2024: 0.0650, 2025: 0.0600, 2026: 0.0550,
}


def clean_bad_ticks(close: pd.DataFrame, threshold: float = 0.40, passes: int = 3) -> pd.DataFrame:
    c = close.copy()
    for _ in range(passes):
        r = c.pct_change()
        bad = r.abs() > threshold
        if not bad.values.any():
            break
        c = c.mask(bad)
        c = c.ffill(limit=5)
    return c


def load_panel(cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    existing = pd.read_parquet(cache_dir / "nse_panel.parquet")
    existing["date"] = pd.to_datetime(existing["date"])
    ext = pd.read_parquet(cache_dir / "nse_panel_extension_2010_2014.parquet")
    ext["date"] = pd.to_datetime(ext["date"])
    combined = pd.concat([ext[["symbol", "date", "close", "volume"]],
                           existing[["symbol", "date", "close", "volume"]]], ignore_index=True)
    combined = combined.drop_duplicates(subset=["symbol", "date"])
    counts = combined.groupby("date")["symbol"].nunique()
    good_dates = counts[counts >= 150].index
    good_dates = good_dates[good_dates.weekday < 5]
    combined = combined[combined["date"].isin(good_dates)]
    close = combined.pivot(index="date", columns="symbol", values="close").sort_index()
    vol = combined.pivot(index="date", columns="symbol", values="volume").sort_index()
    close = clean_bad_ticks(close.ffill(limit=3))
    return close, vol.fillna(0.0)


def load_quality(cache_dir: Path, cfg: IndiaConfig) -> QualityLookup:
    df = pd.read_csv(cache_dir / "fundamentals_real.csv", parse_dates=["fiscal_year_end"])
    for col in ("roe", "debt_to_equity"):
        mu, sd = df[col].mean(), df[col].std()
        df[col + "_z"] = (df[col] - mu) / sd
    stability = df.groupby("symbol")["net_income"].apply(
        lambda s: -s.std() / abs(s.mean()) if len(s) > 1 and s.mean() != 0 else 0.0
    ).rename("earnings_stability")
    df = df.merge(stability, on="symbol", how="left")
    mu, sd = df["earnings_stability"].mean(), df["earnings_stability"].std()
    df["stability_z"] = (df["earnings_stability"] - mu) / sd if sd > 0 else 0.0
    df["quality_score"] = 0.5 * df["roe_z"] - 0.3 * df["debt_to_equity_z"] + 0.2 * df["stability_z"]
    df["available_from"] = df["fiscal_year_end"] + pd.Timedelta(days=cfg.fundamentals_publication_lag_days)
    return QualityLookup(df[["symbol", "available_from", "quality_score"]])


def repo_daily_series(index: pd.DatetimeIndex) -> pd.Series:
    ann = pd.Series([REPO_BY_YEAR.get(y, 0.06) for y in index.year], index=index)
    return (1 + ann) ** (1 / 252) - 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path,
                     default=Path.home() / "Documents/Indian-Equity-Strategy-Backtest/cache")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2026-03-31")
    ap.add_argument("--capital-usd", type=float, default=1_000_000.0)
    args = ap.parse_args()

    cfg = DEFAULT_CONFIG
    print(f"Config: leverage_cap={cfg.leverage_cap} target_vol={cfg.target_vol} "
          f"quintile={cfg.quintile} gate_mode={cfg.gate_mode}")

    print("Loading price panel...")
    close, volume = load_panel(args.cache_dir)
    print(f"  {close.shape[1]} symbols, {close.index.min().date()} -> {close.index.max().date()}")

    bench_close = pd.read_csv(args.cache_dir / "nifty50.csv", index_col=0, parse_dates=True)["close"]
    sector_map = dict(zip(*pd.read_csv(args.cache_dir / "sector_map.csv")[["symbol", "sector"]].values.T))
    quality = load_quality(args.cache_dir, cfg)
    rf_daily = repo_daily_series(close.index)

    print("Running backtest (this takes a couple of minutes)...")
    strat_ret_full, exposure, avg_names = run_backtest(close, volume, bench_close, rf_daily, sector_map, quality, cfg)

    start_ts, end_ts = pd.Timestamp(args.start), min(pd.Timestamp(args.end), close.index.max())
    first_nonzero = strat_ret_full.replace(0, np.nan).first_valid_index()
    live_start = close.index[close.index.searchsorted(max(start_ts, first_nonzero))]
    idx = close.index[(close.index >= live_start) & (close.index <= end_ts)]
    strat_ret = strat_ret_full.reindex(idx).fillna(0.0)

    fx = yf.download("INR=X", period="5d", progress=False)
    fx_rate = float(fx["Close"].iloc[-1].iloc[0]) if hasattr(fx["Close"].iloc[-1], "iloc") else float(fx["Close"].iloc[-1])

    years = len(idx) / 252.0
    cagr = cagr_from_returns(strat_ret, years)
    vol = float(strat_ret.std() * np.sqrt(252))
    sharpe_raw = sharpe(strat_ret)
    sharpe_excess = sharpe(strat_ret, rf_daily)
    bench_ret_tri = (bench_close.pct_change() + cfg.benchmark_dividend_yield / 252.0).reindex(idx)
    beta, alpha = beta_alpha(strat_ret, bench_ret_tri)

    from mentisrex.programme_india.metrics import nav_series
    start_capital_inr = args.capital_usd * fx_rate
    nav = nav_series(strat_ret, start_capital_inr)
    dd = drawdown_stats(nav)

    print(f"\n=== FINAL VERIFIED RESULTS: {live_start.date()} -> {idx[-1].date()} ({years:.2f} years) ===")
    print(f"Start capital: ${args.capital_usd:,.0f}  (Rs {start_capital_inr:,.0f} cr equiv, fx={fx_rate:.2f})")
    print(f"End value: ${nav.iloc[-1]/fx_rate:,.0f}  (Rs {nav.iloc[-1]:,.0f})")
    print(f"CAGR: {cagr:.4%}")
    print(f"Volatility: {vol:.4%}")
    print(f"Sharpe (raw): {sharpe_raw:.3f}   Sharpe (excess over repo): {sharpe_excess:.3f}")
    print(f"Beta: {beta:.3f}   Alpha (annualised): {alpha:.4%}")
    print(f"Max drawdown: {dd.max_dd:.4%}  ({dd.peak_date} -> {dd.trough_date}, recovered {dd.recovery_date})")
    print(f"Longest underwater stretch: {dd.longest_underwater_days} trading days")
    print(f"Average names held: {avg_names:.1f}")
    print(f"Average exposure: {float(exposure.reindex(idx).mean()):.2%}")


if __name__ == "__main__":
    main()
