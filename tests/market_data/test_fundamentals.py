"""PIT fundamentals regression scenarios (AIDP M3). All offline.

Covers the filing-timeline hazards that leak future information into factor
models: delayed filings, amendments/restatements, duplicates, chronology, plus
the tri-phase PIT market-cap path (SecurityMaster → PitPriceStore → Fundamentals).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from mentisrex.market_data.fundamentals import (
    FundamentalsEngine,
    FundamentalsStore,
    check,
    parse_company_facts,
)
from mentisrex.market_data.identity import Security, SecurityMaster, make_security_id
from mentisrex.market_data.storage.pit_store import PitPriceStore

CIK = "320193"


def _fact(concept, unit, end, val, accn, filed, form="10-K", fp="FY", start=None):
    return {
        "cik": CIK,
        "security_id": None,
        "taxonomy": "us-gaap",
        "concept": concept,
        "unit": unit,
        "period_start": start,
        "period_end": end,
        "fiscal_year": end.year,
        "fiscal_period": fp,
        "value": float(val),
        "form": form,
        "accession": accn,
        "filing_date": filed,
        "frame": None,
    }


@pytest.fixture
def store() -> FundamentalsStore:
    s = FundamentalsStore(":memory:")
    yield s
    s.close()


# ── EDGAR parsing ──────────────────────────────────────────────────────────────


def test_parse_company_facts_preserves_restatements() -> None:
    doc = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2019-09-28",
                                "val": 338516000000,
                                "accn": "a1",
                                "fy": 2019,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2019-10-31",
                            },
                            {
                                "end": "2019-09-28",
                                "val": 338000000000,
                                "accn": "a2",
                                "fy": 2019,
                                "fp": "FY",
                                "form": "10-K/A",
                                "filed": "2020-02-01",
                            },
                        ]
                    }
                }
            }
        },
    }
    facts, filings = parse_company_facts(doc)
    assert len(facts) == 2  # both filings kept — restatement preserved
    assert len(filings) == 2
    assert facts[0]["cik"] == "320193"


# ── point-in-time core ──────────────────────────────────────────────────────────


def test_delayed_filing_not_visible_before_filed(store: FundamentalsStore) -> None:
    # FY2019 period ends 2019-09-28 but is only filed 2019-10-31.
    store.write_facts(
        [_fact("StockholdersEquity", "USD", date(2019, 9, 28), 90488e6, "a1", date(2019, 10, 31))]
    )
    eng = FundamentalsEngine(store)
    # Query as-of 2019-10-15: period ended, but not yet filed → invisible.
    assert eng.book_value_as_of(CIK, date(2019, 10, 15)) is None
    # As-of 2019-11-01: filed → visible.
    assert eng.book_value_as_of(CIK, date(2019, 11, 1)) == 90488e6


def test_restatement_knowledge_date(store: FundamentalsStore) -> None:
    store.write_facts(
        [
            _fact("Assets", "USD", date(2019, 9, 28), 338516e6, "a1", date(2019, 10, 31)),
            _fact(
                "Assets", "USD", date(2019, 9, 28), 338000e6, "a2", date(2020, 2, 1), form="10-K/A"
            ),
        ]
    )
    eng = FundamentalsEngine(store)
    # As known on 2019-12-01: only the original filing exists.
    assert eng.fundamental_as_of(CIK, "assets", date(2019, 12, 1)) == 338516e6
    # As known on 2020-03-01: the amendment is in effect.
    assert eng.fundamental_as_of(CIK, "assets", date(2020, 3, 1)) == 338000e6
    # Explicit knowledge_date overrides as_of: "what did we know then?"
    assert (
        eng.fundamental_as_of(CIK, "assets", date(2020, 3, 1), knowledge_date=date(2019, 12, 1))
        == 338516e6
    )


def test_no_future_filing_leaks(store: FundamentalsStore) -> None:
    store.write_facts(
        [
            _fact("NetIncomeLoss", "USD", date(2018, 9, 29), 59531e6, "a0", date(2018, 11, 5)),
            _fact("NetIncomeLoss", "USD", date(2019, 9, 28), 55256e6, "a1", date(2019, 10, 31)),
        ]
    )
    eng = FundamentalsEngine(store)
    # As-of mid-2019: only FY2018 is known; FY2019 hasn't been filed.
    assert eng.fundamental_as_of(CIK, "net_income", date(2019, 6, 1)) == 59531e6


def test_duplicate_filing_detected(store: FundamentalsStore) -> None:
    store.write_facts(
        [
            _fact("Assets", "USD", date(2019, 9, 28), 338516e6, "a1", date(2019, 10, 31)),
            _fact(
                "Assets", "USD", date(2019, 9, 28), 338516e6, "a1b", date(2019, 10, 31)
            ),  # same value, 2 accns
        ]
    )
    rep = check(store, CIK)
    assert rep.duplicate_facts >= 1


def test_negative_shares_and_missing_required(store: FundamentalsStore) -> None:
    store.write_facts(
        [
            _fact(
                "CommonStockSharesOutstanding",
                "shares",
                date(2019, 9, 28),
                -100,
                "a1",
                date(2019, 10, 31),
            )
        ]
    )
    rep = check(store, CIK)
    assert rep.negative_shares == 1
    assert "Assets" in rep.missing_required
    assert rep.passed is False


def test_cross_section_as_of_matches_per_cik_and_is_pit(store: FundamentalsStore) -> None:
    store.write_facts(
        [
            _fact("Assets", "USD", date(2019, 9, 28), 100.0, "a1", date(2019, 10, 31)),
            {
                **_fact("Assets", "USD", date(2019, 9, 28), 200.0, "b1", date(2019, 10, 31)),
                "cik": "999",
            },
            # a future filing that must not leak into a 2019 cross-section:
            {
                **_fact("Assets", "USD", date(2020, 9, 28), 300.0, "b2", date(2020, 10, 31)),
                "cik": "999",
            },
        ]
    )
    xs = store.cross_section_as_of("Assets", date(2019, 12, 1))
    assert xs == {CIK: 100.0, "999": 200.0}  # 999's 2020 filing excluded


def test_series_as_of_takes_latest_restatement(store: FundamentalsStore) -> None:
    store.write_facts(
        [
            _fact("Assets", "USD", date(2018, 9, 29), 365725e6, "a0", date(2018, 11, 5)),
            _fact("Assets", "USD", date(2019, 9, 28), 338516e6, "a1", date(2019, 10, 31)),
            _fact("Assets", "USD", date(2019, 9, 28), 338000e6, "a2", date(2020, 2, 1)),
        ]
    )
    s = store.series_as_of(CIK, "Assets", date(2020, 3, 1))
    assert [r["value"] for r in s] == [365725e6, 338000e6]  # 2019 uses the amendment


# ── tri-phase PIT market cap (M1 + 2 + 3) ──────────────────────────────────


def _bar(ticker, day, close):
    c = Decimal(str(close))
    return {
        "symbol": ticker,
        "timestamp": datetime(2019, 11, day, tzinfo=UTC),
        "frequency": "1d",
        "open": c,
        "high": c,
        "low": c,
        "close": c,
        "volume": Decimal("1000"),
    }


def test_pit_market_cap_and_enterprise_value(store: FundamentalsStore) -> None:
    prices = PitPriceStore(":memory:")
    try:
        store.write_facts(
            [
                _fact(
                    "CommonStockSharesOutstanding",
                    "shares",
                    date(2019, 9, 28),
                    4_600_000_000,
                    "a1",
                    date(2019, 10, 31),
                ),
                _fact("LongTermDebt", "USD", date(2019, 9, 28), 92_000e6, "a1", date(2019, 10, 31)),
                _fact(
                    "CashAndCashEquivalentsAtCarryingValue",
                    "USD",
                    date(2019, 9, 28),
                    48_000e6,
                    "a1",
                    date(2019, 10, 31),
                ),
            ]
        )
        prices.write_raw_bars([_bar("AAPL", 15, "65")])
        eng = FundamentalsEngine(store, price_store=prices)
        mc = eng.market_cap_as_of(CIK, date(2019, 11, 20), ticker="AAPL")
        assert mc == 4_600_000_000 * 65.0
        ev = eng.enterprise_value_as_of(CIK, date(2019, 11, 20), ticker="AAPL")
        assert ev == mc + 92_000e6 - 48_000e6
        # Before shares were filed: no market cap.
        assert eng.market_cap_as_of(CIK, date(2019, 10, 1), ticker="AAPL") is None
    finally:
        prices.close()


def test_market_cap_resolves_pit_ticker_from_security_master(store: FundamentalsStore) -> None:
    prices = PitPriceStore(":memory:")
    sm = SecurityMaster(":memory:")
    try:
        # Security traded as OLD in 2019, renamed NEW later. security_id is stable.
        sid = make_security_id(
            isin="US0000000001",
            figi=None,
            ticker="OLD",
            exchange="XNAS",
            first_date=date(2019, 1, 1),
        )
        sm.register(
            Security(security_id=sid, ticker="OLD", exchange="XNAS", isin="US0000000001"),
            valid_from=date(2019, 1, 1),
        )
        store.write_facts(
            [
                _fact(
                    "CommonStockSharesOutstanding",
                    "shares",
                    date(2019, 9, 28),
                    1_000_000,
                    "a1",
                    date(2019, 10, 31),
                )
            ]
        )
        prices.write_raw_bars([_bar("OLD", 15, "10")])
        eng = FundamentalsEngine(store, price_store=prices, security_master=sm)
        # Only security_id given → engine resolves the 2019 ticker (OLD) itself.
        mc = eng.market_cap_as_of(CIK, date(2019, 11, 20), security_id=sid)
        assert mc == 1_000_000 * 10.0
    finally:
        prices.close()
        sm.close()


def test_factor_inputs_are_pit(store: FundamentalsStore) -> None:
    prices = PitPriceStore(":memory:")
    try:
        store.write_facts(
            [
                _fact(
                    "StockholdersEquity",
                    "USD",
                    date(2019, 9, 28),
                    90_000e6,
                    "a1",
                    date(2019, 10, 31),
                ),
                _fact("Assets", "USD", date(2019, 9, 28), 338_000e6, "a1", date(2019, 10, 31)),
                _fact(
                    "NetIncomeLoss", "USD", date(2019, 9, 28), 55_000e6, "a1", date(2019, 10, 31)
                ),
                _fact("Revenues", "USD", date(2019, 9, 28), 260_000e6, "a1", date(2019, 10, 31)),
                _fact(
                    "CommonStockSharesOutstanding",
                    "shares",
                    date(2019, 9, 28),
                    4_600_000_000,
                    "a1",
                    date(2019, 10, 31),
                ),
            ]
        )
        prices.write_raw_bars([_bar("AAPL", 15, "65")])
        eng = FundamentalsEngine(store, price_store=prices)
        fi = eng.factor_inputs_as_of(CIK, date(2019, 11, 20), ticker="AAPL")
        assert fi["roe"] == pytest.approx(55_000e6 / 90_000e6)
        assert fi["roa"] == pytest.approx(55_000e6 / 338_000e6)
        assert fi["book_to_market"] == pytest.approx(90_000e6 / (4_600_000_000 * 65.0))
        # Nothing is known before the filing date.
        empty = eng.factor_inputs_as_of(CIK, date(2019, 10, 1), ticker="AAPL")
        assert empty["roe"] is None
        assert empty["market_cap"] is None
    finally:
        prices.close()
