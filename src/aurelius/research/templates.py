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


class FactorStrategy(Strategy):
    """Cross-sectional momentum factor: long the top quantile, short the bottom.

    Leak-safe: the cross-section at time t is built from ctx.history (bars <= t)
    for every symbol. Rebalances on a fixed cadence to control turnover.
    """

    name = "factor"

    def __init__(
        self,
        lookback: int = 60,
        quantile: float = 0.33,
        rebalance_days: int = 21,
        allow_short: bool = True,
    ) -> None:
        self.lookback = lookback
        self.quantile = quantile
        self.rebalance_days = rebalance_days
        self.allow_short = allow_short

    @property
    def parameters(self) -> dict:
        return {
            "lookback": self.lookback,
            "quantile": self.quantile,
            "rebalance_days": self.rebalance_days,
            "allow_short": self.allow_short,
        }

    def on_bar(self, ctx: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        # Rebalance gate: act only every rebalance_days bars for this symbol.
        if len(ctx.history(bar.symbol)) % self.rebalance_days != 0:
            return []
        scores: dict[str, float] = {}
        for s in ctx.symbols_with_data:
            c = _closes(ctx, s, self.lookback + 1)
            if len(c) < self.lookback + 1 or c[0] == 0:
                continue
            scores[s] = (c[-1] - c[0]) / c[0]
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
        return [SignalEvent(bar.timestamp, bar.symbol, d, strategy_id=self.name)]
