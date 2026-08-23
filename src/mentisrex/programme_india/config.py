"""Locked parameters for the India momentum-quality programme (M42).

Every number here is the one actually used to produce the backtest results
quoted in `docs/MENTISREX_M42_INDIA_TRADING_HANDBOOK.md` (2010-01-04 to
2026-03-30, real NSE price data, real yfinance-sourced fundamentals). Nothing
downstream should hard-code a parameter that belongs here.

Locked by the user after an explicit, documented experiment across five
exposure-overlay/position-sizing variants (see the handbook's "How these
numbers were chosen" section) — this is the final configuration, not a
default that invites further silent tuning.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndiaConfig:
    # --- Leverage / exposure overlay ---
    leverage_cap: float = 1.50          # hard ceiling, never breached
    target_vol: float = 0.31            # annualised, locked-in final value
    vol_scalar_floor: float = 0.50
    vol_scalar_ceiling: float = 1.50
    signal_lag_days: int = 2            # matches spec convention: decide on t, trade t+2
    trend_ma_fast: int = 100
    trend_ma_slow: int = 200
    breadth_ma: int = 100
    realised_vol_window: int = 63
    gate_mode: str = "min"              # worse-of-two, not average (see handbook: the 2018 fix)

    # --- Universe ---
    top_n_liquid: int = 200             # F&O-eligibility proxy (see handbook limitations)
    min_history_days: int = 280

    # --- Stock selection ---
    momentum_lookback_days: int = 252
    momentum_skip_days: int = 21
    quintile: float = 0.10              # decile, locked-in final value (was quintile=0.20)
    momentum_weight: float = 0.60
    quality_weight: float = 0.40
    sector_cap: float = 0.28
    per_name_cap: float = 0.08
    concentration_multiplier: float = 2.5   # cap = min(avg_weight * this, per_name_cap)

    # --- Fundamentals (quality factor) ---
    fundamentals_publication_lag_days: int = 90

    # --- Costs (all realistic, not modelled as free) ---
    stt_brokerage_impact_bps_oneway: float = 12.5
    extra_slippage_bps_oneway: float = 5.0
    exposure_change_cost_bps: float = 20.0
    leverage_carry_drag_annual: float = 0.008   # applied only to the >100% notional slice
    operational_error_drag_annual: float = 0.0020  # flat, every year, win or lose

    # --- Benchmark ---
    benchmark_dividend_yield: float = 0.012

    @property
    def cost_oneway_bps(self) -> float:
        return self.stt_brokerage_impact_bps_oneway + self.extra_slippage_bps_oneway


DEFAULT_CONFIG = IndiaConfig()
