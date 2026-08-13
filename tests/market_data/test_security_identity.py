"""Temporal Security Identity Layer — regression scenarios (AIDP M2).

Covers the corporate-identity events that break ticker-based research:
rename, ticker reuse, exchange migration, dual listing, ADR, delist, relist,
merger, spin-off, plus lookup/as-of/universe/backtest-compat paths.
"""

from __future__ import annotations

from datetime import date

import pytest

from mentisrex.market_data.identity import Security, SecurityMaster, make_security_id


@pytest.fixture
def sm() -> SecurityMaster:
    store = SecurityMaster(":memory:")
    yield store
    store.close()


def _sec(ticker: str, exchange: str, first: date, **kw) -> Security:
    return Security(
        security_id=make_security_id(
            isin=kw.get("isin"), figi=kw.get("figi"), ticker=ticker,
            exchange=exchange, first_date=first,
        ),
        ticker=ticker, exchange=exchange, **kw,
    )


def test_security_id_is_deterministic_and_listing_stable() -> None:
    # Same (ISIN, exchange) listing → same id regardless of ticker/date (re-ingest collapse).
    a = make_security_id(isin="US0378331005", figi=None, ticker="AAPL", exchange="XNAS", first_date=date(1980, 12, 12))
    b = make_security_id(isin="US0378331005", figi=None, ticker="APPLE", exchange="XNAS", first_date=date(2001, 1, 1))
    assert a == b
    # Different exchange = different listing of the same instrument → different id.
    c = make_security_id(isin="US0378331005", figi=None, ticker="AAPL", exchange="XNYS", first_date=date(1980, 12, 12))
    assert c != a


def test_ticker_rename(sm: SecurityMaster) -> None:
    s = _sec("FB", "XNAS", date(2012, 5, 18), isin="US30303M1027")
    sid = sm.register(s, valid_from=date(2012, 5, 18))
    sm.add_identity_change(sid, new_ticker="META", exchange="XNAS",
                           valid_from=date(2022, 6, 9), reason="rebrand")
    # Same entity across the rename.
    assert sm.resolve_as_of("FB", date(2015, 1, 1)) == sid
    assert sm.resolve_as_of("META", date(2023, 1, 1)) == sid
    assert sm.historical_identifier(sid, date(2015, 1, 1)) == "FB"
    assert sm.historical_identifier(sid, date(2023, 1, 1)) == "META"
    assert sm.current_identifier(sid) == "META"


def test_ticker_reuse_disjoint_periods_resolves_by_date(sm: SecurityMaster) -> None:
    old = _sec("GOOG", "XNAS", date(1998, 1, 1), isin="OLDGOOG00001")
    old_id = sm.register(old, valid_from=date(1998, 1, 1))
    sm.set_status(old_id, "delisted", as_of=date(2001, 1, 1))
    new = _sec("GOOG", "XNAS", date(2014, 4, 3), isin="US02079K1079")
    new_id = sm.register(new, valid_from=date(2014, 4, 3))
    assert old_id != new_id
    assert sm.resolve_as_of("GOOG", date(1999, 6, 1)) == old_id
    assert sm.resolve_as_of("GOOG", date(2015, 6, 1)) == new_id
    assert sm.resolve_as_of("GOOG", date(2008, 1, 1)) is None  # gap between the two
    assert set(sm.lookup_by_ticker("GOOG")) == {old_id, new_id}


def test_exchange_migration_keeps_security_id(sm: SecurityMaster) -> None:
    s = _sec("XYZ", "XASE", date(2005, 1, 1), isin="US_XYZ0000001")
    sid = sm.register(s, valid_from=date(2005, 1, 1))
    sm.add_identity_change(sid, new_ticker="XYZ", exchange="XNAS",
                           valid_from=date(2010, 1, 1), reason="uplisting")
    assert sm.resolve_as_of("XYZ", date(2006, 1, 1)) == sid
    assert sm.resolve_as_of("XYZ", date(2011, 1, 1)) == sid
    assert sm.lookup_by_security_id(sid).exchange == "XNAS"


def test_dual_listing_shares_isin(sm: SecurityMaster) -> None:
    isin = "GB00B03MLX29"  # Shell — LSE + Amsterdam
    a = _sec("RDSA", "XLON", date(2005, 1, 1), isin=isin, primary_listing=True)
    b = _sec("RDSA", "XAMS", date(2005, 1, 1), isin=isin, primary_listing=False)
    sm.register(a, valid_from=date(2005, 1, 1))
    sm.register(b, valid_from=date(2005, 1, 1))
    ids = sm.by_isin(isin)
    assert len(ids) == 2
    assert sm.lookup_by_security_id(ids[0]).primary_listing is True  # primary first


