"""Point-in-time leakage regression — audit finding P1, and its M1 fix.

The legacy DuckDBStore holds vendor-adjusted closes (Yahoo auto_adjust=True) with
INSERT OR REPLACE and no known-as-of dimension: a split after date D silently
restates the close for D, leaking a future corporate action into the past.

`test_legacy_path_leaks` pins that hazard so it can't be "fixed" in place without
someone noticing (the legacy path stays for back-compat; PIT-correct reads move
to PitPriceStore). `test_pit_store_is_leak_free` proves the fix.

Run: pytest tests/market_data/test_pit_leakage.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from aurelius.market_data.storage.duckdb_store import DuckDBStore
from aurelius.market_data.storage.pit_store import PitPriceStore


def _bar(day: int, close: str) -> dict:
    ts = datetime(2020, 1, day, tzinfo=timezone.utc)
    c = Decimal(close)
    return {
        "symbol": "AAA", "timestamp": ts, "frequency": "1d",
        "open": c, "high": c, "low": c, "close": c, "volume": Decimal("1000"),
    }


def test_legacy_path_leaks() -> None:
    """Documents the hazard: adjusted-in-place store restates the past."""
    store = DuckDBStore(":memory:")
    try:
        store.write_bars([_bar(2, "100")])
        assert store.cross_sectional(as_of=date(2020, 1, 2))[0]["close"] == Decimal("100")
        # 2:1 split on 2020-01-10 → Yahoo restates the 01-02 close to 50 on re-fetch.
        store.write_bars([_bar(2, "50"), _bar(10, "50")])
        leaked = store.cross_sectional(as_of=date(2020, 1, 2))[0]["close"]
        assert leaked == Decimal("50"), "legacy path unexpectedly PIT-safe — use PitPriceStore"
    finally:
        store.close()


def test_pit_store_is_leak_free() -> None:
    """The fix: raw prices + split events, adjusted on read with an as-of horizon."""
    store = PitPriceStore(":memory:")
    try:
        # Immutable RAW price, ingested once — never restated.
        store.write_raw_bars([_bar(2, "100")])
        store.record_actions([
            {"symbol": "AAA", "effective_date": date(2020, 1, 10),
             "ratio": 2, "announced_date": date(2020, 1, 10)},
        ])

        # As-of 2020-01-02: the split (effective 01-10) is in the future → not applied.
        assert store.close_as_of("AAA", date(2020, 1, 2)) == Decimal("100")

        # As-of 2020-01-15: the 01-02 bar is back-adjusted by the 2:1 split → 50.
        assert store.close_as_of("AAA", date(2020, 1, 15)) == Decimal("50")

        # Knowledge-date guard: even at as_of 01-15, if we only knew up to 01-05,
        # the split (announced 01-10) is unknown → no adjustment.
        assert store.close_as_of("AAA", date(2020, 1, 15), knowledge_date=date(2020, 1, 5)) == Decimal("100")
    finally:
        store.close()
