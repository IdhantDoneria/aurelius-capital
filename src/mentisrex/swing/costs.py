"""Transaction-cost, financing and borrow models for the swing programme.

Two design choices worth stating up front.

First, the spread is *estimated from the data*, per name and per day, using
the Corwin-Schultz (2012) high-low estimator, rather than assumed as a flat
bps figure. A flat assumption is what makes short-horizon backtests lie: the
names a short-horizon signal likes are disproportionately the volatile,
wider-spread ones, so a constant spread systematically flatters exactly the
trades that would have cost the most.

Second, execution venue is modelled explicitly. Trading in the closing
auction does not cross a spread, but it concentrates the whole order into
roughly a tenth of the day's volume, so its impact term uses a much smaller
effective ADV. Trading continuously intraday crosses the spread but spreads
the order over a window. These are different cost functions and the
strategies below use different ones.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_CS_K = 3.0 - 2.0 * np.sqrt(2.0)


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    """Proportional effective spread from two-day high/low ranges.

    Returns a per-day series aligned to `high.index`. Days where the
    estimator goes negative (its known small-sample failure mode) are set to
    NaN, to be filled by the caller's rolling median rather than to zero --
    zero would be an assertion of free trading.
    """
    h, l = high.astype(float), low.astype(float)
    hl = np.log(h / l) ** 2
    beta = hl + hl.shift(1)
    h2 = pd.concat([h, h.shift(1)], axis=1).max(axis=1)
    l2 = pd.concat([l, l.shift(1)], axis=1).min(axis=1)
    gamma = np.log(h2 / l2) ** 2

    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / _CS_K - np.sqrt(gamma / _CS_K)
    s = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    return s.where(s > 0)


@dataclass(frozen=True)
class CostConfig:
    """All friction parameters in one place so they can be swept."""

    commission_bps: float = 0.20
    """Broker commission + exchange/regulatory fees, one way, in bps."""

    auction_fee_bps: float = 0.50
    """Additional per-side fee for closing-auction participation."""

    spread_capture: float = 0.5
    """Fraction of the quoted spread paid when crossing (0.5 = pay the half
    spread; >0.5 models being the impatient side in a wide book)."""

    impact_eta_continuous: float = 0.60
    """Square-root-law coefficient for continuous intraday execution."""

    impact_eta_auction: float = 0.30
    """Square-root-law coefficient for a batch auction cross. Lower than the
    continuous coefficient because the auction is a single clearing price
    against accumulated contra interest rather than a walk up the book."""

    auction_adv_share: float = 0.10
    """Closing auction as a share of consolidated volume. NYSE reported
    9.44% of US notional in Q2 2024; 10% is used here."""

    min_spread_bps: float = 1.0
    max_spread_bps: float = 200.0

    borrow_gc_bps: float = 40.0
    """General-collateral annual borrow fee, in bps, for liquid names."""

    borrow_htb_bps: float = 300.0
    """Annual borrow fee applied to the least-liquid tradable quintile."""

    margin_spread_bps: float = 50.0
    """Spread over the overnight rate charged on financed gross exposure."""

    rebate_haircut_bps: float = 15.0
    """Shortfall of the short rebate versus the overnight rate."""


def spread_cost(
    spread_frac: np.ndarray, cfg: CostConfig, *, auction: bool
) -> np.ndarray:
    """Proportional cost of crossing, per unit of notional traded."""
    if auction:
        return np.zeros_like(spread_frac)
    s = np.clip(spread_frac, cfg.min_spread_bps / 1e4, cfg.max_spread_bps / 1e4)
    return cfg.spread_capture * s


def impact_cost(
    notional: np.ndarray,
    adv_dollar: np.ndarray,
    daily_vol: np.ndarray,
    cfg: CostConfig,
    *,
    auction: bool,
) -> np.ndarray:
    """Square-root market impact, per unit of notional traded.

    impact = eta * sigma_daily * sqrt(participation)

    where participation is the order divided by the dollar volume actually
    available in the chosen execution venue.
    """
    eta = cfg.impact_eta_auction if auction else cfg.impact_eta_continuous
    avail = adv_dollar * (cfg.auction_adv_share if auction else 1.0)
    part = np.divide(
        np.abs(notional), np.maximum(avail, 1.0), out=np.zeros_like(notional), where=True
    )
    return eta * np.nan_to_num(daily_vol) * np.sqrt(np.clip(part, 0.0, 1.0))


def round_trip_bps(
    spread_frac: float, participation: float, daily_vol: float, cfg: CostConfig, *, auction: bool
) -> float:
    """Convenience: total round-trip friction in bps for a single name."""
    eta = cfg.impact_eta_auction if auction else cfg.impact_eta_continuous
    fee = cfg.commission_bps + (cfg.auction_fee_bps if auction else 0.0)
    one_way = (
        fee / 1e4
        + (0.0 if auction else cfg.spread_capture * spread_frac)
        + eta * daily_vol * np.sqrt(participation)
    )
    return 2.0 * one_way * 1e4


@dataclass
class FinancingModel:
    """Daily financing on a levered long/short book.

    Charges margin interest on the gross above one times equity, a borrow fee
    on short notional, and credits a short rebate on short proceeds. The
    overnight rate is a supplied series so that the 2016-2021 zero-rate era
    and the 2022-2026 high-rate era are treated differently -- a fixed rate
    assumption would misprice a levered book by several hundred basis points
    a year across this sample.
    """

    cfg: CostConfig
    overnight_rate: pd.Series = field(repr=False)
    """Annualised decimal overnight rate indexed by date."""

    def daily_charge(
        self, date: pd.Timestamp, equity: float, long_notional: float, short_notional: float,
        htb_short_notional: float = 0.0,
    ) -> float:
        """Currency cost for carrying the book overnight from `date`."""
        r = float(self.overnight_rate.asof(date))
        if not np.isfinite(r):
            r = 0.0
        gross = long_notional + short_notional
        financed = max(gross - max(equity, 0.0), 0.0)
        margin = financed * (r + self.cfg.margin_spread_bps / 1e4) / 360.0

        gc = max(short_notional - htb_short_notional, 0.0)
        borrow = (
            gc * self.cfg.borrow_gc_bps / 1e4 + htb_short_notional * self.cfg.borrow_htb_bps / 1e4
        ) / 360.0
        rebate = short_notional * max(r - self.cfg.rebate_haircut_bps / 1e4, 0.0) / 360.0
        return margin + borrow - rebate
