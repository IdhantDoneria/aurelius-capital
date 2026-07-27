"""Phase-9 paper trading: run the whole stack continuously on live-style data.

    from aurelius.paper import PaperBroker, TradingEngine, TradeJournal, replay

    broker = PaperBroker(cash=Decimal("100000"), risk_engine=RiskEngine())
    journal = TradeJournal("./data/journal.jsonl")
    engine = TradingEngine(broker, journal, strategy=my_strategy,
                           checkpoint_path="./data/checkpoint.json")
    engine.run_forever(lambda: live_tick_source())   # never returns in production

How this differs from backtesting: the backtest is a pure, deterministic pass
over a fixed dataset that is thrown away at the end; this is a supervised,
crash-surviving, wall-clock loop that sees only the present, journals every
action, and must run unattended. Same broker/risk/execution contracts — only the
data source and the survival machinery change.
"""

from aurelius.paper.broker import OrderRequest, OrderResult, PaperBroker, Tick
from aurelius.paper.dashboard import build_snapshot, render_text
from aurelius.paper.engine import Health, TradingEngine, replay
from aurelius.paper.journal import TradeJournal

__all__ = [
    "Health",
    "OrderRequest",
    "OrderResult",
    "PaperBroker",
    "Tick",
    "TradeJournal",
    "TradingEngine",
    "build_snapshot",
    "demo",
    "render_text",
    "replay",
]


def demo() -> None:
    """Run a short deterministic replay through the full platform + asserts."""
    import tempfile
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from aurelius.backtesting.events.types import OrderType, Side
    from aurelius.risk import RiskEngine

    tmp = tempfile.mkdtemp()
    broker = PaperBroker(cash=Decimal("100000"), risk_engine=RiskEngine())
    journal = TradeJournal(f"{tmp}/journal.jsonl")

    # Strategy: buy 10 shares of AAA the first time we see it, then rest a limit.
    placed = {"done": False}

    def strat(tick: Tick, _broker: PaperBroker) -> list[OrderRequest]:
        if tick.symbol == "AAA" and not placed["done"]:
            placed["done"] = True
            return [OrderRequest("AAA", Side.BUY, Decimal("10"), OrderType.MARKET)]
        return []

    engine = TradingEngine(
        broker, journal, strategy=strat, checkpoint_path=f"{tmp}/checkpoint.json"
    )

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    ticks = [Tick(t0 + timedelta(seconds=i), "AAA", Decimal("100") + Decimal(i)) for i in range(20)]

    # A source that raises once, to exercise automatic restart.
    calls = {"n": 0}

    def source_factory():
        calls["n"] += 1
        if calls["n"] == 1:

            def boom():
                yield ticks[0]
                raise ConnectionError("feed dropped")

            return boom()
        return replay(ticks)

    engine.run_forever(source_factory, max_restarts=3, sleep=lambda _s: None)

    assert broker.state.position("AAA").quantity == Decimal("10")  # bought
    assert engine.health.restarts == 1  # recovered once
    assert engine.health.fills >= 1
    assert journal.read("fill")  # journalled
    print("paper demo ok:", render_text(engine, broker).splitlines()[1].strip())


if __name__ == "__main__":
    demo()
