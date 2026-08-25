"""Dayburn -- intraday trend participation in high-attention names.

Economic claim
--------------
Information does not arrive in a market and get priced instantly; it gets
priced over hours, by participants with different mandates, attention and
execution constraints. Gao, Han, Li and Zhou (2018) show the first
half-hour's move on the S&P 500 predicts the last half-hour's, more strongly
on volatile days, high-volume days and macro-release days -- exactly the days
on which information is being processed. Bogousslavsky's infrequent-
rebalancing model gives the mechanism: participants who cannot trade
continuously arrive late and push in the same direction.

That effect is a *conditional* one. It lives in names that are being
repriced, not in the average name on the average day, so the sleeve first
identifies the names in play -- those with abnormal pre-market volume and an
abnormal opening gap -- and only trades those.

The entry threshold is a volatility cone rather than a fixed percentage. The
US session's volatility is strongly U-shaped, so a move that is remarkable
at 13:00 is unremarkable at 09:45, and a constant threshold silently makes
the strategy a different strategy at different times of day. The cone is
built as (the name's own trailing daily volatility) x (a universe-wide
time-of-day shape estimated on a trailing window), which is both cheaper and
a lower-variance estimator than fitting a cone per name.

Risk is managed by a stop at the opposite side of the opening range, a
trailing exit at session VWAP, and a hard flat at 15:50. The expected shape
of the return distribution is a hit rate well under half with a large
average winner: that convexity is the point, and a version of this strategy
with a high hit rate would be one that had quietly removed its stops.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..costs import CostConfig
from ..intraday_sim import BARS_PER_SESSION, RTH_CLOSE, RTH_OPEN, IntradayRules


ENTRY_ANCHOR_MOD = 10 * 60 - 15
"""Bar whose close is the 10:00 ET price -- the point at which the opening
range is complete and the sleeve may first act."""

MIN_SESSION_BARS = max(BARS_PER_SESSION * 3 // 4, 4)
"""Minimum bars for a session to be tradable, derived from the bar interval
rather than hardcoded. A literal count written for one interval silently
rejects every session at another -- which is how this sleeve produced zero
trades on its first run against fifteen-minute bars."""


@dataclass
class DayburnConfig:
    n_in_play: int = 20
    """Names traded per session. Breadth matters more than conviction here:
    the per-name hit rate is low by construction."""

    w_gap: float = 0.45
    w_or_rvol: float = 0.35
    w_or_range: float = 0.20
    """Weights on the three components of the in-play score. All are known by
    10:00 ET, which is the sleeve's earliest permitted entry: the overnight
    gap is known at the bell, and the first-thirty-minute volume and range
    are known at 10:00.

    Pre-market relative volume -- the strongest single in-play measure in the
    practitioner literature -- is **not** used, because the bars in this
    programme are regular-hours only. See the skipped-items section of the
    strategy document."""

    min_price: float = 5.0
    min_addv: float = 20_000_000.0
    max_spread_bps: float = 8.0
    """Only trade names whose modelled spread is inside this. This sleeve
    crosses the spread on both legs in the continuous market, so the spread
    is its single largest cost and a name that is wide is untradable by it
    regardless of how attractive the signal looks."""
    """Higher liquidity floor than the cross-sectional sleeves: this book
    crosses the spread twice a day in the continuous market, so it can only
    live in names where that is cheap."""

    max_gross: float = 3.0
    max_net: float = 0.75
    """Breakouts cluster directionally -- on a strong trend day nearly every
    in-play name breaks the same way. That is a real beta exposure, so it is
    capped and reported rather than assumed away."""

    cone_vol_source: str = "blend"
    """How the cone's volatility level is set: `trailing` uses the name's own
    twenty-day average realised volatility, `today` infers it from the width
    of the opening range, `blend` takes the larger of the two.

    This matters more than it looks. The sleeve deliberately selects names
    whose volatility today is abnormal, so a cone scaled by trailing
    volatility is systematically too narrow for exactly the names being
    traded, and the strategy enters on noise. The opening range is a
    same-session estimate available at 10:00, which is before the sleeve's
    first permitted entry, so using it introduces no look-ahead."""

    parkinson_factor: float = 1.6
    """Expected ratio of a random walk's range to its absolute displacement
    over the same interval, used to convert the opening-range width into a
    displacement-scaled volatility."""

    rules: IntradayRules = field(default_factory=IntradayRules)
    daily_loss_limit: float = 0.02
    """Stop opening new positions for the session once the day's realised
    loss passes this fraction of equity."""

    target_vol: float = 0.10
    vol_lookback: int = 60
    max_leverage_scalar: float = 3.0


def in_play_score(day: pd.DataFrame, cfg: DayburnConfig) -> pd.Series:
    """Rank-combine the attention measures into one score."""
    def rk(s: pd.Series) -> pd.Series:
        return s.rank(pct=True, na_option="bottom")

    return (
        cfg.w_gap * rk(day["gap_z"].abs())
        + cfg.w_or_rvol * rk(day["rvol_or30"])
        + cfg.w_or_range * rk(day["or30_range_z"])
    )


def select_in_play(features: pd.DataFrame, cfg: DayburnConfig) -> pd.DataFrame:
    """Per session, the names the sleeve is allowed to trade.

    Every input is observable by 10:00 ET on the same day: pre-market volume
    and the opening gap are known at the bell, and the first-30-minute
    volume is known at 10:00, which is the earliest the sleeve may enter.
    """
    f = features[
        (features["p_open"] >= cfg.min_price)
        & (features["addv60"] >= cfg.min_addv)
        & features["rvol_or30"].notna()
        & features["gap_z"].notna()
        & features["or30_range_z"].notna()
        & (features["spread"] * 1e4 <= cfg.max_spread_bps)
    ].copy()
    f["play"] = f.groupby("d", group_keys=False).apply(
        lambda g: in_play_score(g, cfg), include_groups=False
    )
    f["play_rank"] = f.groupby("d")["play"].rank(ascending=False, method="first")
    return f[f["play_rank"] <= cfg.n_in_play].copy()


def size_trades(
    trades: pd.DataFrame,
    equity: float,
    cfg: DayburnConfig,
    vol_scalar: float,
) -> pd.DataFrame:
    """Risk-parity sizing: every trade risks the same fraction of equity
    between its entry and its initial stop, subject to a per-name weight cap
    and a participation cap against the name's own dollar volume."""
    t = trades.copy()
    risk_budget = cfg.rules.risk_per_trade * equity * vol_scalar
    t["notional"] = risk_budget / t["risk_frac"].clip(lower=1e-4)
    t["notional"] = t[["notional"]].assign(
        cap_w=cfg.rules.max_position_weight * equity,
        cap_adv=cfg.rules.max_adv_participation * t["addv60"].fillna(0.0),
    ).min(axis=1)

    gross = t["notional"].sum()
    if gross > cfg.max_gross * equity and gross > 0:
        t["notional"] *= cfg.max_gross * equity / gross

    net = (t["notional"] * t["side"]).sum()
    if abs(net) > cfg.max_net * equity and gross > 0:
        # trim the crowded side rather than levering the other one up
        crowded = np.sign(net)
        excess = abs(net) - cfg.max_net * equity
        mask = t["side"] == crowded
        side_gross = t.loc[mask, "notional"].sum()
        if side_gross > 0:
            t.loc[mask, "notional"] *= max(1.0 - excess / side_gross, 0.0)
    return t


