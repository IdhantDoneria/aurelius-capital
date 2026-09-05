"""PIT survivorship-free universe regression (AIDP M4). Offline.

Scenarios: future-IPO invisibility, delisted-security preservation, ticker
migration, merger exclusion, and future-delisting isolation.
"""

from __future__ import annotations

from datetime import date

import pytest

from mentisrex.market_data.delistings import DelistingEvent, DelistingStore
from mentisrex.market_data.identity import Security, SecurityMaster, make_security_id
from mentisrex.market_data.universe import UniverseEngine


def _register(sm: SecurityMaster, ticker: str, exchange: str, first: date, isin: str) -> str:
    sid = make_security_id(isin=isin, figi=None, ticker=ticker, exchange=exchange, first_date=first)
    sm.register(
        Security(security_id=sid, ticker=ticker, exchange=exchange, isin=isin), valid_from=first
    )
    return sid


@pytest.fixture
def stores():
    sm = SecurityMaster(":memory:")
    dl = DelistingStore(":memory:")
    yield sm, dl, UniverseEngine(sm, delisting_store=dl)
    sm.close()
    dl.close()


def _tickers(snap) -> set[str]:
    return {s["ticker"] for s in snap.securities}


def test_future_ipo_is_invisible(stores) -> None:
    sm, _dl, eng = stores
    _register(sm, "NEW", "XNAS", date(2022, 1, 1), "US_NEW0000001")
    assert _tickers(eng.universe_as_of(date(2020, 6, 30))) == set()  # before IPO
    assert "NEW" in _tickers(eng.universe_as_of(date(2023, 1, 1)))  # after IPO


def test_delisted_security_preserved_then_absent(stores) -> None:
    sm, dl, eng = stores
    sid = _register(sm, "DEAD", "XNAS", date(2005, 1, 1), "US_DEAD000001")
    dl.record(
        DelistingEvent(
            security_id=sid,
            effective_date=date(2015, 6, 1),
            delisting_type="BANKRUPTCY",
            vendor="test",
            source="unit",
        )
    )
    dl.apply_to_master(sm)
    assert "DEAD" in _tickers(eng.universe_as_of(date(2010, 1, 1)))  # alive in 2010
    assert "DEAD" not in _tickers(eng.universe_as_of(date(2020, 1, 1)))  # gone by 2020


def test_ticker_migration_historical_vs_current(stores) -> None:
    sm, _dl, eng = stores
    sid = _register(sm, "ABC", "XNAS", date(2005, 1, 1), "US_ABC0000001")
    sm.add_identity_change(
        sid, new_ticker="XYZ", exchange="XNAS", valid_from=date(2018, 1, 1), reason="rebrand"
    )
    assert "ABC" in _tickers(eng.universe_as_of(date(2010, 1, 1)))  # historical name
    assert "XYZ" not in _tickers(eng.universe_as_of(date(2010, 1, 1)))
    assert "XYZ" in _tickers(eng.universe_as_of(date(2020, 1, 1)))  # current name
    assert "ABC" not in _tickers(eng.universe_as_of(date(2020, 1, 1)))


def test_merger_excludes_after_effective(stores) -> None:
    sm, dl, eng = stores
    sid = _register(sm, "TGT", "XNYS", date(1990, 1, 1), "US_TGT0000001")
    dl.record(
        DelistingEvent(
            security_id=sid,
            effective_date=date(2015, 1, 1),
            delisting_type="MERGER",
            reason="acquired",
            vendor="test",
        )
    )
    dl.apply_to_master(sm)
    assert "TGT" in _tickers(eng.universe_as_of(date(2014, 1, 1)))  # before merger
    assert "TGT" not in _tickers(eng.universe_as_of(date(2016, 1, 1)))  # after merger
    assert sm.lookup_by_security_id(sid).status == "merged"


def test_future_delisting_does_not_affect_history(stores) -> None:
    sm, dl, eng = stores
    sid = _register(sm, "LIVE", "XNAS", date(2000, 1, 1), "US_LIVE000001")
    before = _tickers(eng.universe_as_of(date(2010, 1, 1)))
    assert "LIVE" in before
    # A delisting effective in 2022 is recorded; the 2010 universe must not change.
    dl.record(
        DelistingEvent(
            security_id=sid,
            effective_date=date(2022, 1, 1),
            delisting_type="EXCHANGE_DELIST",
            vendor="test",
        )
    )
    dl.apply_to_master(sm)
    assert _tickers(eng.universe_as_of(date(2010, 1, 1))) == before  # unchanged
    assert "LIVE" not in _tickers(eng.universe_as_of(date(2023, 1, 1)))  # gone after 2022


def test_exclusions_distinguish_ipo_from_delisting(stores) -> None:
    sm, dl, eng = stores
    dead = _register(sm, "OLD", "XNAS", date(2000, 1, 1), "US_OLD0000001")
    _register(sm, "FUT", "XNAS", date(2025, 1, 1), "US_FUT0000001")
    dl.record(
        DelistingEvent(
            security_id=dead,
            effective_date=date(2008, 1, 1),
            delisting_type="LIQUIDATION",
            vendor="test",
        )
    )
    dl.apply_to_master(sm)
    snap = eng.universe_as_of(date(2015, 1, 1), with_exclusions=True)
    reasons = {e["ticker"]: e["exclusion_reason"] for e in snap.exclusions}
    assert reasons["OLD"] == "delisted"
    assert reasons["FUT"] == "not_yet_listed"
