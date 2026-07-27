"""BacktestEngine — the main event-driven simulation loop.

Wires together every component and enforces the execution model:

  For each bar (in chronological order):
    1. Fill any pending orders at this bar's OPEN price.
       FillEvent has EVENT_TYPE=1 → processes before MarketEvent(=2).
    2. Push MarketEvent to the queue.
    3. Drain the queue (Fill → Market → Signal → Order).
       - FillEvent: PortfolioManager.apply_fill() + OMS.apply_fill()
       - MarketEvent: mark_to_market, update history, call Strategy.on_bar()
                      → push SignalEvent(s)
       - SignalEvent: PortfolioManager.size_order() → push OrderEvent
       - OrderEvent: RiskEngine.check() → if pass: add to pending_orders
                                         if fail: OMS.reject()
    4. Record equity snapshot.

Why pending_orders lives outside the EventQueue:
  Orders are not filled within the same bar they're created (no look-ahead).
  They pend until the NEXT bar's open. The event queue processes within-bar
  events only. pending_orders is the "carry-forward" list between bars.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import UTC, datetime

from aurelius.backtesting.analytics.performance import EquityPoint, PerformanceCalculator
from aurelius.backtesting.analytics.report import BacktestReport
from aurelius.backtesting.config import BacktestConfig
from aurelius.backtesting.data.feed import DataFeed
from aurelius.backtesting.events.base import EventQueue
from aurelius.backtesting.events.types import (
    FillEvent,
    MarketEvent,
    OrderEvent,
    SignalEvent,
)
from aurelius.backtesting.execution.simulator import ExecutionSimulator
from aurelius.backtesting.oms.manager import OrderManager
from aurelius.backtesting.portfolio.manager import PortfolioManager
from aurelius.backtesting.portfolio.state import PortfolioState
from aurelius.backtesting.risk.engine import RiskEngine
from aurelius.backtesting.strategy.base import Strategy, StrategyContext
from aurelius.core.logging import get_logger

logger = get_logger(__name__)


class BacktestEngine:
    """Runs a single strategy backtest end-to-end."""

    def __init__(
        self,
        strategy: Strategy,
        data_feed: DataFeed,
        config: BacktestConfig | None = None,
        run_id: str | None = None,
    ) -> None:
        self._strategy = strategy
        self._feed = data_feed
        self._config = config or BacktestConfig()
        self._run_id = run_id or str(uuid.uuid4())

        # Core components
        self._portfolio_manager = PortfolioManager(self._config)
        self._simulator = ExecutionSimulator(self._config)
        self._oms = OrderManager()
        self._risk = RiskEngine(self._config)

        # State
        self._portfolio = PortfolioState(self._config.initial_capital)
        self._queue = EventQueue()
        self._pending_orders: list[OrderEvent] = []
        self._history: dict[str, deque] = {}
        self._equity_curve: list[EquityPoint] = []
        self._all_fills: list[FillEvent] = []
        self._bar_count = 0
        self._first_ts: datetime | None = None
        self._last_ts: datetime | None = None

    def run(self) -> BacktestReport:
        """Execute the full backtest. Returns a complete report."""
        logger.info(
            "backtest_start",
            strategy=self._strategy.name,
            run_id=self._run_id,
        )

        # Prime history deques
        for symbol in self._feed.symbols():
            self._history[symbol] = deque(maxlen=self._config.max_history_bars)

        # Initial context for on_start()
        ctx = self._make_context(datetime.now(UTC))
        self._strategy.on_start(ctx)

        for bar in self._feed.iter_bars():
            if self._config.start_date and bar.timestamp.date() < self._config.start_date:
                continue
            if self._config.end_date and bar.timestamp.date() > self._config.end_date:
                break
            if self._risk.is_halted:
                break

            self._process_bar(bar)
            self._bar_count += 1
            if self._first_ts is None:
                self._first_ts = bar.timestamp
            self._last_ts = bar.timestamp

        # Final signal (e.g., close all positions)
        if self._last_ts:
            ctx = self._make_context(self._last_ts)
            self._strategy.on_end(ctx)

        return self._build_report()

    # ── bar processing ────────────────────────────────────────────────────────

    def _process_bar(self, bar) -> None:
        # Step 1: Create FillEvents for pending orders (at this bar's open)
        still_pending: list[OrderEvent] = []
        for order in self._pending_orders:
            fill = self._simulator.try_fill(order, bar)
            if fill:
                self._queue.push(fill)
                # If partially filled, keep remainder
                if fill.quantity < order.quantity:
                    remainder = order.quantity - fill.quantity
                    # rebuild OrderEvent with reduced quantity
                    still_pending.append(OrderEvent(
                        timestamp=order.timestamp,
                        symbol=order.symbol,
                        order_type=order.order_type,
                        side=order.side,
                        quantity=remainder,
                        limit_price=order.limit_price,
                        stop_price=order.stop_price,
                        order_id=order.order_id,
                        strategy_id=order.strategy_id,
                    ))
            else:
                still_pending.append(order)

        self._pending_orders = still_pending

        # Step 2: Push MarketEvent for this bar
        market_event = MarketEvent(
            timestamp=bar.timestamp,
            symbol=bar.symbol,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            frequency=bar.frequency,
            vwap=bar.vwap,
        )
        self._queue.push(market_event)

        # Step 3: Drain the queue
        while not self._queue.empty():
            event = self._queue.pop()
            match type(event).__name__:
                case "FillEvent":
                    self._on_fill(event)
                case "MarketEvent":
                    self._on_market(event)
                case "SignalEvent":
                    self._on_signal(event)
                case "OrderEvent":
                    self._on_order(event)

        # Step 4: Record equity after all events settled
        self._portfolio.update_peak()
        self._equity_curve.append(
            EquityPoint(
                timestamp=bar.timestamp,
                equity=float(self._portfolio.total_value),
            )
        )

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_fill(self, fill: FillEvent) -> None:
        self._portfolio_manager.apply_fill(fill, self._portfolio)
        self._oms.apply_fill(fill)
        self._all_fills.append(fill)
        logger.debug(
            "fill",
            symbol=fill.symbol,
            side=fill.side,
            qty=str(fill.quantity),
            price=str(fill.fill_price),
            commission=str(fill.commission),
        )

    def _on_market(self, event: MarketEvent) -> None:
        # Update last price (unrealized P&L recalculates lazily via property)
        self._portfolio_manager.mark_to_market(event.symbol, event.close, self._portfolio)

        # Update history
        if event.symbol not in self._history:
            self._history[event.symbol] = deque(maxlen=self._config.max_history_bars)
        self._history[event.symbol].append(event)

        # Run strategy
        ctx = self._make_context(event.timestamp)
        signals = self._strategy.on_bar(ctx, event)
        for signal in signals:
            self._queue.push(signal)

    def _on_signal(self, signal: SignalEvent) -> None:
        order = self._portfolio_manager.size_order(signal, self._portfolio)
        if order is not None:
            self._queue.push(order)

    def _on_order(self, order: OrderEvent) -> None:
        result = self._risk.check(order, self._portfolio)
        if result.passed:
            self._oms.submit(order)
            self._pending_orders.append(order)
        else:
            self._oms.reject(order, result.reason)
            logger.debug("order_rejected", symbol=order.symbol, reason=result.reason)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_context(self, now: datetime) -> StrategyContext:
        return StrategyContext(
            history=self._history,
            portfolio=self._portfolio,
            now=now,
            max_bars=self._config.max_history_bars,
        )

    def _build_report(self) -> BacktestReport:
        calc = PerformanceCalculator(
            risk_free_rate=self._config.risk_free_rate,
            trading_days=self._config.trading_days_per_year,
        )
        metrics = calc.compute(
            equity_curve=self._equity_curve,
            fills=self._all_fills,
            initial_capital=float(self._config.initial_capital),
        )

        symbols = self._feed.symbols()
        start = self._first_ts.date().isoformat() if self._first_ts else "unknown"
        end = self._last_ts.date().isoformat() if self._last_ts else "unknown"

        report = BacktestReport(
            strategy_name=self._strategy.name,
            strategy_parameters=self._strategy.parameters,
            run_id=self._run_id,
            symbols=symbols,
            start_date=start,
            end_date=end,
            total_bars=self._bar_count,
            initial_capital=float(self._config.initial_capital),
            commission_rate_bps=float(self._config.commission_rate * 10_000),
            spread_bps=float(self._config.spread_bps),
            slippage_bps=float(self._config.slippage_impact_bps),
            metrics=metrics,
        )

        logger.info(
            "backtest_complete",
            run_id=self._run_id,
            strategy=self._strategy.name,
            bars=self._bar_count,
            total_return=f"{metrics.total_return:.2%}",
            sharpe=f"{metrics.sharpe_ratio:.3f}",
            max_drawdown=f"{metrics.max_drawdown:.2%}",
        )

        return report
