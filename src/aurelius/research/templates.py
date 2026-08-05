"""Reusable strategy templates. Rule-based; parameters are tunable knobs the
validation framework then stress-tests for fragility.

All templates obey the Phase-4 contract: on_bar(ctx, bar) -> list[SignalEvent],
read history only through ctx, never look ahead. The statistics here are the
same definitions as the Phase-5 feature library (simple returns, z-score,
cross-sectional momentum) — templates are the parametric research harness,
features are the fixed, versioned production signals.
"""

from __future__ import annotations

import statistics

from aurelius.backtesting.events.types import Direction, MarketEvent, SignalEvent
from aurelius.backtesting.strategy.base import Strategy, StrategyContext
from aurelius.research.liquidity import (
    DEFAULT_METRIC,
    LIQUIDITY_METRICS,
    screen as _screen,
)
from aurelius.research.portfolio_construction import invariant_weight


def _closes(ctx: StrategyContext, symbol: str, n: int) -> list[float]:
    return [float(b.close) for b in ctx.history(symbol, n)]


class MomentumStrategy(Strategy):
    """Long names whose trailing return exceeds a threshold. Optional short leg."""

    name = "momentum"

    def __init__(self, lookback: int = 60, entry: float = 0.0, allow_short: bool = False) -> None:
        self.lookback = lookback
        self.entry = entry
        self.allow_short = allow_short

    @property
    def parameters(self) -> dict:
        return {"lookback": self.lookback, "entry": self.entry, "allow_short": self.allow_short}

    def on_bar(self, ctx: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        c = _closes(ctx, bar.symbol, self.lookback + 1)
        if len(c) < self.lookback + 1 or c[0] == 0:
            return []
        mom = (c[-1] - c[0]) / c[0]
        if mom > self.entry:
            d = Direction.LONG
        elif self.allow_short and mom < -self.entry:
            d = Direction.SHORT
        else:
            d = Direction.FLAT
        return [SignalEvent(bar.timestamp, bar.symbol, d, strategy_id=self.name)]


class MeanReversionStrategy(Strategy):
    """Fade extremes: long when z-score of price is low, short when high."""

    name = "mean_reversion"

    def __init__(
        self,
        lookback: int = 20,
        entry_z: float = 1.0,
        exit_z: float = 0.25,
        allow_short: bool = True,
    ) -> None:
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.allow_short = allow_short

    @property
    def parameters(self) -> dict:
        return {
            "lookback": self.lookback,
            "entry_z": self.entry_z,
            "exit_z": self.exit_z,
            "allow_short": self.allow_short,
        }

    def on_bar(self, ctx: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        c = _closes(ctx, bar.symbol, self.lookback)
        if len(c) < self.lookback:
            return []
        sd = statistics.pstdev(c)
        if sd == 0:
            return []
        z = (c[-1] - statistics.mean(c)) / sd
        if z < -self.entry_z:
            d = Direction.LONG
        elif self.allow_short and z > self.entry_z:
            d = Direction.SHORT
        elif abs(z) < self.exit_z:
            d = Direction.FLAT
        else:
            return []  # hold current position, no new signal
        return [SignalEvent(bar.timestamp, bar.symbol, d, strategy_id=self.name)]


class PairsStrategy(Strategy):
    """Trade the spread of two symbols. Acts once per timestamp (on symbol_y's bar).

    spread = close_x - hedge * close_y. When its z-score is extreme, go long the
    cheap leg and short the rich leg; flatten as it reverts.
    """

    name = "pairs"

    def __init__(
        self,
        symbol_x: str,
        symbol_y: str,
        lookback: int = 60,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        hedge: float = 1.0,
    ) -> None:
        self.symbol_x = symbol_x
        self.symbol_y = symbol_y
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.hedge = hedge

    @property
    def parameters(self) -> dict:
        return {
            "symbol_x": self.symbol_x,
            "symbol_y": self.symbol_y,
            "lookback": self.lookback,
            "entry_z": self.entry_z,
            "exit_z": self.exit_z,
            "hedge": self.hedge,
        }

    def on_bar(self, ctx: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        if bar.symbol != self.symbol_y:
            return []  # evaluate the pair once per timestamp, on the second leg
        cx = _closes(ctx, self.symbol_x, self.lookback)
        cy = _closes(ctx, self.symbol_y, self.lookback)
        n = min(len(cx), len(cy))
        if n < self.lookback:
            return []
        spread = [cx[-n + i] - self.hedge * cy[-n + i] for i in range(n)]
        sd = statistics.pstdev(spread)
        if sd == 0:
            return []
        z = (spread[-1] - statistics.mean(spread)) / sd
        ts = bar.timestamp
        if z > self.entry_z:  # spread rich -> short x, long y
            return [
                SignalEvent(ts, self.symbol_x, Direction.SHORT, strategy_id=self.name),
                SignalEvent(ts, self.symbol_y, Direction.LONG, strategy_id=self.name),
            ]
        if z < -self.entry_z:  # spread cheap -> long x, short y
            return [
                SignalEvent(ts, self.symbol_x, Direction.LONG, strategy_id=self.name),
                SignalEvent(ts, self.symbol_y, Direction.SHORT, strategy_id=self.name),
            ]
        if abs(z) < self.exit_z:
            return [
                SignalEvent(ts, self.symbol_x, Direction.FLAT, strategy_id=self.name),
                SignalEvent(ts, self.symbol_y, Direction.FLAT, strategy_id=self.name),
            ]
        return []


class MultiPairStrategy(Strategy):
    """Gatev portfolio: trade N pairs' spreads at once in ONE backtest, so the
    equity curve carries genuine cross-pair diversification (not an average of N
    single-pair Sharpes, which would fake it). Pure composition of PairsStrategy
    — each sub-strategy owns one pair; on_bar concatenates their signals. Engine
    untouched; it already sizes/nets a multi-symbol long/short book.
    """

    name = "multi_pairs"

    def __init__(self, pairs: list[tuple], lookback: int = 126,
                 entry_z: float = 2.0, exit_z: float = 0.5) -> None:
        # pairs: list of (symbol_x, symbol_y, hedge)
        self._subs = [
            PairsStrategy(x, y, lookback=lookback, entry_z=entry_z,
                          exit_z=exit_z, hedge=hedge)
            for x, y, hedge in pairs
        ]
        self._pairs = pairs
        self.lookback, self.entry_z, self.exit_z = lookback, entry_z, exit_z

    @property
    def parameters(self) -> dict:
        return {"n_pairs": len(self._subs), "lookback": self.lookback,
                "entry_z": self.entry_z, "exit_z": self.exit_z,
                "pairs": [f"{x}|{y}" for x, y, _ in self._pairs]}

    def on_bar(self, ctx: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        out: list[SignalEvent] = []
        for sub in self._subs:
            out.extend(sub.on_bar(ctx, bar))
        return out


class OverlappingFactorStrategy(Strategy):
    """JT-1993 overlapping K-cohort momentum portfolio.

    Maintains K independent cohorts, each rebalancing every K*period bars
    (the holding period). At each period, exactly one cohort updates its
    selection while the other K-1 retain their prior selections. The signal
    for each symbol is the net vote across all K cohorts, weighted by
    conviction (long_count - short_count) / K.

    This matches JT's description: 'at the beginning of each month t, the
    securities are ranked in ascending order on the basis of their returns in
    the past J months. Based on these rankings, ten decile portfolios are
    formed … the portfolios are held for K months.'  The strategy rebalances
    1/K of the book each period so at any time the book carries K overlapping
    vintages.

    M3 baseline = M1 (equal_weight) + M2 (min_price) + overlapping cohorts.

    Engine compatibility: the engine has one position per symbol, so all K
    cohorts must be aggregated into a SINGLE signal per symbol before dispatch.
    State (cohort memberships) is stored in self and updated once per
    portfolio-level rebalance timestamp.
    """

    name = "overlapping_factor"

    def __init__(
        self,
        K: int = 6,
        lookback: int = 126,
        rebalance_days: int = 21,
        quantile: float = 0.10,
        allow_short: bool = True,
        equal_weight: bool = True,
        min_price: float = 5.0,
    ) -> None:
        self.K = K
        self.lookback = lookback
        self.rebalance_days = rebalance_days
        self.quantile = quantile
        self.allow_short = allow_short
        self.equal_weight = equal_weight
        self.min_price = min_price
        # Per-cohort cached cross-section: cohort k -> {symbol: Direction}
        self._memberships: list[dict[str, Direction]] = [{} for _ in range(K)]
        self._n_decile: list[int] = [0] * K
        # Global portfolio-level clock (shared across all symbol on_bar calls)
        self._last_seen_ts: object = None
        self._trading_day: int = 0    # incremented once per unique timestamp
        self._last_period_computed: int = -1  # period_idx of last cohort update

    @property
    def parameters(self) -> dict:
        return {
            "K": self.K,
            "lookback": self.lookback,
            "rebalance_days": self.rebalance_days,
            "quantile": self.quantile,
            "allow_short": self.allow_short,
            "equal_weight": self.equal_weight,
            "min_price": self.min_price,
        }

    def _build_cross_section(self, ctx: StrategyContext) -> tuple[dict[str, Direction], int]:
        scores: dict[str, float] = {}
        for s in ctx.symbols_with_data:
            c = _closes(ctx, s, self.lookback + 1)
            if len(c) < self.lookback + 1 or c[0] == 0:
                continue
            if self.min_price > 0 and float(c[-1]) < self.min_price:
                continue
            scores[s] = (c[-1] - c[0]) / c[0]
        if len(scores) < 3:
            return {}, 0
        ranked = sorted(scores.values())
        n = len(ranked)
        n_decile = max(1, int(self.quantile * n))
        lo, hi = ranked[n_decile - 1], ranked[n - n_decile]
        memberships: dict[str, Direction] = {}
        for s, v in scores.items():
            if v >= hi:
                memberships[s] = Direction.LONG
            elif self.allow_short and v <= lo:
                memberships[s] = Direction.SHORT
            else:
                memberships[s] = Direction.FLAT
        return memberships, n_decile

    def on_bar(self, ctx: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        # Advance global trading-day counter once per unique timestamp.
        if ctx.now != self._last_seen_ts:
            self._trading_day += 1
            self._last_seen_ts = ctx.now

        b = self._trading_day
        if b % self.rebalance_days != 0:
            return []

        # Which cohort rebalances this period?
        period_idx = b // self.rebalance_days
        active_k = period_idx % self.K

        # Recompute active cohort once per portfolio-level rebalance period.
        # First symbol at this timestamp (period_idx changed) triggers the update;
        # subsequent symbols at the same timestamp use the cached memberships.
        if period_idx != self._last_period_computed:
            m, n_d = self._build_cross_section(ctx)
            self._memberships[active_k] = m
            self._n_decile[active_k] = n_d
            self._last_period_computed = period_idx

        # Aggregate votes across all K cohorts that have been initialized.
        active_cohorts = [k for k in range(self.K) if self._n_decile[k] > 0]
        if not active_cohorts:
            return []

        sym_directions = [self._memberships[k].get(bar.symbol, Direction.FLAT)
                          for k in active_cohorts]
        long_count = sym_directions.count(Direction.LONG)
        short_count = sym_directions.count(Direction.SHORT)

        if long_count > short_count:
            d = Direction.LONG
        elif short_count > long_count:
            d = Direction.SHORT
        else:
            d = Direction.FLAT

        if d == Direction.FLAT:
            return [SignalEvent(bar.timestamp, bar.symbol, d, strategy_id=self.name)]

        if self.equal_weight:
            # Net conviction as fraction of full K cohorts × equal-weight budget.
            # max n_decile across active cohorts = reference decile size.
            n_ref = max(self._n_decile[k] for k in active_cohorts)
            net = abs(long_count - short_count)
            gross_factor = 0.75 if self.allow_short else 1.0
            strength = (net / self.K) * (gross_factor / n_ref)
        else:
            strength = 1.0

        return [SignalEvent(bar.timestamp, bar.symbol, d, strategy_id=self.name,
                            strength=strength)]


class FactorStrategy(Strategy):
    """Cross-sectional momentum factor: long the top quantile, short the bottom.

    Leak-safe: the cross-section at time t is built from ctx.history (bars <= t)
    for every symbol. Rebalances on a fixed cadence to control turnover.

    equal_weight=True (M1): each decile name receives an equal share of the
    gross leverage budget (0.75/n per leg for L/S; 1.0/n for long-only) so the
    full decile expresses without hitting the gross cap. Requires the backtest
    config to use max_position_pct=1.0 (strength IS the target NAV fraction).

    min_price (M2): formation-time price screen. JT-2001 explicitly drops
    stocks with price < $5 to remove penny-stock microstructure noise. Applied
    at each rebalance: a name below min_price is excluded from the cross-section
    for that period. Default 0.0 (off) for backward compatibility.

    skip (M4): one-month skip period. JT-1993 ranks on the formation window
    ending `skip` bars BEFORE the holding period begins, to remove the
    short-term (1-month) reversal contaminating the momentum signal. The
    formation return is measured from lookback+skip bars ago to skip bars ago;
    the most recent `skip` bars are excluded from ranking. Default 0 (off,
    contiguous formation→holding) for backward compatibility.

    liquidity_filter (M7): the only M6-approved universe screen. When enabled,
    at each rebalance the bottom `liquidity_pct` fraction of the cross-section by
    `liquidity_metric` (computed over the trailing `liquidity_window` bars, bars
    <= t → no look-ahead) is dropped BEFORE momentum ranking. Uses only close +
    volume — no market cap, no shares, no exchange. Default OFF
    (liquidity_filter=False) → the on_bar code path is byte-identical to M4, so
    the certified baseline is unchanged when the feature is disabled. Metric
    library + default-selection rationale live in `research/liquidity.py`.
    """

    name = "factor"

    def __init__(
        self,
        lookback: int = 60,
        quantile: float = 0.33,
        rebalance_days: int = 21,
        allow_short: bool = True,
        equal_weight: bool = False,
        min_price: float = 0.0,
        skip: int = 0,
        liquidity_filter: bool = False,
        liquidity_metric: str = DEFAULT_METRIC,
        liquidity_pct: float = 0.0,
        liquidity_window: int = 21,
        invariant_construction: bool = False,
        max_position_weight: float = 0.10,
        min_constituents: int = 10,
    ) -> None:
        self.lookback = lookback
        self.quantile = quantile
        self.rebalance_days = rebalance_days
        self.allow_short = allow_short
        self.equal_weight = equal_weight
        self.min_price = min_price
        self.skip = skip
        self.liquidity_filter = liquidity_filter
        self.liquidity_metric = liquidity_metric
        self.liquidity_pct = liquidity_pct
        self.liquidity_window = liquidity_window
        self.invariant_construction = invariant_construction
        self.max_position_weight = max_position_weight
        self.min_constituents = min_constituents

    @property
    def parameters(self) -> dict:
        return {
            "lookback": self.lookback,
            "quantile": self.quantile,
            "rebalance_days": self.rebalance_days,
            "allow_short": self.allow_short,
            "equal_weight": self.equal_weight,
            "min_price": self.min_price,
            "skip": self.skip,
            "liquidity_filter": self.liquidity_filter,
            "liquidity_metric": self.liquidity_metric,
            "liquidity_pct": self.liquidity_pct,
            "liquidity_window": self.liquidity_window,
            "invariant_construction": self.invariant_construction,
            "max_position_weight": self.max_position_weight,
            "min_constituents": self.min_constituents,
        }

    def on_bar(self, ctx: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        # Rebalance gate: act only every rebalance_days bars for this symbol.
        if len(ctx.history(bar.symbol)) % self.rebalance_days != 0:
            return []
        scores: dict[str, float] = {}
        need = self.lookback + self.skip + 1
        for s in ctx.symbols_with_data:
            c = _closes(ctx, s, need)
            if len(c) < need or c[0] == 0:
                continue
            # M2 price screen: JT-2001 drops stocks priced below $5 (current price).
            if self.min_price > 0 and float(c[-1]) < self.min_price:
                continue
            # M4 skip: formation return ends `skip` bars ago, not at the current
            # bar. c[-1-skip] is the formation-window end; c[0] is its start,
            # exactly lookback bars earlier. skip=0 → c[-1], identical to M2.
            end = c[-1 - self.skip]
            scores[s] = (end - c[0]) / c[0]
        # M7 liquidity screen: drop the least-liquid tail of the cross-section
        # before ranking. Guarded so disabled → byte-identical to M4 (no volume
        # fetch, no branch). Look-ahead-free: trailing-window metrics only.
        if self.liquidity_filter and self.liquidity_pct > 0 and scores:
            fn, higher_liquid = LIQUIDITY_METRICS[self.liquidity_metric]
            w = self.liquidity_window
            liq: dict[str, float] = {}
            for s in scores:
                bars = ctx.history(s, w)
                if len(bars) < w:
                    continue
                liq[s] = fn([float(b.close) for b in bars],
                            [float(b.volume) for b in bars])
            if liq:
                survivors = _screen(liq, self.liquidity_pct, higher_liquid)
                scores = {s: v for s, v in scores.items()
                          if s not in liq or s in survivors}
        if bar.symbol not in scores or len(scores) < 3:
            return []
        ranked = sorted(scores.values())
        _n = len(ranked)
        _count = max(1, int(self.quantile * _n))
        lo = ranked[_count - 1]
        hi = ranked[_n - _count]
        val = scores[bar.symbol]
        if val >= hi:
            d = Direction.LONG
        elif self.allow_short and val <= lo:
            d = Direction.SHORT
        else:
            d = Direction.FLAT
        # M1: equal-weight within gross leverage budget.
        # gross_budget=1.5 split 50/50 long/short → 0.75/_count per leg;
        # long-only → 1.0/_count (fully invested). Requires max_position_pct=1.0.
        if self.equal_weight and d != Direction.FLAT:
            budget = 0.75 if self.allow_short else 1.0
            # M8 invariant construction: bound single-name weight (cap + min-
            # constituent floor) so a shrunk universe can't concentrate the book.
            # Default OFF and, when ON, byte-identical to baseline while the bounds
            # are slack (full universe) — see portfolio_construction.invariant_weight.
            if self.invariant_construction:
                strength = invariant_weight(_count, budget,
                                            self.max_position_weight,
                                            self.min_constituents)
            else:
                strength = budget / _count
        else:
            strength = 1.0
        return [SignalEvent(bar.timestamp, bar.symbol, d, strategy_id=self.name, strength=strength)]