def test_adr_is_distinct_security(sm: SecurityMaster) -> None:
    ordinary = _sec("0700", "XHKG", date(2004, 6, 16), isin="KYG875721634")
    adr = _sec("TCEHY", "OTCM", date(2008, 1, 1), isin="US88032Q1094")
    oid = sm.register(ordinary, valid_from=date(2004, 6, 16))
    aid = sm.register(adr, valid_from=date(2008, 1, 1))
    assert oid != aid
    assert sm.resolve_as_of("TCEHY", date(2015, 1, 1)) == aid


def test_delist_then_relist(sm: SecurityMaster) -> None:
    s = _sec("DLST", "XNAS", date(2000, 1, 1), isin="US_DLST000001")
    sid = sm.register(s, valid_from=date(2000, 1, 1))
    sm.set_status(sid, "delisted", as_of=date(2003, 1, 1))
    assert sm.resolve_as_of("DLST", date(2001, 1, 1)) == sid
    assert sm.resolve_as_of("DLST", date(2004, 1, 1)) is None  # dark
    sm.add_identity_change(sid, new_ticker="DLST", exchange="XNAS",
                           valid_from=date(2006, 1, 1), reason="relisting")
    sm.set_status(sid, "active")
    assert sm.resolve_as_of("DLST", date(2007, 1, 1)) == sid


def test_merger_closes_acquired(sm: SecurityMaster) -> None:
    target = _sec("TGT1", "XNYS", date(1990, 1, 1), isin="US_TGT1000001")
    tid = sm.register(target, valid_from=date(1990, 1, 1))
    sm.set_status(tid, "merged", as_of=date(2015, 1, 1))
    assert sm.lookup_by_security_id(tid).status == "merged"
    assert sm.resolve_as_of("TGT1", date(2010, 1, 1)) == tid
    assert sm.resolve_as_of("TGT1", date(2016, 1, 1)) is None


def test_spinoff_creates_new_security(sm: SecurityMaster) -> None:
    parent = _sec("PRNT", "XNYS", date(1980, 1, 1), isin="US_PRNT000001")
    pid = sm.register(parent, valid_from=date(1980, 1, 1))
    spin = _sec("SPIN", "XNYS", date(2013, 7, 1), isin="US_SPIN000001")
    spid = sm.register(spin, valid_from=date(2013, 7, 1))
    assert pid != spid
    assert sm.resolve_as_of("SPIN", date(2012, 1, 1)) is None  # didn't exist pre-spin
    assert sm.resolve_as_of("SPIN", date(2014, 1, 1)) == spid


def test_research_universe_resolution_is_pit(sm: SecurityMaster) -> None:
    fb = _sec("FB", "XNAS", date(2012, 5, 18), isin="US30303M1027")
    fid = sm.register(fb, valid_from=date(2012, 5, 18))
    sm.add_identity_change(fid, new_ticker="META", exchange="XNAS",
                           valid_from=date(2022, 6, 9), reason="rebrand")
    aapl = _sec("AAPL", "XNAS", date(1980, 12, 12), isin="US0378331005")
    aid = sm.register(aapl, valid_from=date(1980, 12, 12))
    # A 2015 universe naming "FB" must map to the same entity a 2023 "META" does.
    u2015 = sm.resolve_universe(["FB", "AAPL"], date(2015, 1, 1))
    u2023 = sm.resolve_universe(["META", "AAPL"], date(2023, 1, 1))
    assert u2015 == {"FB": fid, "AAPL": aid}
    assert u2023 == {"META": fid, "AAPL": aid}


def test_backtest_compat_ticker_still_resolvable(sm: SecurityMaster) -> None:
    """Legacy engines pass tickers; the shim maps them without any rewrite."""
    s = _sec("AAA", "XNAS", date(2020, 1, 1), isin="US_AAA0000001")
    sid = sm.register(s, valid_from=date(2020, 1, 1))
    feed_symbols = ["AAA"]  # what a DuckDBDataFeed emits today
    resolved = sm.resolve_universe(feed_symbols, date(2020, 6, 1))
    assert resolved["AAA"] == sid
    assert sm.current_identifier(sid) == "AAA"
