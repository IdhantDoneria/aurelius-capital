"""Nightfall -- harvesting the overnight/intraday tug of war.

Economic claim
--------------
A US session is two auctions with two populations. The overnight segment
(previous close to open) prices news and retail/attention flow and is
executed at the open, where spreads are widest. The intraday segment (open
to close) is where institutional participation algorithms work, spreading a
decision across hours.

Lou, Polk and Skouras (2019) document that firm-level returns continue
*within* each segment and reverse *across* them. Measured on this firm's own
data over 2017-2026 on the top-500 US names by dollar volume, that is
exactly what appears -- and the cross-period effect is much the larger one:

    signal: 10-day divergence = z(sum intraday) - z(sum overnight)
        -> forward overnight return, 5d :  IC -2.91%,  t = -9.8
        -> forward intraday  return, 5d :  IC +1.58%,  t = +5.8
        -> forward close-to-close,   5d :  IC -0.06%,  t = -0.2

The third line is the important one. A name whose recent gains came intraday
while its overnight tape lagged gives almost all of that back overnight, and
keeps drifting up intraday, and the two cancel almost exactly in
close-to-close terms. **A close-to-close strategy on this signal earns
nothing, however good the signal is.** The effect is real, large and
significant, and it is invisible to any backtest that marks positions from
one close to the next.

So the sleeve trades the segments separately: short the high-divergence names
across the overnight gap, long them across the session. `mode` selects
whether to run one leg or both. The dual-leg version doubles turnover -- it
flips its whole book twice a day -- which makes the cost model, not the
signal, the thing that decides whether it is tradable.

Both components are scaled by their own volatilities before differencing.
Overnight and intraday returns have materially different variances, so a raw
difference would be an overnight signal wearing a spread's clothing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..construction import cross_sectional_z, rank_normal, select_tails
from .base import CrossSectionalStrategy


@dataclass
class NightfallConfig:
    lookback: str = "10"
    """Accumulation window to difference: 5, 10, 21 or 63 sessions."""

    mode: str = "overnight"
    """`overnight` holds only across the gap, `intraday` only across the
    session, `dual` runs both legs with opposite signs."""

    overnight_sign: int = -1
    """Short high-divergence names overnight. The sign is read off the
    measured cross-period reversal, and is stated rather than searched."""

    intraday_sign: int = +1

    persistence_weight: float = 0.25
    """Weight on the fraction of recent sessions with a positive intraday
    leg -- rewards a steady drift over one large day."""

    reversal_weight: float = 0.0
    """Optional tilt on the latest close-to-close return, to let the sleeve
    carry a short-horizon reversal component."""

    gate_gap_z: float = 3.0
    """Suppress names whose latest overnight gap exceeded this many standard
    deviations: an information gap contaminates the decomposition."""

    gate_earnings: bool = True
    min_price: float = 5.0
    max_amihud_pct: float = 0.80

    tail_pct: float = 1.0
    """Fraction of the cross-section actually traded, split between the two
    tails. Below one the book concentrates on conviction, which raises the
    edge per name and the impact per name at the same time."""

    min_dispersion_pct: float = 0.0
    """Trade only on days whose cross-sectional signal dispersion is above
    this trailing percentile. Turnover is the binding constraint on this
    sleeve, so skipping low-information days is the most direct lever on the
    ratio of edge to cost."""


class Nightfall(CrossSectionalStrategy):
    name = "nightfall"

    def __init__(self, *args, config: NightfallConfig | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.c = config or NightfallConfig()
        lb = self.c.lookback
        self._son = self.cube[f"son{lb}"]
        self._sid = self.cube[f"sid{lb}"]
        self._n = float(lb)
        self._sd_on = self.cube["sd_on60"]
        self._sd_id = self.cube["sd_id60"]
        self._idup = self.cube["idup10"]
        self._gapz = self.cube["gap_z"]
        self._earn_near = self.cube["earn_near"]
        self._amihud = self.cube["amihud20"]
        self._px = self.cube["p_close"]
        self._retcc = self.cube["ret_cc"]
        self.overnight_only = self.c.mode == "overnight"
        self._disp_history: list[float] = []

    def raw_score(self, t: int) -> np.ndarray:
        rt = np.sqrt(self._n)
        on = self._son[t] / np.maximum(self._sd_on[t] * rt, 1e-6)
        idr = self._sid[t] / np.maximum(self._sd_id[t] * rt, 1e-6)

        divergence = rank_normal(idr) - rank_normal(on)
        persistence = cross_sectional_z(self._idup[t] - 0.5)
        score = divergence + self.c.persistence_weight * persistence
        if self.c.reversal_weight:
            score = score - self.c.reversal_weight * rank_normal(self._retcc[t])

        keep = (
            np.isfinite(score)
            & (self._px[t] >= self.c.min_price)
            & (np.abs(np.nan_to_num(self._gapz[t])) <= self.c.gate_gap_z)
        )
        if self.c.gate_earnings:
            keep &= np.nan_to_num(self._earn_near[t]) <= 0
        am = self._amihud[t]
        fin = np.isfinite(am)
        if fin.sum() > 50:
            keep &= fin & (am <= np.quantile(am[fin], self.c.max_amihud_pct))
        out = np.where(keep, score, np.nan)

        if self.c.min_dispersion_pct > 0.0:
            live = out[np.isfinite(out)]
            disp = float(live.std(ddof=1)) if live.size > 20 else 0.0
            self._disp_history.append(disp)
            if len(self._disp_history) > 260:
                self._disp_history.pop(0)
            if len(self._disp_history) >= 120:
                # trailing percentile, computed on history strictly before today
                cut = float(np.quantile(self._disp_history[:-1], self.c.min_dispersion_pct))
                if disp < cut:
                    return np.full_like(out, np.nan)

        return select_tails(out, self.c.tail_pct)

    # -- segment-specific books ---------------------------------------------
    def targets_moc(self, t: int) -> np.ndarray | None:
        """The book carried across tonight's gap."""
        if self.c.mode not in ("overnight", "dual"):
            return np.zeros(self.N) if self.c.mode == "intraday" else None
        return self.c.overnight_sign * self._target(t)

    def targets_moo(self, t: int) -> np.ndarray | None:
        """The book carried across today's session.

        Scored on day t-1, because at the opening auction of day t that is
        the most recent complete session.
        """
        if self.c.mode == "overnight":
            return np.zeros(self.N)
        if t < 1:
            return np.zeros(self.N)
        return self.c.intraday_sign * self._target(t - 1)
