"""Transaction-cost, financing and borrow models for the swing programme.

Three design choices worth stating up front, because each one changes the
answer to "is this strategy tradable" by more than the signal does.

**Fees are per share, not per basis point.** US equity commissions and
exchange fees are charged per share, so the same notional costs five times
as much in a $15 stock as in a $75 one. At the turnover a daily-flattening
book runs, that difference is whole percentage points of annual return.

**Impact is measured against daily volume, and does not extrapolate below
the range it was fitted on.** The square-root law is an empirical fit to
institutional metaorders of roughly 0.1% to 10% of volume. Applied literally
at 0.02% it claims a $22k order in a mega-cap moves the price more than a
basis point, which is false; below the fitted range the linear Kyle regime
is the right limit.

**The spread is modelled, not measured.** There is no quote data in this
repository. High-low estimators were tested against synthetic paths with a
known injected spread and are biased upward by 3x to 20x at realistic
levels, so they are kept as diagnostics only. Every headline result is
therefore re-run at multiples of the modelled level, and each strategy's
breakeven multiple is reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_CS_K = 3.0 - 2.0 * np.sqrt(2.0)

SPREAD_K = 1450.0
SPREAD_VOL_EXPONENT = 1.0
SPREAD_ADV_EXPONENT = 1.0 / 3.0
TICK = 0.01


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    """Proportional effective spread from two-day high/low ranges.

    Kept as a **diagnostic, not a cost input.** Tested against synthetic
    price paths with a known injected spread, this estimator overstates by
    roughly 3x when the true spread is 40bps and by more than 15x when it is
    5bps -- because it cannot separate a one-basis-point spread from a
    hundred and fifty basis points of daily volatility, which is exactly the
    regime every liquid US equity lives in. The Abdi-Ranaldo close-high-low
    estimator was tested alongside it and is better but still biased about
    6x at realistic levels.

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


def modelled_spread(
    daily_vol: np.ndarray,
    adv_dollar: np.ndarray,
    price: np.ndarray,
    *,
    scalar: float = 1.0,
    min_bps: float = 0.5,
    max_bps: float = 300.0,
) -> np.ndarray:
    """Proportional effective spread, as a fraction of price.

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
    is much of why low-priced names are expensive for a high-turnover book.
    """
    sig = np.nan_to_num(daily_vol, nan=0.02)
    adv_m = np.maximum(np.nan_to_num(adv_dollar, nan=1e6), 1e5) / 1e6
    modelled = (SPREAD_K * sig**SPREAD_VOL_EXPONENT * adv_m**-SPREAD_ADV_EXPONENT) / 1e4
    tick_floor = TICK / np.maximum(np.nan_to_num(price, nan=50.0), 1.0)
    return np.clip(
        np.maximum(modelled, tick_floor) * scalar, min_bps / 1e4, max_bps / 1e4
    )


@dataclass(frozen=True)
class CostConfig:
    """All friction parameters in one place, so they can be swept."""

    commission_cps: float = 0.10
    """Broker commission in **cents per share**, one way. At $0.0010 a share
    a $75 stock pays 0.13bps and a $15 stock pays 0.67bps for the same
    notional."""

    auction_fee_cps: float = 0.10
    """Exchange fee for closing/opening auction participation, cents per
    share, one way."""

    sec_fee_bps: float = 0.25
    """SEC Section 31 fee, charged on **sales only**, in bps of notional."""

    taf_cps: float = 0.0166
    """FINRA Trading Activity Fee, cents per share, sales only."""

    sell_share_of_turnover: float = 0.5
    """Fraction of traded notional that is sales. The simulator nets each
    name to one signed delta per venue rather than tracking buys and sells
    separately, so sell-side statutory fees are applied at this weight. Over
    any closed round trip the true fraction is exactly one half."""

    spread_capture: float = 0.5
    """Fraction of the quoted spread paid when crossing (0.5 = the half
    spread; above that models being the impatient side of a wide book)."""

    spread_scalar: float = 1.0
    """Multiplier on the modelled spread, for sensitivity analysis."""

    min_spread_bps: float = 0.5
    max_spread_bps: float = 300.0

    impact_eta_continuous: float = 0.50
    """Square-root coefficient for continuous intraday execution, calibrated
    so that 1% of daily volume in a 2%-a-day name costs about 10bps."""

    impact_eta_auction: float = 0.40
    """Coefficient for the closing cross -- below the continuous figure
    because the auction clears at one price against accumulated index contra
    interest rather than walking the book."""

    open_auction_eta_mult: float = 2.0
    """Impact multiplier for the opening cross relative to the closing one.
    The open is a far smaller event with none of the close's index contra
    flow and the widest spreads of the session. Treating the two auctions as
    equally cheap is the single most flattering assumption available to an
    overnight strategy, so this is set deliberately punitive and swept."""

    impact_linear_below: float = 0.001
    """Participation below which impact is linear rather than square-root.

    The square-root law is fitted to metaorders of 0.1%-10% of volume; it is
    not a law of nature and it does not extrapolate downward. Applied
    literally it says a $22k order in a $100m-a-day stock moves the price
    1.2bps, which is not what such an order does. Below the fitted range the
    linear Kyle-lambda limit applies, matched to the square root here.

    This parameter materially decides whether a high-turnover, small-order
    book is viable, so results are always reported across a sweep of it."""

    auction_adv_share: float = 0.10
    """Closing auction as a share of consolidated volume -- NYSE reported
    9.44% of US notional in Q2 2024. Used for capacity analysis; deliberately
    *not* the denominator of the impact term."""

    borrow_gc_bps: float = 40.0
    """General-collateral annual borrow fee, in bps, for liquid names."""

    borrow_htb_bps: float = 300.0
    """Annual borrow fee for the least-liquid tradable quintile."""

    margin_spread_bps: float = 50.0
    """Spread over the overnight rate charged on financed gross exposure."""

    rebate_haircut_bps: float = 15.0
    """Shortfall of the short rebate versus the overnight rate."""


