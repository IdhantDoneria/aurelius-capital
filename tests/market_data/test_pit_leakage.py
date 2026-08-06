"""Point-in-time leakage regression — proves audit finding P1.

The research DuckDB store holds vendor-adjusted closes (Yahoo auto_adjust=True)
with no known-as-of dimension and INSERT OR REPLACE semantics. When a split
happens *after* date D, a re-fetch restates the close for D. A point-in-time
query `cross_sectional(as_of=D)` then returns the restated (post-split) price —
future corporate-action information leaking into the past.

This test reproduces exactly that with the real DuckDBStore API. It is marked
xfail(strict) because the store cannot yet answer "price as known on D". When
Phase 1 (corp-action-aware, bitemporal store) lands, this must PASS — strict
xfail turns an accidental pass into a failure, forcing the marker's removal.

Run: pytest tests/market_data/test_pit_leakage.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from aurelius.market_data.storage.duckdb_store import DuckDBStore


def _bar(sym: str, day: int, close: str) -> dict:
    return {
        "symbol": sym,
        "timestamp": datetime(2020, 1, day, tzinfo=timezone.utc),
        "frequency": "1d",
        "open": Decimal(close),
        "high": Decimal(close),
        "low": Decimal(close),
        "close": Decimal(close),
        "volume": Decimal("1000"),
    }


@pytest.mark.xfail(
    strict=True,
    reason="P1: research store is not bitemporal; as_of query sees post-split "
    "restatement. Fixed by Phase 1 — remove this marker when it passes.",
)
def test_as_of_price_is_not_contaminated_by_a_later_split() -> None:
    store = DuckDBStore(":memory:")
    try:
        # As known on 2020-01-02: AAA traded at 100.
        store.write_bars([_bar("AAA", 2, "100")])
        as_known_on_jan2 = store.cross_sectional(as_of=date(2020, 1, 2))
        assert as_known_on_jan2[0]["close"] == Decimal("100")

        # 2020-01-10: 2:1 split. Yahoo (auto_adjust) restates ALL prior closes
        # to 50 on the next fetch. Re-ingest overwrites the 2020-01-02 row.
        store.write_bars([_bar("AAA", 2, "50"), _bar("AAA", 10, "50")])

        # A point-in-time query for 2020-01-02 must still reflect what was known
        # THEN (100), not the post-split restatement (50). It currently returns 50.
        as_of_jan2 = store.cross_sectional(as_of=date(2020, 1, 2))
        assert as_of_jan2[0]["close"] == Decimal("100"), (
            "PIT leak: as_of=2020-01-02 returned the post-split restated price"
        )
    finally:
        store.close()
