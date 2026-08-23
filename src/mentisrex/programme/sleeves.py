"""Signals -> sleeve weights, holding periods, cost model (spec §3.1, §3.3, §4.2).

Numeric core is `float64` pandas/numpy throughout, matching every other module
in `programme/`; this is deliberate (spec §5.1 cost-versus-horizon inequality
is a floating-point argument, not a ledger).

The design decision this module encodes is spec §3.1: gross information from a
signal falls as `h^-1/2` with holding period `h`, but cost rises as `h^-1`
(rebalances scale as `1/h`, and cost per rebalance is roughly fixed). Cost
always wins as `h` shrinks, so sleeves are held for multiple days
(`SleeveConfig.hold_days`) rather than rebalanced every day, and the book is
allowed to **drift** with returns between rebalances rather than recomputed
from scratch. `apply_holding_period` is where that drift lives; it is why the
turnover this module reports comes out at the spec's Table 3 order of
magnitude (11-22x annualised for the 10/21-day sleeves) instead of roughly 4x
that under a naive "rebalance every row toward the current signal" construction.

Lag: `sleeve_returns` is the ONLY place `signal_to_trade_lag` is applied,
per the contract's lag model (spec §2.4). Nothing else in this module shifts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from mentisrex.programme.signals import compute_all_signals

from mentisrex.core.logging import get_logger
from mentisrex.programme.config import ProgrammeConfig

logger = get_logger(__name__)

_MIN_VALID_NAMES = 20


def directional_to_weights(exposure: pd.Series, panel: object) -> pd.DataFrame:
    """Weight frame with `exposure` in the benchmark column, 0 elsewhere.

    `panel` is a `PricePanel` (data.py); only `.columns` and `.benchmark` are
    used, so a lightweight stand-in with those attributes also works.
    """
    columns = panel.columns
    weights = pd.DataFrame(0.0, index=exposure.index, columns=columns)
    weights.loc[:, panel.benchmark] = exposure.to_numpy(dtype="float64")
    return weights


def cross_sectional_to_weights(scores: pd.DataFrame, panel: object) -> pd.DataFrame:
    """Per date: demean over valid names (dollar neutral), then divide by
    sum(|w|) so gross == 1.0. All-NaN or < 20-name rows -> all zeros.
    Benchmark column is always 0.
    """
    columns = panel.columns
    valid = scores.notna()
    n_valid = valid.sum(axis=1)

    demeaned = scores.sub(scores.mean(axis=1, skipna=True), axis=0).where(valid)
    gross = demeaned.abs().sum(axis=1, skipna=True)

    enough = n_valid >= _MIN_VALID_NAMES
    safe_gross = gross.where(enough & (gross > 0), other=1.0)
    normalised = demeaned.div(safe_gross, axis=0).fillna(0.0)
    normalised = normalised.where(enough, other=0.0)

    weights = pd.DataFrame(0.0, index=scores.index, columns=columns)
    weights.loc[:, normalised.columns] = normalised
    weights.loc[:, panel.benchmark] = 0.0
    return weights


def apply_holding_period(
    weights: pd.DataFrame, hold_days: int, returns: pd.DataFrame
) -> pd.DataFrame:
    """Discrete rebalance every `hold_days` rows; the book DRIFTS with returns
    between rebalances (spec Table 26: "turnover measured against the drifted
    book"). Rebalance rows are those where the positional index `i` (counted
    from the first row with a non-empty signal) satisfies `i % hold_days == 0`.

    Drift: `w_drifted(t) = w(t-1) * (1 + r(t))`, then rescaled so the drifted
    book's gross equals `w(t-1)`'s gross — drift changes composition, not
    scale. `hold_days == 1` rebalances every row (no drift).

    The recursion is sequential by construction (each day's drifted book
    depends on the previous day's), so this is a single forward pass over
    dates; there is no loop over names.
    """
    if hold_days < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days}")

    aligned_returns = returns.reindex(index=weights.index, columns=weights.columns).fillna(0.0)
    values = weights.to_numpy(dtype="float64")
    ret_values = aligned_returns.to_numpy(dtype="float64")
    n_rows, n_cols = values.shape
    out = np.zeros_like(values)

    # "non-empty signal" = the first row that isn't entirely NaN. Directional
    # weights carry NaN in the benchmark column before the signal's lookback
    # window is satisfied; cross-sectional weights are never NaN (all-invalid
    # rows are already zeroed by `cross_sectional_to_weights`), so for those
    # first_row is simply 0.
    has_data = weights.notna().any(axis=1).to_numpy()
    non_empty = np.flatnonzero(has_data)
    first_row = int(non_empty[0]) if non_empty.size else n_rows

    if hold_days == 1:
        out[first_row:] = np.nan_to_num(values[first_row:], nan=0.0)
        return pd.DataFrame(out, index=weights.index, columns=weights.columns)

    prev = np.zeros(n_cols)
    for i in range(first_row, n_rows):
        positional = i - first_row
        if positional % hold_days == 0:
            current = np.nan_to_num(values[i], nan=0.0)
        else:
            drifted = prev * (1.0 + ret_values[i])
            prev_gross = np.abs(prev).sum()
            drifted_gross = np.abs(drifted).sum()
            if drifted_gross > 0.0:
                current = drifted * (prev_gross / drifted_gross)
            else:
                current = drifted
        out[i] = current
        prev = current

    return pd.DataFrame(out, index=weights.index, columns=weights.columns)


def sleeve_returns(weights: pd.DataFrame, returns: pd.DataFrame, lag: int) -> pd.Series:
    """(weights.shift(lag) * returns).sum(axis=1). The ONLY place lag is applied
    in this module (contract §0, "The lag model")."""
    aligned_returns = returns.reindex(columns=weights.columns).fillna(0.0)
    return (weights.shift(lag) * aligned_returns).sum(axis=1)


def turnover(weights: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    """Per-date ONE-WAY notional traded as a fraction of NAV, measured against
    the DRIFTED prior book: `sum(abs(w(t) - w_drifted(t)))`.

    CONTRACT-NOTE: the contract's own prose contradicts itself here (one line
    says "/2", the next says "NO, return sum(abs(...))" without dividing).
    The binding text is the un-halved version — `test_cost_identity` asserts
    `transaction_cost == turnover * one_way_bps / 10_000` to 1e-12, which only
    holds if `turnover` is not divided by 2. Implemented that way.
    """
    aligned_returns = returns.reindex(columns=weights.columns).fillna(0.0)
    prior = weights.shift(1).fillna(0.0)
    prior_gross = prior.abs().sum(axis=1)
    drifted = prior.mul(1.0 + aligned_returns)
    drifted_gross = drifted.abs().sum(axis=1)
    scale = (prior_gross / drifted_gross.replace(0.0, np.nan)).fillna(1.0)
    w_drifted = drifted.mul(scale, axis=0)
    return (weights - w_drifted).abs().sum(axis=1)


def volatility_scalar(
    sleeve_ret: pd.Series, target: float, window: int, floor: float, cap: float
) -> pd.Series:
    """clip(target / (rolling_std(sleeve_ret, window) * sqrt(252)), floor, cap),
    shifted by 1 so date t uses only returns through t-1. NaN -> 1.0.
    """
    realised_vol = sleeve_ret.rolling(window).std() * np.sqrt(252)
    scalar = (target / realised_vol).clip(lower=floor, upper=cap)
    return scalar.shift(1).fillna(1.0)


@dataclass(frozen=True)
class Sleeve:
    name: str
    kind: str
    hold_days: int
    weights: pd.DataFrame  # after holding period, gross 1.0 (x-sec) or [0,1] (dir)
    gross_returns: pd.Series  # before cost, at the configured lag
    turnover: pd.Series


def build_sleeves(panel: object, mask: pd.DataFrame, config: ProgrammeConfig) -> dict[str, Sleeve]:
    """Full pipeline: compute_all_signals -> to_weights -> apply_holding_period
    -> sleeve_returns / turnover. Returns {"S1": Sleeve, ...} for all ten,
    using `hold_days` and `kind` from `config.sleeves`.
    """
    signals = compute_all_signals(panel, mask, config.signals)
    returns = panel.returns
    lag = config.execution.signal_to_trade_lag

    sleeves: dict[str, Sleeve] = {}
    for sleeve_cfg in config.sleeves:
        signal = signals[sleeve_cfg.name]
        if sleeve_cfg.kind == "directional":
            raw_weights = directional_to_weights(signal, panel)
        elif sleeve_cfg.kind == "cross_sectional":
            raw_weights = cross_sectional_to_weights(signal, panel)
        else:
            raise ValueError(f"unknown sleeve kind {sleeve_cfg.kind!r} for {sleeve_cfg.name}")

        held_weights = apply_holding_period(raw_weights, sleeve_cfg.hold_days, returns)
        gross_returns = sleeve_returns(held_weights, returns, lag)
        sleeve_turnover = turnover(held_weights, returns)

        sleeves[sleeve_cfg.name] = Sleeve(
            name=sleeve_cfg.name,
            kind=sleeve_cfg.kind,
            hold_days=sleeve_cfg.hold_days,
            weights=held_weights,
            gross_returns=gross_returns,
            turnover=sleeve_turnover,
        )
        logger.info(
            "programme_sleeve_built",
            sleeve=sleeve_cfg.name,
            kind=sleeve_cfg.kind,
            hold_days=sleeve_cfg.hold_days,
            annualised_turnover=float(sleeve_turnover.mean() * 252),
        )

    return sleeves
