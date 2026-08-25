"""Nightfall -- overnight/intraday clientele divergence.

Economic claim
--------------
A US session is two different auctions with two different populations. The
overnight segment (previous close to open) prices news and retail/attention
flow, and is executed at the open where spreads are widest. The intraday
segment (open to close) is where institutional participation algorithms
work, spreading a decision over hours.

Lou, Polk and Skouras (2019) document that firm-level returns continue
*within* each segment and reverse *across* them, and that the profits of a
long list of standard strategies accrue entirely in one segment or the
other, usually with opposite signs. That is a statement that the two
segments carry different information, which means the difference between
them is itself a signal rather than noise.

The hypothesis tested here is directional and stated before the fact: a name
whose recent gains have been earned intraday while its overnight tape has
been soft is under quiet institutional accumulation that has not yet shown
up in headline close-to-close momentum, and should outperform. The reverse
-- gains earned overnight while the intraday tape leaks -- is distribution
into attention, and should underperform.

Both components are scaled by their own volatilities before differencing.
Overnight and intraday returns have materially different variances, so a raw
difference would be an overnight signal wearing a spread's clothing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..construction import cross_sectional_z, rank_normal
from .base import CrossSectionalStrategy


@dataclass
class NightfallConfig:
    lookback: str = "10"
    """Which accumulation window to difference: 5, 10, 21 or 63 sessions."""

    sign: int = +1
    """+1 = long intraday-strong / overnight-weak. The sign is a stated
    hypothesis, not a fitted parameter; -1 exists so the opposite can be
    reported side by side."""

    persistence_weight: float = 0.25
    """Weight on the fraction of recent sessions with a positive intraday
    leg. Rewards a steady drift over one large day."""

    reversal_weight: float = 0.0
    """Optional tilt on the most recent session's close-to-close return, to
    let the sleeve carry a short-horizon reversal component."""

    gate_earnings_days: int = 3
    """Suppress names within this many sessions of a scheduled report: an
    earnings gap contaminates the overnight leg with information rather than
    clientele flow."""

    gate_gap_z: float = 3.0
    """Suppress names whose latest overnight gap exceeded this many
    standard deviations, for the same reason but for unscheduled news."""

    min_price: float = 5.0
    max_amihud_pct: float = 0.80
    """Drop the least liquid tail of the eligible universe."""


class Nightfall(CrossSectionalStrategy):
    name = "nightfall"
    trade_at = "moc"

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

    def raw_score(self, t: int) -> np.ndarray:
        rt = np.sqrt(self._n)
        on = self._son[t] / np.maximum(self._sd_on[t] * rt, 1e-6)
        idr = self._sid[t] / np.maximum(self._sd_id[t] * rt, 1e-6)

        divergence = rank_normal(idr) - rank_normal(on)
        persistence = cross_sectional_z(self._idup[t] - 0.5)
        score = self.c.sign * (divergence + self.c.persistence_weight * persistence)

        if self.c.reversal_weight:
            score = score - self.c.reversal_weight * rank_normal(self._retcc[t])

        keep = (
            np.isfinite(score)
            & (self._px[t] >= self.c.min_price)
            & (np.abs(np.nan_to_num(self._gapz[t])) <= self.c.gate_gap_z)
            & (np.nan_to_num(self._earn_near[t]) <= 0)
        )
        am = self._amihud[t]
        fin = np.isfinite(am)
        if fin.sum() > 50:
            cut = np.quantile(am[fin], self.c.max_amihud_pct)
            keep &= fin & (am <= cut)
        return np.where(keep, score, np.nan)
