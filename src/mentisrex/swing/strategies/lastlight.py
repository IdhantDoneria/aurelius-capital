"""Lastlight -- liquidity provision against mechanical closing-auction flow.

Economic claim
--------------
The closing auction is now the single largest liquidity event of the US
trading day: NYSE reported closing auctions matching $55.5bn per day in
Q2 2024, 9.44% of consolidated notional and a record share. That flow is
overwhelmingly index and ETF flow, which trades at the close because net
asset values are struck there, and which is price-insensitive by mandate.

Price-insensitive size has to be absorbed by someone, and the compensation
for absorbing it is a temporary price concession that unwinds once the flow
stops. Nagel (2012) shows that the return to exactly this kind of liquidity
provision -- proxied by short-horizon reversal -- is strongly predictable by
the VIX, spiking when intermediary capital withdraws. This sleeve is that
trade, aimed at the specific point in the session where the uninformed flow
is largest.

The hard part is separating mechanical pressure from information, because
fading real news is how a reversal book dies. Three filters do that work: no
scheduled report near the date, no news-scale relative volume on the day,
and no large overnight gap. What is left is a run into the close on
concentrated closing volume with no visible reason, which is the signature
of an order that had to be done rather than one that wanted to be done.

Entry is the closing auction of day t, exit is the opening auction of day
t+1. Holding only the overnight leg is deliberate: Lou, Polk and Skouras
find reversal profits accrue overnight, and it keeps the book flat during
the session, so its risk never overlaps an intraday sleeve.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..construction import OverlayConfig, rank_normal
from .base import CrossSectionalStrategy


@dataclass
class LastlightConfig:
    push_source: str = "close_push"
    """Displacement of the closing print from the afternoon VWAP, expressed
    in units of the day's own five-minute volatility."""

    min_close_vol_share: float = 0.06
    """Require the last thirty minutes to carry at least this share of the
    session's volume, i.e. that flow really did concentrate at the close."""

    close_share_weight: float = 0.35
    """Extra weight on names where that concentration is unusually high."""

    max_rvol: float = 3.0
    """Above this day-level relative volume, assume information, not flow."""

    max_gap_z: float = 2.5
    gate_earnings_days: int = 2

    vix_scaling: bool = True
    vix_ref: float = 18.0
    vix_beta: float = 0.5
    """Exposure multiplier = (VIX / vix_ref) ** vix_beta, capped. Nagel's
    result says the expected return to liquidity provision rises with
    volatility, so the book should lean in when it is being paid more."""

    vix_scalar_cap: float = 2.0
    min_price: float = 5.0
    max_amihud_pct: float = 0.70


class Lastlight(CrossSectionalStrategy):
    name = "lastlight"
    trade_at = "moc"

    def __init__(self, *args, config: LastlightConfig | None = None, vix: np.ndarray | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.c = config or LastlightConfig()
        self.vix = vix
        self._push = self.cube[self.c.push_source]
        self._share = self.cube["close_vol_share"]
        self._rvol = self.cube["rvol"]
        self._gapz = self.cube["gap_z"]
        self._earn_near = self.cube["earn_near"]
        self._amihud = self.cube["amihud20"]
        self._px = self.cube["p_close"]

    def _overlay_for(self, t: int) -> OverlayConfig:
        if not self.c.vix_scaling or self.vix is None:
            return self.overlay
        v = float(self.vix[t])
        if not np.isfinite(v) or v <= 0:
            return self.overlay
        k = min((v / self.c.vix_ref) ** self.c.vix_beta, self.c.vix_scalar_cap)
        o = self.overlay
        return OverlayConfig(
            target_vol=o.target_vol * k,
            vol_lookback=o.vol_lookback,
            vol_floor=o.vol_floor,
            max_leverage_scalar=o.max_leverage_scalar,
            gross_cap=o.gross_cap,
            max_weight=o.max_weight,
            beta_neutral=o.beta_neutral,
            dollar_neutral=o.dollar_neutral,
            n_stat_factors=o.n_stat_factors,
            dd_brake_start=o.dd_brake_start,
            dd_brake_full=o.dd_brake_full,
            dd_brake_floor=o.dd_brake_floor,
        )

    def raw_score(self, t: int) -> np.ndarray:
        push = self._push[t]
        share = self._share[t]

        # fade the displacement, weighted up where closing volume concentrated
        score = -rank_normal(push) * (1.0 + self.c.close_share_weight * rank_normal(share))

        keep = (
            np.isfinite(push)
            & np.isfinite(share)
            & (share >= self.c.min_close_vol_share)
            & (np.nan_to_num(self._rvol[t], nan=99.0) <= self.c.max_rvol)
            & (np.abs(np.nan_to_num(self._gapz[t])) <= self.c.max_gap_z)
            & (np.nan_to_num(self._earn_near[t]) <= 0)
            & (self._px[t] >= self.c.min_price)
        )
        am = self._amihud[t]
        fin = np.isfinite(am)
        if fin.sum() > 50:
            keep &= fin & (am <= np.quantile(am[fin], self.c.max_amihud_pct))
        return np.where(keep, score, np.nan)

    def targets_moo(self, t: int) -> np.ndarray:
        """Flat at every open: the sleeve carries only the overnight leg."""
        return np.zeros(self.N)
