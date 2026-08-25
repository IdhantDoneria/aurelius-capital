"""Segment-aware backtester.

The unit of simulation is a *segment*, not a day. Each session is split into
an overnight leg (previous close to open) and an intraday leg (open to
close), with a trading opportunity in the opening auction and another in the
closing auction. That split is the whole point: the three strategies under
test hold across different segments, and a close-to-close simulator cannot
tell them apart.

Ordering within day t:
    1. mark the book through the overnight leg
    2. optional opening-auction trade
    3. mark the book through the intraday leg
    4. optional closing-auction trade  (signals were fixed at 15:45)
    5. charge financing on whatever is carried overnight
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import numpy as np
import pandas as pd

from .costs import CostConfig, FinancingModel, fee_rate, impact_cost, spread_cost


@dataclass
class MarketPanel:
    """Wide (T, N) arrays. NaN means the name did not trade that session."""

    dates: pd.DatetimeIndex
    symbols: np.ndarray
    open_: np.ndarray
    close: np.ndarray
    prev_close: np.ndarray
    adv: np.ndarray
    spread: np.ndarray
    daily_vol: np.ndarray
    tradable: np.ndarray
    htb: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.close.shape

    def ret_on(self, t: int) -> np.ndarray:
        r = self.open_[t] / self.prev_close[t] - 1.0
        return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)

    def ret_id(self, t: int) -> np.ndarray:
        r = self.close[t] / self.open_[t] - 1.0
        return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)


class Strategy(Protocol):
    name: str

    def warmup(self) -> int: ...
    def targets_moc(self, t: int) -> np.ndarray | None: ...
    def targets_moo(self, t: int) -> np.ndarray | None: ...


class Venue(str, Enum):
    """Where an order is worked.

    The three venues differ in what fraction of the day's volume they give
    access to and in whether they cross a spread, and those differences are
    resolved from `CostConfig` rather than hardcoded here -- a second copy of
    the cost parameters would silently override every cost sensitivity sweep.
    """

    CLOSE_AUCTION = "close_auction"
    OPEN_AUCTION = "open_auction"
    CONTINUOUS = "continuous"


@dataclass(frozen=True)
class VenueParams:
    eta: float
    is_auction: bool
    crosses_spread: bool


def resolve_venue(venue: Venue, cfg: CostConfig) -> VenueParams:
    if venue is Venue.CLOSE_AUCTION:
        return VenueParams(cfg.impact_eta_auction, True, False)
    if venue is Venue.OPEN_AUCTION:
        return VenueParams(cfg.impact_eta_auction * cfg.open_auction_eta_mult, True, False)
    return VenueParams(cfg.impact_eta_continuous, False, True)


@dataclass
class BacktestConfig:
    initial_equity: float = 100_000_000.0
    costs: CostConfig = field(default_factory=CostConfig)
    delist_haircut: float = 0.0
    """Extra loss applied when a position is force-closed because the name
    stopped trading. Zero is the default because the true delisting return is
    not observable in this data set; a negative value is used in the
    robustness sweep to price the bankruptcy tail."""


class SegmentBacktester:
    def __init__(self, panel: MarketPanel, financing: FinancingModel, cfg: BacktestConfig):
        self.p = panel
        self.fin = financing
        self.cfg = cfg
        self.T, self.N = panel.shape

    def _trade(
        self,
        pos: np.ndarray,
        target_notional: np.ndarray,
        t: int,
        venue: Venue,
    ) -> tuple[np.ndarray, float, float]:
        """Move the book to `target_notional`; return (new pos, cost, traded)."""
        delta = target_notional - pos
        delta = np.where(self.p.tradable[t], delta, 0.0)
        traded = float(np.abs(delta).sum())
        if traded <= 0:
            return pos, 0.0, 0.0

        c = self.cfg.costs
        v = resolve_venue(venue, c)
        sp = spread_cost(self.p.spread[t], c, auction=not v.crosses_spread)
        imp = impact_cost(
            delta, self.p.adv[t], self.p.daily_vol[t], c,
            auction=v.is_auction, eta=v.eta,
        )
        rate = fee_rate(self.p.close[t], c, auction=v.is_auction) + sp + imp
        cost = float((np.abs(delta) * rate).sum())
        return pos + delta, cost, traded

    def run(self, strategy: Strategy) -> pd.DataFrame:
        p, cfg = self.p, self.cfg
        equity = cfg.initial_equity
        pos = np.zeros(self.N)
        rows: list[dict] = []
        peak = equity
        warm = strategy.warmup()

        for t in range(self.T):
            date = p.dates[t]

            # --- 1. overnight leg -------------------------------------------------
            pnl_on = float((pos * p.ret_on(t)).sum())
            pos = pos * (1.0 + p.ret_on(t))
            equity += pnl_on

            # names that stopped trading are force-closed at the last known mark
            gone = (~p.tradable[t]) & (pos != 0.0)
            delist_loss = 0.0
            if gone.any():
                delist_loss = float((pos[gone] * cfg.delist_haircut).sum())
                equity += delist_loss
                pos = np.where(gone, 0.0, pos)

            cost_moo = traded_moo = 0.0
            if t >= warm:
                tgt = strategy.targets_moo(t)
                if tgt is not None:
                    pos, cost_moo, traded_moo = self._trade(pos, tgt * equity, t, Venue.OPEN_AUCTION)
                    equity -= cost_moo

            # --- 3. intraday leg --------------------------------------------------
            pnl_id = float((pos * p.ret_id(t)).sum())
            pos = pos * (1.0 + p.ret_id(t))
            equity += pnl_id

            cost_moc = traded_moc = 0.0
            if t >= warm:
                tgt = strategy.targets_moc(t)
                if tgt is not None:
                    pos, cost_moc, traded_moc = self._trade(pos, tgt * equity, t, Venue.CLOSE_AUCTION)
                    equity -= cost_moc

            # --- 5. financing on the carried book ---------------------------------
            longs = float(pos[pos > 0].sum())
            shorts = float(-pos[pos < 0].sum())
            htb_short = float(-pos[(pos < 0) & p.htb[t]].sum())
            fin = self.fin.daily_charge(date, equity, longs, shorts, htb_short)
            equity -= fin

            peak = max(peak, equity)
            observe = getattr(strategy, "observe", None)
            if observe is not None:
                observe(equity / peak - 1.0)
            rows.append(
                {
                    "date": date,
                    "equity": equity,
                    "pnl_overnight": pnl_on,
                    "pnl_intraday": pnl_id,
                    "cost": cost_moo + cost_moc,
                    "pnl_gross": pnl_on + pnl_id,
                    "financing": fin,
                    "delist_loss": delist_loss,
                    "traded": traded_moo + traded_moc,
                    "gross": (longs + shorts) / max(equity, 1e-9),
                    "net": (longs - shorts) / max(equity, 1e-9),
                    "n_pos": int((pos != 0).sum()),
                    "drawdown": equity / peak - 1.0,
                }
            )

            if equity <= 0:
                break

        out = pd.DataFrame(rows).set_index("date")
        out["ret"] = out["equity"].pct_change().fillna(
            out["equity"].iloc[0] / cfg.initial_equity - 1.0
        )
        out["turnover"] = out["traded"] / out["equity"].shift(1).fillna(cfg.initial_equity)
        out["cost_bps"] = out["cost"] / out["equity"].shift(1).fillna(cfg.initial_equity) * 1e4
        return out
