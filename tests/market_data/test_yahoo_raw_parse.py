"""parse_raw_history + PIT store round-trip — Phase 1 wiring, no network.

Feeds a synthetic yfinance-shaped frame (auto_adjust=False, actions=True) through
the parser into PitPriceStore and asserts the as-of price is PIT-correct across a
split. This is the end-to-end check for the Yahoo → PIT ingest path.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from aurelius.market_data.adapters.yahoo import parse_raw_history
from aurelius.market_data.storage.pit_store import PitPriceStore


def _frame() -> pd.DataFrame:
    # Raw (unadjusted) closes: 100 on 01-02, then a 2:1 split on 01-10 (raw 50 after).
    idx = pd.to_datetime(["2020-01-02", "2020-01-10"])
    return pd.DataFrame(
        {
            "Open": [100.0, 50.0], "High": [100.0, 50.0], "Low": [100.0, 50.0],
            "Close": [100.0, 50.0], "Volume": [1000, 1000],
            "Dividends": [0.0, 0.0], "Stock Splits": [0.0, 2.0],
        },
        index=idx,
    )


def test_parse_extracts_raw_bars_and_split() -> None:
    bars, actions = parse_raw_history(_frame(), "aapl")
    assert len(bars) == 2
    assert bars[0]["symbol"] == "AAPL" and bars[0]["close"] == Decimal("100")
    assert len(actions) == 1
    assert actions[0]["effective_date"] == date(2020, 1, 10)
    assert actions[0]["ratio"] == 2.0
    assert actions[0]["announced_date"] == date(2020, 1, 10)  # = effective (Yahoo limitation)


def test_parsed_data_is_pit_correct_end_to_end() -> None:
    bars, actions = parse_raw_history(_frame(), "AAPL")
    store = PitPriceStore(":memory:")
    try:
        store.write_raw_bars(bars)
        store.record_actions(actions)
        # Before the split is known: 01-02 close is its raw 100.
        assert store.close_as_of("AAPL", date(2020, 1, 5)) == Decimal("100")
        # After: the 01-10 bar (raw 50) is the latest; no split after it → 50.
        assert store.close_as_of("AAPL", date(2020, 1, 15)) == Decimal("50")
    finally:
        store.close()
