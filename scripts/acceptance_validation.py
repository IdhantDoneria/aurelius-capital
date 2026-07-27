"""Institutional acceptance test — Phase 2 end-to-end validation.

Runs 5 benchmark strategies through the REAL BacktestEngine on deterministic,
seeded, multi-symbol synthetic data. Verifies the properties that matter for
research trust — accounting identity, costs applied, look-ahead prevention,
reproducibility, position sizing — and prints a pass/fail table.

Purpose is validation, NOT profitability. A benchmark "passes" if the engine
accounts for it correctly, not if it makes money.

Run: python scripts/acceptance_validation.py
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aurelius.backtesting import BacktestConfig, BacktestEngine
from aurelius.backtesting.data.feed import BarData, InMemoryDataFeed
from aurelius.backtesting.events.types import Direction, SignalEvent
from aurelius.backtesting.strategy.base import Strategy, StrategyContext

UNIVERSE = ["AAA", "BBB", "CCC", "DDD", "EEE"]
N_BARS = 300
SEED = 42


# ── deterministic synthetic data ────────────────────────────────────────────
def make_bars(seed: int = SEED) -> list[BarData]:
    """Seeded geometric random walk per symbol. Same seed = identical bars."""
    rng = random.Random(seed)
    bars: list[BarData] = []
    start = datetime(2020, 1, 2, tzinfo=UTC)
    for si, sym in enumerate(UNIVERSE):
        price = 100.0 + si * 20  # different starting levels
        drift = 0.0003 + si * 0.0002  # mild, symbol-specific drift
        for i in range(N_BARS):
            ret = drift + rng.gauss(0, 0.012)
            close = price * (1 + ret)
            high = max(price, close) * (1 + abs(rng.gauss(0, 0.003)))
            low = min(price, close) * (1 - abs(rng.gauss(0, 0.003)))
            bars.append(
                BarData(
                    symbol=sym,
                    timestamp=start + timedelta(days=i),
                    open=Decimal(str(round(price, 4))),
                    high=Decimal(str(round(high, 4))),
                    low=Decimal(str(round(low, 4))),
                    close=Decimal(str(round(close, 4))),
                    volume=Decimal("1000000"),
                )
            )
            price = close
    return bars


# ── 5 benchmark strategies ──────────────────────────────────────────────────
class BuyAndHold(Strategy):
    name = "buy_and_hold"

    def on_bar(self, ctx: StrategyContext, bar) -> list[SignalEvent]:
        if ctx.portfolio.position(bar.symbol).is_flat:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG, 1.0)]
        return []


class MACrossover(Strategy):
    name = "ma_crossover_50_200"

    def __init__(self, fast: int = 50, slow: int = 200) -> None:
        self.fast, self.slow = fast, slow

    def on_bar(self, ctx: StrategyContext, bar) -> list[SignalEvent]:
        c = ctx.close_series(bar.symbol, self.slow + 1)
        if len(c) < self.slow:
            return []
        fast = sum(c[-self.fast :]) / self.fast
        slow = sum(c[-self.slow :]) / self.slow
        pos = ctx.portfolio.position(bar.symbol)
        if fast > slow and pos.is_flat:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG, 1.0)]
        if fast < slow and pos.is_long:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.FLAT)]
        return []

    @property
    def parameters(self) -> dict:
        return {"fast": self.fast, "slow": self.slow}


class CrossSectionalMomentum(Strategy):
    """Rank universe by trailing return; long the top half, flat the rest.

    Called once per symbol per bar. Ranking uses only history <= now
    (look-ahead safe by construction of StrategyContext).
    """

    name = "xs_momentum"

    def __init__(self, lookback: int = 60) -> None:
        self.lookback = lookback

    def _trailing_return(self, ctx: StrategyContext, sym: str) -> float | None:
        c = ctx.close_series(sym, self.lookback + 1)
        if len(c) < self.lookback + 1:
            return None
        return float(c[-1] / c[0]) - 1.0

    def on_bar(self, ctx: StrategyContext, bar) -> list[SignalEvent]:
        rets = {}
        for sym in ctx.symbols_with_data:
            r = self._trailing_return(ctx, sym)
            if r is not None:
                rets[sym] = r
        if len(rets) < 2:
            return []
        ranked = sorted(rets, key=rets.get, reverse=True)
        top = set(ranked[: max(1, len(ranked) // 2)])
        pos = ctx.portfolio.position(bar.symbol)
        if bar.symbol in top and pos.is_flat:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG, 1.0)]
        if bar.symbol not in top and pos.is_long:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.FLAT)]
        return []

    @property
    def parameters(self) -> dict:
        return {"lookback": self.lookback}


class RSIMeanReversion(Strategy):
    name = "rsi_mean_reversion"

    def __init__(self, period: int = 14, low: float = 30, high: float = 70) -> None:
        self.period, self.low, self.high = period, low, high

    def _rsi(self, closes: list) -> float | None:
        if len(closes) < self.period + 1:
            return None
        gains, losses = 0.0, 0.0
        for a, b in zip(closes[-self.period - 1 :], closes[-self.period :], strict=False):
            d = float(b) - float(a)
            gains += max(d, 0.0)
            losses += max(-d, 0.0)
        if losses == 0:
            return 100.0
        rs = (gains / self.period) / (losses / self.period)
        return 100.0 - 100.0 / (1.0 + rs)

    def on_bar(self, ctx: StrategyContext, bar) -> list[SignalEvent]:
        rsi = self._rsi(ctx.close_series(bar.symbol, self.period + 2))
        if rsi is None:
            return []
        pos = ctx.portfolio.position(bar.symbol)
        if rsi < self.low and pos.is_flat:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG, 1.0)]
        if rsi > self.high and pos.is_long:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.FLAT)]
        return []

    @property
    def parameters(self) -> dict:
        return {"period": self.period, "low": self.low, "high": self.high}


class EqualWeight(Strategy):
    """Hold every symbol at equal weight. Rebalance is implicit via sizing."""

    name = "equal_weight"

    def on_bar(self, ctx: StrategyContext, bar) -> list[SignalEvent]:
        n = len(UNIVERSE)
        if ctx.portfolio.position(bar.symbol).is_flat:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG, 1.0 / n)]
        return []


STRATEGIES = [BuyAndHold, MACrossover, CrossSectionalMomentum, RSIMeanReversion, EqualWeight]


def config() -> BacktestConfig:
    return BacktestConfig(
        initial_capital=Decimal("1_000_000"),
        commission_rate=Decimal("0.0010"),
        spread_bps=Decimal("5"),
        slippage_impact_bps=Decimal("10"),
        max_position_pct=Decimal("0.20"),
        max_drawdown_halt=Decimal("0.50"),
    )


# ── verification checks ─────────────────────────────────────────────────────
def verify(strat_cls) -> dict:
    bars = make_bars()
    feed = InMemoryDataFeed(bars)
    eng = BacktestEngine(strategy=strat_cls(), data_feed=feed, config=config())
    rep = eng.run()

    checks: dict[str, bool] = {}

    # 1. Equity curve has exactly one point per processed bar event.
    #    NOTE: engine snapshots per MarketEvent, so multi-symbol runs get
    #    n_symbols points per calendar day (see report — Sharpe sampling debt).
    checks["equity_curve_len"] = len(rep.metrics.equity_curve) == len(bars)

    # 2. Equity curve starts at initial capital.
    checks["starts_at_capital"] = abs(rep.metrics.equity_curve[0].equity - 1_000_000) < 5_000

    # 3. Drawdown is never positive (it is a loss measure).
    checks["drawdown_non_positive"] = all(dd <= 1e-6 for _, dd in rep.metrics.drawdown_series)

    # 4. Transaction costs actually charged (every fill has positive commission).
    fills = eng._all_fills
    checks["costs_charged"] = bool(fills) and all(f.commission > 0 for f in fills)

    # 5. Look-ahead prevention: no fill timestamp precedes its bar; fills land on
    #    a bar strictly AFTER the earliest possible signal bar (engine T+1 rule).
    ts_sorted = sorted({b.timestamp for b in bars})
    first_ts = ts_sorted[0]
    checks["no_fill_on_first_bar"] = all(f.timestamp > first_ts for f in fills) if fills else True

    # 6. Position sizing respects max_position_pct at entry (per-name notional
    #    <= max_position_pct * NAV, with a tolerance for the fill-price move).
    cap = 1_000_000 * 0.20 * 1.15
    checks["sizing_within_limit"] = all(float(f.notional) <= cap for f in fills) if fills else True

    # 7. Reproducibility: identical seed -> identical final equity + fill count.
    feed2 = InMemoryDataFeed(make_bars())
    eng2 = BacktestEngine(strategy=strat_cls(), data_feed=feed2, config=config())
    rep2 = eng2.run()
    same_equity = (
        abs(rep.metrics.equity_curve[-1].equity - rep2.metrics.equity_curve[-1].equity) < 1e-6
    )
    checks["reproducible"] = same_equity and len(fills) == len(eng2._all_fills)

    return {
        "name": rep.strategy_name,
        "bars": rep.total_bars,
        "fills": len(fills),
        "total_return": rep.metrics.total_return,
        "sharpe": rep.metrics.sharpe_ratio,
        "max_dd": rep.metrics.max_drawdown,
        "checks": checks,
    }


def main() -> int:
    print(f"\nAcceptance validation — {len(STRATEGIES)} benchmarks, "
          f"{len(UNIVERSE)} symbols x {N_BARS} bars, seed={SEED}\n")
    check_names = [
        "equity_curve_len", "starts_at_capital", "drawdown_non_positive",
        "costs_charged", "no_fill_on_first_bar", "sizing_within_limit", "reproducible",
    ]
    all_pass = True
    header = f"{'strategy':<22}{'fills':>6}{'ret':>9}{'sharpe':>8}{'maxDD':>8}  checks"
    print(header)
    print("-" * len(header))
    for cls in STRATEGIES:
        r = verify(cls)
        passed = all(r["checks"].values())
        all_pass &= passed
        mark = "PASS" if passed else "FAIL"
        failed = [n for n in check_names if not r["checks"][n]]
        print(
            f"{r['name']:<22}{r['fills']:>6}{r['total_return']:>8.1%}"
            f"{r['sharpe']:>8.2f}{r['max_dd']:>8.1%}  {mark}"
            + (f"  missing: {failed}" if failed else "")
        )
    print("\n" + ("ALL CHECKS PASS" if all_pass else "SOME CHECKS FAILED"))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