def fee_rate(price: np.ndarray, cfg: CostConfig, *, auction: bool) -> np.ndarray:
    """Commission, exchange and statutory fees as a fraction of notional."""
    cps = cfg.commission_cps + (cfg.auction_fee_cps if auction else 0.0)
    cps += cfg.sell_share_of_turnover * cfg.taf_cps
    px = np.maximum(np.nan_to_num(np.asarray(price, dtype=float), nan=50.0), 1.0)
    return (cps / 100.0) / px + cfg.sell_share_of_turnover * cfg.sec_fee_bps / 1e4


def spread_cost(spread_frac: np.ndarray, cfg: CostConfig, *, auction: bool) -> np.ndarray:
    """Proportional cost of crossing, per unit of notional traded.

    An auction fill crosses no spread: the whole book clears at one price.
    """
    if auction:
        return np.zeros_like(np.asarray(spread_frac, dtype=float))
    s = np.clip(spread_frac, cfg.min_spread_bps / 1e4, cfg.max_spread_bps / 1e4)
    return cfg.spread_capture * s


def impact_cost(
    notional: np.ndarray,
    adv_dollar: np.ndarray,
    daily_vol: np.ndarray,
    cfg: CostConfig,
    *,
    auction: bool,
    eta: float | None = None,
) -> np.ndarray:
    """Market impact per unit of notional traded.

        p = order / daily dollar volume

        impact = eta * sigma * sqrt(p)                  for p >= p0
        impact = eta * sigma * sqrt(p0) * (p / p0)      for p <  p0

    Participation is measured against the name's **daily** volume for every
    venue, and the venue enters only through `eta`. Dividing instead by the
    venue's own share of volume -- an order is 7% of the closing auction but
    0.17% of the day -- while keeping a *daily* volatility scale mixes two
    horizons and inflates auction impact by about an order of magnitude.
    """
    if eta is None:
        eta = cfg.impact_eta_auction if auction else cfg.impact_eta_continuous
    q = np.abs(np.asarray(notional, dtype=float))
    part = np.divide(
        q,
        np.maximum(np.nan_to_num(np.asarray(adv_dollar, dtype=float), nan=0.0), 1.0),
        out=np.zeros_like(q),
        where=True,
    )
    part = np.clip(part, 0.0, 1.0)
    p0 = max(cfg.impact_linear_below, 1e-12)
    shape = np.where(part >= p0, np.sqrt(part), np.sqrt(p0) * (part / p0))
    return eta * np.nan_to_num(np.asarray(daily_vol, dtype=float)) * shape


def round_trip_bps(
    spread_frac: float,
    participation: float,
    daily_vol: float,
    cfg: CostConfig,
    *,
    auction: bool,
    price: float = 75.0,
) -> float:
    """Total round-trip friction in bps for a single name."""
    one_way = (
        float(fee_rate(np.array([price]), cfg, auction=auction)[0])
        + float(spread_cost(np.array([spread_frac]), cfg, auction=auction)[0])
        + float(
            impact_cost(
                np.array([participation]), np.array([1.0]), np.array([daily_vol]),
                cfg, auction=auction,
            )[0]
        )
    )
    return 2.0 * one_way * 1e4


@dataclass
class FinancingModel:
    """Daily financing on a levered long/short book.

    Charges margin interest on the gross above one times equity, a borrow fee
    on short notional, and credits a short rebate on short proceeds. The
    overnight rate is a supplied series so that the 2016-2021 zero-rate era
    and the 2022-2026 high-rate era are treated differently -- a fixed rate
    would misprice a levered book by several hundred basis points a year
    across this sample.
    """

    cfg: CostConfig
    overnight_rate: pd.Series = field(repr=False)
    """Annualised decimal overnight rate indexed by date."""

    def daily_charge(
        self,
        date: pd.Timestamp,
        equity: float,
        long_notional: float,
        short_notional: float,
        htb_short_notional: float = 0.0,
    ) -> float:
        """Currency cost of carrying the book overnight from `date`."""
        r = float(self.overnight_rate.asof(date))
        if not np.isfinite(r):
            r = 0.0
        gross = long_notional + short_notional
        financed = max(gross - max(equity, 0.0), 0.0)
        margin = financed * (r + self.cfg.margin_spread_bps / 1e4) / 360.0

        gc = max(short_notional - htb_short_notional, 0.0)
        borrow = (
            gc * self.cfg.borrow_gc_bps / 1e4
            + htb_short_notional * self.cfg.borrow_htb_bps / 1e4
        ) / 360.0
        rebate = short_notional * max(r - self.cfg.rebate_haircut_bps / 1e4, 0.0) / 360.0
        return margin + borrow - rebate
