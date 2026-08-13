#!/usr/bin/env python
"""Institutional Reproduction Program — Gatev, Goetzmann & Rouwenhorst (2006).

Paper 2 of the roadmap: the only OTHER landmark executable on price data alone.
FAITHFUL reproduction, no parameter tuning.

Gatev method: (1) FORMATION — normalize each stock to a cumulative total-return
index, pick the pair with minimum sum-of-squared-deviation between the two
normalized price paths. (2) TRADING — open the pair when the spread diverges by
2 historical standard deviations, close on convergence (mean reversion).

We reuse the existing `PairsStrategy` (raw-spread z-score) + `ResearchRunner`
unchanged. Pair selection = Gatev distance on the formation half. entry_z=2.0 is
Gatev's exact 2-SD rule; no grid, single param set.

Fidelity gaps (implementation-related, documented — engine NOT modified):
  - Template z-scores the RAW price spread; Gatev uses the NORMALIZED-price
    spread. We scale-balance with hedge = mean(px_x)/mean(px_y) over formation
    to approximate normalization. Residual gap remains.
  - Gatev trades the top-20 pairs; a 12-name panel supports one robust pair.

    python scripts/reproduce_gatev_pairs.py
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mentisrex.backtesting.data.feed import BarData
from mentisrex.market_data.storage.duckdb_store import DuckDBStore
from mentisrex.research.runner import ResearchRunner, research_config
from mentisrex.research.store import ResearchStore
from mentisrex.research.templates import PairsStrategy

STORE_DB = "./data/analytics.duckdb"


def load_bars() -> list[BarData]:
    store = DuckDBStore(STORE_DB)
    rows = store.query(
        "SELECT symbol,timestamp,open,high,low,close,volume,frequency "
        "FROM ohlcv WHERE frequency='1d' ORDER BY timestamp,symbol"
    )
    store.close()
    return [
        BarData(
            symbol=r["symbol"], timestamp=r["timestamp"],
            open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
            low=Decimal(str(r["low"])), close=Decimal(str(r["close"])),
            volume=Decimal(str(r["volume"])), frequency=r["frequency"],
        )
        for r in rows
    ]


def select_gatev_pair(bars: list[BarData]) -> tuple[str, str, float, float]:
    """Formation half: min sum-of-squared-deviation of normalized price paths.

    Returns (x, y, ssd, hedge). hedge scale-balances the raw spread the template
    z-scores, approximating Gatev's normalized-price spread.
    """
    ts = sorted({b.timestamp for b in bars})
    formation_end = ts[len(ts) // 2]  # first half = formation, per Gatev split
    series: dict[str, list[tuple] ] = {}
    for b in bars:
        if b.timestamp <= formation_end:
            series.setdefault(b.symbol, []).append((b.timestamp, float(b.close)))

    # normalize each name to start=1 over aligned formation dates
    dates = sorted({t for s in series.values() for t, _ in s})
    norm: dict[str, list[float]] = {}
    for sym, pts in series.items():
        px = dict(pts)
        if len(px) < len(dates) or dates[0] not in px:
            continue  # require full formation history (no gaps) — faithful filter
        base = px[dates[0]]
        norm[sym] = [px[d] / base for d in dates if d in px]

    syms = sorted(norm)
    best = None
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            a, b_ = norm[syms[i]], norm[syms[j]]
            n = min(len(a), len(b_))
            ssd = sum((a[k] - b_[k]) ** 2 for k in range(n))
            if best is None or ssd < best[2]:
                best = (syms[i], syms[j], ssd)

    if best is None:
        raise SystemExit("no complete-history pair in formation window")
    x, y, ssd = best
    # scale-balance hedge from raw formation means
    mx = sum(float(px) for _, px in series[x]) / len(series[x])
    my = sum(float(px) for _, px in series[y]) / len(series[y])
    return x, y, ssd, round(mx / my, 4)


def main() -> None:
    bars = load_bars()
    syms = sorted({b.symbol for b in bars})
    ts = sorted({b.timestamp for b in bars})
    print(f"Data: {len(bars)} bars, {len(syms)} securities, {ts[0].date()}..{ts[-1].date()}\n")

    x, y, ssd, hedge = select_gatev_pair(bars)
    print(f"Gatev formation-selected pair: {x} / {y}  (SSD={ssd:.4f}, hedge={hedge})\n")

    # Gatev 2-SD rule. NO tuning: one param set, no grid.
    #   lookback 126d ~ 6-month spread window; entry at 2 SD; exit on reversion.
    params = {
        "symbol_x": x, "symbol_y": y,
        "lookback": 126, "entry_z": 2.0, "exit_z": 0.5, "hedge": hedge,
    }

    store = ResearchStore()
    runner = ResearchRunner(store)
    h = runner.hypothesis(
        statement=f"Normalized prices of the minimum-distance pair ({x},{y}) mean-revert; "
                  "trading 2-SD divergence earns relative-value profit (Gatev et al. 2006).",
        rationale="Law of one price: close economic substitutes co-move; temporary "
                  "divergences of the normalized spread revert.",
        researcher="reproduction_program",
    )
    print(f"Executing PairsStrategy, Gatev params: {params}\n")
    report = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: PairsStrategy(**p),
        base_params=params,
        bars=bars,
        config=research_config(),
        param_grid=None,          # faithful — no parameter search
        features_used=["normalized_price_spread_zscore"],
    )

    print("REPRODUCED RESULT (out-of-sample slice)")
    print(f"  IS Sharpe   : {report.is_sharpe:.3f}")
    print(f"  OOS Sharpe  : {report.oos_sharpe:.3f}")
    print(f"  OOS return  : {report.oos_return:.2%}")
    print(f"  OOS max DD  : {report.oos_max_drawdown:.2%}")
    print(f"  OOS trades  : {report.oos_trades}")
    print(f"  trials      : {report.n_trials}  (=1, no tuning)")
    print(f"  adj p-value : {report.adjusted_pvalue:.3f}")
    print(f"  verdict     : {report.verdict.value.upper()}")
    store.close()


if __name__ == "__main__":
    main()