def apply_daily_loss_limit(
    t: pd.DataFrame, equity: float, cfg: DayburnConfig
) -> pd.DataFrame:
    """Drop trades that would have been opened after the day's loss limit was
    already breached.

    Trades are ordered by entry time and their realised P&L accumulated in
    that order; once cumulative loss passes the limit, no further position is
    opened that session. Positions already open are left to run to their own
    stop or time exit, which is what a desk-level loss limit actually does --
    it stops new risk, it does not liquidate at the moment of breach.
    """
    if t.empty or cfg.daily_loss_limit <= 0:
        return t
    o = t.sort_values("entry_mod").copy()
    realised = (o["notional"] * o["gross_ret"]).cumsum().shift(1).fillna(0.0)
    allowed = realised > -cfg.daily_loss_limit * equity
    return o[allowed]


def apply_costs(t: pd.DataFrame, cost: CostConfig) -> pd.Series:
    """Round-trip continuous-market cost per trade, in currency.

    This sleeve crosses the spread on both legs -- it is not an auction
    strategy -- which is the dominant term in its cost and the reason it
    carries a much higher liquidity floor than the other two.
    """
    from ..costs import fee_rate

    spread = t["spread"].clip(cost.min_spread_bps / 1e4, cost.max_spread_bps / 1e4)
    part = (t["notional"] / t["addv60"].clip(lower=1.0)).clip(0.0, 1.0)
    impact = cost.impact_eta_continuous * t["daily_vol"].fillna(0.02) * np.sqrt(part)
    fees = fee_rate(t["entry_px"].to_numpy(), cost, auction=False)
    one_way = fees + cost.spread_capture * spread + impact
    return 2.0 * one_way * t["notional"]


