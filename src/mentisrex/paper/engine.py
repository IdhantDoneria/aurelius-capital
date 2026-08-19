"""TradingEngine — the supervised loop that runs the paper platform continuously.

This is everything a backtest loop is NOT built for:

  backtest loop                     paper/live loop (this)
  -----------------------------     -----------------------------------------
  iterate a fixed dataset fast      consume ticks in wall-clock real time
  pure function, rerun on crash     must SURVIVE crashes and keep running
  sees the whole series             sees only up to 'now' (no look-ahead, ever)
  deterministic (seed + data)       non-deterministic (live data + timing)
  state thrown away at the end       state checkpointed + journalled to disk

So the design centres on staying alive: a bad tick is caught and logged, never
fatal (error recovery); the outer supervisor restarts the data source on a
disconnect with backoff (automatic restart); health counters + heartbeats make
it observable (monitoring); an alert sink escalates errors/restarts (alerts);
and every action is journalled + checkpointed so a restart resumes cleanly.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from mentisrex.backtesting.analytics.performance import EquityPoint
from mentisrex.core.logging import get_logger
from mentisrex.paper.broker import OrderRequest, PaperBroker, Tick
from mentisrex.paper.journal import TradeJournal

logger = get_logger(__name__)

# (tick, broker) -> orders to place this tick. The seam for any Phase-8 strategy.
Strategy = Callable[[Tick, PaperBroker], list[OrderRequest]]
AlertSink = Callable[[str, str], None]  # (level, message)


def _log_alert(level: str, message: str) -> None:
    logger.warning("alert", level=level, message=message)


@dataclass
class Health:
    ticks: int = 0
    orders: int = 0
    fills: int = 0
    rejects: int = 0
    errors: int = 0
    restarts: int = 0
    last_tick_ts: str | None = None
    running: bool = False


class TradingEngine:
    def __init__(
        self,
        broker: PaperBroker,
        journal: TradeJournal,
        strategy: Strategy | None = None,
        alert: AlertSink | None = None,
        checkpoint_path: str | None = None,
        heartbeat_every: int = 100,
    ) -> None:
        self._broker = broker
        self._journal = journal
        self._strategy = strategy
        self._alert = alert or _log_alert
        self._checkpoint_path = checkpoint_path
        self._heartbeat_every = heartbeat_every
        self.health = Health()
        self.equity_curve: list[EquityPoint] = []

    # ── one cycle ──────────────────────────────────────────────────────────

    def process_tick(self, tick: Tick) -> None:
        """Handle a single tick. Any exception here is caught by run() — a bad
        tick must never kill the loop."""
        for fill in self._broker.on_tick(tick):  # resting limit fills
            self.health.fills += 1
            self._journal.record(
                "fill",
                symbol=fill.symbol,
                side=fill.side.value,
                qty=fill.quantity,
                price=fill.fill_price,
            )

        if self._strategy:
            for req in self._strategy(tick, self._broker):
                self.health.orders += 1
                res = self._broker.submit(req, now=tick.timestamp)
                if not res.accepted:
                    self.health.rejects += 1
                    self._journal.record("reject", symbol=req.symbol, reason=res.reason)
                    self._alert("warning", f"order rejected {req.symbol}: {res.reason}")
                elif res.fill is not None:
                    self.health.fills += 1
                    self._journal.record(
                        "fill",
                        symbol=res.fill.symbol,
                        side=res.fill.side.value,
                        qty=res.fill.quantity,
                        price=res.fill.fill_price,
                    )
                else:
                    self._journal.record("order", symbol=req.symbol, resting=res.resting)

        try:
            equity = float(self._broker.account()["equity"])
        except Exception:
            equity = float(getattr(getattr(self._broker, "state", None), "total_value", 0))
        self.equity_curve.append(EquityPoint(tick.timestamp, equity))
        self.health.ticks += 1
        self.health.last_tick_ts = tick.timestamp.isoformat()
        if self.health.ticks % self._heartbeat_every == 0:
            self._journal.record(
                "heartbeat", ticks=self.health.ticks, equity=equity
            )

    # ── run: error recovery per tick ──────────────────────────────────────────

    def run(self, source: Iterable[Tick]) -> None:
        """Consume a data source to exhaustion. A failure on one tick is logged,
        journalled and alerted, then the loop CONTINUES — capital keeps being
        tracked even when a single message is malformed."""
        self.health.running = True
        try:
            for tick in source:
                try:
                    self.process_tick(tick)
                except Exception as exc:
                    self.health.errors += 1
                    logger.exception("tick_error", symbol=getattr(tick, "symbol", "?"))
                    self._journal.record("error", where="process_tick", error=str(exc))
                    self._alert("error", f"tick error: {exc}")
        finally:
            self.health.running = False
            self.checkpoint()

    # ── run_forever: automatic restart of the data source ─────────────────────

    def run_forever(
        self,
        source_factory: Callable[[], Iterable[Tick]],
        max_restarts: int | None = None,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Supervisor: (re)connect the feed and run; on a source-level failure
        (disconnect), back off and restart. max_restarts bounds it for tests;
        None = truly continuous, the production default.

        ponytail: linear backoff, single feed. Add exponential backoff + a
        circuit breaker if a flapping feed becomes a real operational problem.
        """
        attempts = 0
        while True:
            try:
                self.run(source_factory())
                return  # source exhausted cleanly
            except Exception as exc:
                attempts += 1
                self.health.restarts += 1
                logger.exception("source_failure", attempt=attempts)
                self._journal.record("restart", attempt=attempts, error=str(exc))
                self._alert("critical", f"source failure #{attempts}: {exc}")
                if max_restarts is not None and attempts >= max_restarts:
                    self._alert("critical", "max restarts reached; supervisor giving up")
                    return
                sleep(backoff_seconds)

    # ── checkpoint / restore ──────────────────────────────────────────────────

    def checkpoint(self) -> None:
        if not self._checkpoint_path:
            return
        import json
        from pathlib import Path

        snap = {
            "health": asdict(self.health),
            "account": _jsonable_account(self._broker.account()),
            "saved_at": datetime.now(UTC).isoformat(),
        }
        Path(self._checkpoint_path).write_text(json.dumps(snap, indent=2))

    def health_snapshot(self) -> dict:
        return asdict(self.health)


def _jsonable_account(acc: dict) -> dict:
    from decimal import Decimal

    return {
        k: (
            float(v)
            if isinstance(v, Decimal)
            else {s: float(q) for s, q in v.items()}
            if isinstance(v, dict)
            else v
        )
        for k, v in acc.items()
    }


def replay(ticks: list[Tick]) -> Iterator[Tick]:
    """A finite in-memory data source (for demos/tests). A live source would be a
    generator yielding ticks off a websocket instead — the engine can't tell."""
    yield from ticks
