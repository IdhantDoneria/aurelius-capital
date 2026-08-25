"""Backtest orchestration for the three swing strategies.

One entry point per strategy, all sharing the same dataset, the same risk
overlay and the same cost model, so the three results are comparable.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .construction import OverlayConfig
from .costs import CostConfig, FinancingModel
from .data import Dataset, load
from .metrics import Performance, evaluate
from .portfolio import BacktestConfig, SegmentBacktester
from .strategies import Lastlight, LastlightConfig, Nightfall, NightfallConfig
from .strategies.base import CrossSectionalStrategy, StagingConfig, unit_gross_vol_series

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")
OUT = DATA / "results"


def _financing(ds: Dataset, cost: CostConfig) -> FinancingModel:
    return FinancingModel(cfg=cost, overnight_rate=ds.rf)


def run_cross_sectional(
    ds: Dataset,
    strategy: CrossSectionalStrategy,
    *,
    cost: CostConfig | None = None,
    initial_equity: float = 100_000_000.0,
    delist_haircut: float = 0.0,
    vol_target_pass: bool = True,
) -> tuple[pd.DataFrame, Performance]:
    cost = cost or CostConfig()

    if vol_target_pass:
        fwd = ds.ret_on_fwd if strategy.trade_at == "moc" and getattr(
            strategy, "overnight_only", False
        ) else ds.ret_cc_fwd
        strategy.unit_vol = unit_gross_vol_series(
            strategy, fwd, lookback=strategy.overlay.vol_lookback
        )

    bt = SegmentBacktester(
        ds.panel,
        _financing(ds, cost),
        BacktestConfig(initial_equity=initial_equity, costs=cost, delist_haircut=delist_haircut),
    )
    strategy.reset()
    res = bt.run(strategy)
    perf = evaluate(
        res["ret"],
        benchmark=ds.benchmark,
        rf=ds.rf,
        gross=res["gross"],
        net=res["net"],
        turnover=res["turnover"],
    )
    return res, perf


def build_nightfall(
    ds: Dataset,
    *,
    config: NightfallConfig | None = None,
    overlay: OverlayConfig | None = None,
    hold_days: int = 5,
) -> Nightfall:
    return Nightfall(
        ds.cube,
        overlay or OverlayConfig(target_vol=0.10, gross_cap=2.5, max_weight=0.015, n_stat_factors=3),
        StagingConfig(hold_days=hold_days, stage=hold_days > 1),
        beta=ds.beta,
        factor_loadings=ds.factor_loadings,
        tradable=ds.panel.tradable,
        config=config,
    )


def build_lastlight(
    ds: Dataset,
    *,
    config: LastlightConfig | None = None,
    overlay: OverlayConfig | None = None,
    hold_days: int = 1,
) -> Lastlight:
    s = Lastlight(
        ds.cube,
        overlay or OverlayConfig(target_vol=0.10, gross_cap=3.0, max_weight=0.010, n_stat_factors=3),
        StagingConfig(hold_days=hold_days, stage=hold_days > 1),
        beta=ds.beta,
        factor_loadings=ds.factor_loadings,
        tradable=ds.panel.tradable,
        config=config,
        vix=ds.vix,
    )
    s.overnight_only = True
    return s


def _jsonable(obj):
    if is_dataclass(obj):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    return obj


def save(name: str, res: pd.DataFrame, perf: Performance, extra: dict | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    res.to_parquet(OUT / f"{name}_daily.parquet")
    payload = {"performance": perf.to_dict(), **_jsonable(extra or {})}
    (OUT / f"{name}_perf.json").write_text(json.dumps(payload, indent=2, default=float))


def summary_table(results: dict[str, Performance]) -> pd.DataFrame:
    rows = {k: v.to_dict() for k, v in results.items()}
    return pd.DataFrame(rows).T


# --------------------------------------------------------------------------
# Dayburn: the intraday sleeve is not a cross-sectional book, so it has its
# own loader and its own runner.
# --------------------------------------------------------------------------

DAYBURN_COLS = [
    "symbol", "d", "p_open", "p_close", "p_1000", "p_1545", "addv60",
    "gap_z", "rvol_or30", "or30_range_z", "or30_hi", "or30_lo",
    "rv_day", "sd_cc60", "prev_close",
]


def dayburn_inputs(
    *,
    features: str | Path = DATA / "features.parquet",
    bars: str | Path = DATA / "bars_rth" / "*.parquet",
    cone: str | Path = DATA / "cone.parquet",
    start: str = "2020-01-01",
    end: str = "2026-08-24",
    tier: str = "core",
    spread_scalar: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Assemble the per-session feature table, the bar table and the cone."""
    import duckdb

    from .costs import CostConfig, modelled_spread

    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    cols = ", ".join(DAYBURN_COLS)
    f = con.execute(
        f"""
        SELECT {cols},
               avg(rv_day) OVER (
                   PARTITION BY symbol ORDER BY d ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
               ) AS rv_day_prev
        FROM parquet_scan('{features}')
        WHERE d BETWEEN DATE '{start}' AND DATE '{end}' AND tier = '{tier}'
        """
    ).fetchdf()
    f["d"] = pd.to_datetime(f["d"]).dt.date
    f["daily_vol"] = f["sd_cc60"].fillna(f["sd_cc60"].median())
    f["spread"] = modelled_spread(
        f["daily_vol"].to_numpy(), f["addv60"].to_numpy(), f["p_open"].to_numpy(),
        scalar=spread_scalar,
    )

    b = con.execute(
        f"""
        SELECT symbol,
               CAST(ts AT TIME ZONE 'America/New_York' AS DATE) AS d,
               CAST(date_part('hour', ts AT TIME ZONE 'America/New_York') AS INT) * 60
                 + CAST(date_part('minute', ts AT TIME ZONE 'America/New_York') AS INT) AS mod,
               open, high, low, close, volume, vwap
        FROM parquet_scan('{bars}')
        WHERE close > 0
          AND CAST(ts AT TIME ZONE 'America/New_York' AS DATE)
              BETWEEN DATE '{start}' AND DATE '{end}'
        """
    ).fetchdf()
    b["d"] = pd.to_datetime(b["d"]).dt.date

    c = con.execute(f"SELECT * FROM parquet_scan('{cone}')").fetchdf()
    c["d"] = pd.to_datetime(c["d"]).dt.date
    return f, b, c


def run_dayburn(
    features: pd.DataFrame,
    bars: pd.DataFrame,
    cone: pd.DataFrame,
    *,
    config=None,
    cost: CostConfig | None = None,
    initial_equity: float = 100_000_000.0,
    benchmark: pd.Series | None = None,
    rf: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, Performance]:
    from .strategies import Dayburn

    d = Dayburn(features, bars, cone, config=config, cost=cost, initial_equity=initial_equity)
    trades, daily = d.run()
    if daily.empty:
        raise RuntimeError("dayburn produced no trades")
    perf = evaluate(
        daily["ret"],
        benchmark=benchmark, rf=rf,
        gross=daily["gross"], net=daily["net"], turnover=daily["turnover"],
    )
    return trades, daily, perf