class Dayburn:
    """Runner for the intraday sleeve.

    Unlike the cross-sectional strategies this one does not plug into
    `SegmentBacktester`: its return comes from a path within the session, so
    it is simulated bar by bar and then reduced to a daily return series that
    the same performance machinery can consume.
    """

    name = "dayburn"

    def __init__(
        self,
        features: pd.DataFrame,
        bars: pd.DataFrame,
        cone: pd.DataFrame,
        *,
        config: DayburnConfig | None = None,
        cost: CostConfig | None = None,
        initial_equity: float = 100_000_000.0,
    ) -> None:
        self.cfg = config or DayburnConfig()
        self.cost = cost or CostConfig()
        self.equity0 = initial_equity
        self.features = features
        self.bars = bars
        self.cone = cone

    def run(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        from ..intraday_sim import running_vwap, simulate_day_symbol

        sel = select_in_play(self.features, self.cfg)
        shape = self.cone.set_index(["d", "mod"])["shape_ratio"]
        bars = self.bars.sort_values(["d", "symbol", "mod"])

        meta_cols = ["symbol", "d", "or30_hi", "or30_lo", "rv_day_prev", "addv60", "spread", "daily_vol"]
        meta = sel[meta_cols].set_index(["d", "symbol"])
        wanted = set(map(tuple, sel[["d", "symbol"]].to_numpy()))

        rules = self.cfg.rules
        trades: list[dict] = []
        for (d, sym), g in bars.groupby(["d", "symbol"], sort=True):
            if (d, sym) not in wanted:
                continue
            m = meta.loc[(d, sym)]
            g = g[(g["mod"] >= RTH_OPEN) & (g["mod"] < RTH_CLOSE)]
            if len(g) < MIN_SESSION_BARS:
                continue
            mods = g["mod"].to_numpy()
            try:
                sh = shape.loc[d].reindex(mods).to_numpy(dtype=float)
            except KeyError:
                continue
            sigma = self._cone_sigma(m, shape, d)
            if sigma is None:
                continue
            cone_vals = sh * sigma

            o = g["open"].to_numpy(dtype=float)
            h = g["high"].to_numpy(dtype=float)
            lo = g["low"].to_numpy(dtype=float)
            c = g["close"].to_numpy(dtype=float)
            vw = running_vwap(g["vwap"].to_numpy(dtype=float), g["volume"].to_numpy(dtype=float))
            p_open = float(o[0])
            atr = sigma / np.sqrt(BARS_PER_SESSION) * p_open * 2.0

            for tr in simulate_day_symbol(
                mods, o, h, lo, c, vw, cone_vals, p_open,
                float(m["or30_hi"]), float(m["or30_lo"]), atr, rules,
            ):
                side, emod, epx, xmod, xpx, spx, reason, riskf, gret = tr
                trades.append(
                    {
                        "d": d, "symbol": sym, "side": side,
                        "entry_mod": emod, "entry_px": epx,
                        "exit_mod": xmod, "exit_px": xpx, "stop_px": spx,
                        "reason": reason, "risk_frac": riskf, "gross_ret": gret,
                        "addv60": float(m["addv60"]), "spread": float(m["spread"]),
                        "daily_vol": float(m["daily_vol"]),
                    }
                )

        tdf = pd.DataFrame(trades)
        if tdf.empty:
            return tdf, pd.DataFrame()
        return tdf, self._accumulate(tdf)

    def _cone_sigma(self, meta_row, shape, d) -> float | None:
        """Volatility level for the cone, in daily log-return units."""
        trailing = float(meta_row["rv_day_prev"])
        if self.cfg.cone_vol_source == "trailing":
            return trailing if np.isfinite(trailing) and trailing > 0 else None

        hi, lo = float(meta_row["or30_hi"]), float(meta_row["or30_lo"])
        today = np.nan
        if np.isfinite(hi) and np.isfinite(lo) and lo > 0 and hi > lo:
            try:
                anchor = float(shape.loc[(d, ENTRY_ANCHOR_MOD)])
            except (KeyError, TypeError):
                anchor = np.nan
            if np.isfinite(anchor) and anchor > 0:
                today = (np.log(hi / lo) / self.cfg.parkinson_factor) / anchor

        if self.cfg.cone_vol_source == "today":
            return float(today) if np.isfinite(today) and today > 0 else None
        candidates = [x for x in (trailing, today) if np.isfinite(x) and x > 0]
        return float(max(candidates)) if candidates else None

    def _accumulate(self, tdf: pd.DataFrame) -> pd.DataFrame:
        """Walk the trade blotter forward, sizing each day against the equity
        actually available and against a causal volatility estimate."""
        equity = self.equity0
        peak = equity
        unit_rets: list[float] = []
        rows: list[dict] = []

        for d, g in tdf.groupby("d", sort=True):
            if len(unit_rets) >= 20:
                r = np.asarray(unit_rets[-self.cfg.vol_lookback :])
                vol = float(r.std(ddof=1) * np.sqrt(252))
            else:
                vol = self.cfg.target_vol
            scalar = min(self.cfg.target_vol / max(vol, 0.02), self.cfg.max_leverage_scalar)

            sized = size_trades(g, equity, self.cfg, scalar)
            sized = apply_daily_loss_limit(sized, equity, self.cfg)
            if sized.empty:
                continue
            cost = apply_costs(sized, self.cost)
            pnl = float((sized["notional"] * sized["gross_ret"]).sum() - cost.sum())
            gross = float(sized["notional"].sum())
            net = float((sized["notional"] * sized["side"]).sum())

            # the unit-gross return, recorded for the next day's vol estimate
            unit_rets.append(float((sized["notional"] * sized["gross_ret"]).sum() / max(gross, 1.0)))

            equity += pnl
            peak = max(peak, equity)
            rows.append(
                {
                    "date": pd.Timestamp(d), "equity": equity, "pnl": pnl,
                    "cost": float(cost.sum()), "gross": gross / max(equity, 1.0),
                    "net": net / max(equity, 1.0), "n_trades": len(sized),
                    "traded": 2.0 * gross, "drawdown": equity / peak - 1.0,
                    "hit": float((sized["gross_ret"] > 0).mean()),
                }
            )

        out = pd.DataFrame(rows).set_index("date")
        out["ret"] = out["equity"].pct_change().fillna(out["equity"].iloc[0] / self.equity0 - 1.0)
        out["turnover"] = out["traded"] / out["equity"].shift(1).fillna(self.equity0)
        out["financing"] = 0.0
        out["pnl_overnight"] = 0.0
        out["pnl_intraday"] = out["pnl"]
        return out
