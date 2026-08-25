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
