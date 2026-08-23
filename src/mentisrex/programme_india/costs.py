"""Cost model: transaction costs, exposure-change costs, leverage carry
drag, and a flat operational-error haircut.

Every rate here is a realistic, stated assumption -- none are modelled as
zero. See the handbook's cost-stack section for the reasoning behind each
number (STT rates, typical Indian discount-broker slippage, and why an
operational-error drag is included at all).
"""

from __future__ import annotations

import pandas as pd

from mentisrex.programme_india.config import IndiaConfig


def turnover(new_weights: pd.Series, prev_weights: pd.Series) -> float:
    """One-way turnover: half the sum of absolute weight changes."""
    all_names = new_weights.index.union(prev_weights.index)
    nw = new_weights.reindex(all_names, fill_value=0.0)
    pw = prev_weights.reindex(all_names, fill_value=0.0)
    return float(0.5 * (nw - pw).abs().sum())


def rebalance_cost(turnover_frac: float, cfg: IndiaConfig) -> float:
    return turnover_frac * (cfg.cost_oneway_bps / 10_000.0)


def exposure_change_cost(exposure: pd.Series, cfg: IndiaConfig) -> pd.Series:
    return exposure.diff().abs().fillna(0.0) * (cfg.exposure_change_cost_bps / 10_000.0)


def leverage_carry_drag(exposure: pd.Series, cfg: IndiaConfig) -> pd.Series:
    """Small net financing drag, applied only to the slice of exposure
    above 100% (the actual leveraged/borrowed portion)."""
    return (exposure - 1.0).clip(lower=0.0) * (cfg.leverage_carry_drag_annual / 252.0)


def operational_error_drag(cfg: IndiaConfig) -> float:
    """Flat annual haircut, applied every trading day, win or lose -- a
    standard professional allowance for the things no backtest naturally
    captures (a late rebalance, a fat-finger correction, a missed exit
    before a circuit halt)."""
    return cfg.operational_error_drag_annual / 252.0
