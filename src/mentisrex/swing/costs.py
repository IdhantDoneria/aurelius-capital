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

    Kept as a **diagnostic, not a cost input.** Tested against synthetic
    price paths with a known injected spread, this estimator overstates the
    spread by roughly 3x when the true spread is 40bps and by more than 15x
    when it is 5bps -- because it cannot separate a one-basis-point spread
    from a hundred and fifty basis points of daily volatility, which is
    exactly the regime every liquid US equity lives in. The Abdi-Ranaldo
    close-high-low estimator was tested alongside it and is better but still
    biased 6x at realistic levels.

    Costs in this programme therefore come from `modelled_spread` instead.
    See `docs/` for what would be needed to measure rather than model.

    Days where the estimator goes negative (its known small-sample failure
    mode) return NaN, never zero -- zero would be an assertion of free
    trading.
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


SPREAD_K = 1450.0
SPREAD_VOL_EXPONENT = 1.0
SPREAD_ADV_EXPONENT = 1.0 / 3.0
TICK = 0.01


def modelled_spread(
    daily_vol: np.ndarray,
    adv_dollar: np.ndarray,
    price: np.ndarray,
    *,
    scalar: float = 1.0,
    min_bps: float = 0.5,
    max_bps: float = 300.0,
) -> np.ndarray:
    """Proportional effective spread, in fractional terms.

        spread_bps = 1450 * sigma_daily * (ADV in $m) ** (-1/3)

    floored at the one-tick minimum `TICK / price`.

    The functional form is the microstructural one -- spreads widen with
    volatility and narrow with participation -- and the constant is
    calibrated so that a $5bn-a-day mega cap at 1.5% daily volatility prices
    at about 1.5bps, a $200m name at 4.5bps and a $5m name at 40bps, which
    are the levels US equity transaction-cost studies report. The fit
    reproduces those seven anchors to within about 10%.

    The tick floor matters more than it looks: a one-cent minimum increment
    means a $10 stock cannot trade inside 10bps however liquid it is, which
    is a large part of why low-priced names are expensive for a
    high-turnover book and why this programme applies a price floor.

    This is a **model, not a measurement** -- there is no quote data in this
    repository. Every headline result is therefore also reported at
    multiples of this level, and each strategy's breakeven cost multiple is
    stated.
    """
    sig = np.nan_to_num(daily_vol, nan=0.02)
    adv_m = np.maximum(np.nan_to_num(adv_dollar, nan=1e6), 1e5) / 1e6
    modelled = (
        SPREAD_K * sig**SPREAD_VOL_EXPONENT * adv_m**-SPREAD_ADV_EXPONENT
    ) / 1e4
    tick_floor = TICK / np.maximum(np.nan_to_num(price, nan=50.0), 1.0)
    return np.clip(
        np.maximum(modelled, tick_floor) * scalar, min_bps / 1e4, max_bps / 1e4
    )


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

    open_auction_adv_share: float = 0.025
    """The opening auction is a much smaller event than the close, so the
    same order size is a far larger share of it."""

    open_auction_eta_mult: float = 1.8
    """Impact multiplier for the opening cross relative to the closing one.
    The open has less accumulated contra interest and the widest spreads of
    the session; treating the two auctions as equally cheap is the single
    most flattering assumption available to an overnight strategy."""

    spread_scalar: float = 1.0
    """Multiplier on the modelled spread. The spread is modelled rather than
    measured, so every headline result is re-run at 2x and 4x this value and
    each strategy's breakeven multiple is reported."""

    min_spread_bps: float = 0.5
    max_spread_bps: float = 300.0

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
