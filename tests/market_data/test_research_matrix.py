"""PIT research matrix regression (AIDP Phase 6). All offline.

Cross-source PIT isolation (fundamentals + insiders), survivorship-free universe,
identity migration, reproducibility, and missing-data tolerance — all composed
over the five certified engines with in-memory stores.
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pytest

from aurelius.market_data.fundamentals import FundamentalsEngine, FundamentalsStore
from aurelius.market_data.identity import Security, SecurityMaster, make_security_id
from aurelius.market_data.insiders import InsiderEngine, InsiderStore, parse_form4
from aurelius.market_data.research_matrix import ResearchMatrixEngine, check
from aurelius.market_data.storage.pit_store import PitPriceStore
from aurelius.market_data.universe import UniverseEngine

CIK = "320193"


def _fact(concept, value, period_end, filing_date, accession):
    return {"cik": CIK, "taxonomy": "us-gaap", "concept": concept, "unit": "USD",
            "period_end": period_end, "value": value, "form": "10-K",
            "accession": accession, "filing_date": filing_date}


def _form4_doc(name, shares, price, code, ad):
    return {
        "issuer": {"issuerCik": CIK, "issuerTradingSymbol": "AAPL"},
        "reportingOwner": {"reportingOwnerId": {"rptOwnerName": name},
                           "reportingOwnerRelationship": {"isOfficer": True, "officerTitle": "CEO"}},
        "nonDerivativeTable": {"nonDerivativeTransaction": {
            "transactionDate": {"value": "2020-06-01"},
            "transactionCoding": {"transactionCode": code},
            "transactionAmounts": {
                "transactionShares": {"value": shares},
                "transactionPricePerShare": {"value": price},
                "transactionAcquiredDisposedCode": {"value": ad}},
            "postTransactionAmounts": {"sharesOwnedFollowingTransaction": {"value": 10000}},
            "ownershipNature": {"directOrIndirectOwnership": {"value": "D"}},
        }},
        "periodOfReport": "2020-06-01",
    }


@pytest.fixture
def rig():
    """Wire the five engines over in-memory stores; seed one live security (AAPL)."""
    prices = PitPriceStore(":memory:")
    fstore = FundamentalsStore(":memory:")
    istore = InsiderStore(":memory:")
    sm = SecurityMaster(":memory:")

    sid = make_security_id(isin="US0378331005", figi=None, ticker="AAPL",
                           exchange="XNAS", first_date=date(1980, 12, 12))
    sm.register(Security(security_id=sid, ticker="AAPL", exchange="XNAS", isin="US0378331005"),
                valid_from=date(1980, 12, 12))

    # Prices: two bars so returns/volatility are computable.
    prices.write_raw_bars([
        {"symbol": "AAPL", "timestamp": datetime(2020, 6, 29), "frequency": "1d",
         "open": 90, "high": 92, "low": 89, "close": 90.0, "volume": 1000, "source": "t"},
        {"symbol": "AAPL", "timestamp": datetime(2020, 6, 30), "frequency": "1d",
         "open": 91, "high": 96, "low": 90, "close": 95.0, "volume": 2000, "source": "t"},
    ])

    fund = FundamentalsEngine(fstore, price_store=prices, security_master=sm)
    ins = InsiderEngine(istore, security_master=sm, cluster_threshold=3)
    uni = UniverseEngine(sm)
    eng = ResearchMatrixEngine(universe=uni, fundamentals=fund, insiders=ins,
                               prices=prices, cik_map={sid: CIK})
    yield {"eng": eng, "sm": sm, "sid": sid, "prices": prices, "fstore": fstore,
           "istore": istore, "fund": fund, "ins": ins, "uni": uni}
    for s in (prices, fstore, istore, sm):
        s.close()


# 1. cross-source PIT isolation — future fundamental filing ───────────────────────

def test_future_fundamental_not_visible(rig):
    # Q1 equity, period end Mar 31 2020, but FILED May 10 2020.
    rig["fstore"].write_facts([_fact("StockholdersEquity", 5e11, "2020-03-31", "2020-05-10", "a1")])
    sid = rig["sid"]
    before = rig["eng"].feature_matrix_as_of(date(2020, 4, 30), features=["book_value"])
    assert before.frame.loc[sid, "book_value"] is None or math.isnan(_num(before.frame.loc[sid, "book_value"]))
    after = rig["eng"].feature_matrix_as_of(date(2020, 5, 11), features=["book_value"])
    assert _num(after.frame.loc[sid, "book_value"]) == 5e11


# 2. future insider filing not visible ────────────────────────────────────────────

def test_future_insider_not_visible(rig):
    # Trade Jun 1, accepted Jun 3 18:00.
    rows = parse_form4(_form4_doc("COOK", 1000, 150.0, "P", "A"), accession="i1",
                       filing_date=date(2020, 6, 3),
                       acceptance_datetime=datetime(2020, 6, 3, 18, 0, 0),
                       security_id=rig["sid"])
    rig["istore"].write_transactions(rows)
    sid = rig["sid"]
    m2 = rig["eng"].feature_matrix_as_of(date(2020, 6, 2), features=["insider_buy_value"])
    assert _num(m2.frame.loc[sid, "insider_buy_value"]) == 0.0        # not yet public
    m4 = rig["eng"].feature_matrix_as_of(date(2020, 6, 4), features=["insider_buy_value"])
    assert _num(m4.frame.loc[sid, "insider_buy_value"]) == 1000 * 150.0


# 3. survivorship-free universe — delisted then vs now ────────────────────────────

def test_delisted_included_historically_excluded_now(rig):
    sm = rig["sm"]
    dead = make_security_id(isin="US_DEAD", figi=None, ticker="DEAD",
                            exchange="XNYS", first_date=date(2005, 1, 1))
    sm.register(Security(security_id=dead, ticker="DEAD", exchange="XNYS"),
                valid_from=date(2005, 1, 1))
    sm.set_status(dead, "delisted", as_of=date(2016, 1, 1))  # closes interval

    hist = rig["eng"].feature_matrix_as_of(date(2010, 1, 1), features=["close"])
    assert dead in hist.frame.index                    # alive in 2010 → present
    now = rig["eng"].feature_matrix_as_of(date(2020, 1, 1), features=["close"])
    assert dead not in now.frame.index                 # delisted by 2020 → absent


# 4. identity migration resolves correctly ────────────────────────────────────────

def test_identity_migration(rig):
    sm, sid = rig["sm"], rig["sid"]
    # AAPL renamed → APPL2 on 2021-01-01. Price bars are keyed by the PIT ticker.
    sm.add_identity_change(sid, new_ticker="APPL2", exchange="XNAS",
                           valid_from=date(2021, 1, 1), reason="rename")
    rig["prices"].write_raw_bars([
        {"symbol": "APPL2", "timestamp": datetime(2021, 6, 30), "frequency": "1d",
         "open": 100, "high": 101, "low": 99, "close": 120.0, "volume": 500, "source": "t"},
    ])
    # 2020: universe row carries ticker AAPL → old bars.
    m2020 = rig["eng"].feature_matrix_as_of(date(2020, 6, 30), features=["close"])
    assert _num(m2020.frame.loc[sid, "close"]) == 95.0
    # 2021: universe row carries ticker APPL2 → new bars, same security_id.
    m2021 = rig["eng"].feature_matrix_as_of(date(2021, 6, 30), features=["close"])
    assert _num(m2021.frame.loc[sid, "close"]) == 120.0


# 5. reproducibility — same inputs, same matrix ───────────────────────────────────

def test_reproducibility(rig):
    a = rig["eng"].feature_matrix_as_of(date(2020, 6, 30))
    b = rig["eng"].feature_matrix_as_of(date(2020, 6, 30))
    assert a.frame.equals(b.frame)
    assert a.data_versions == b.data_versions
    # cache hit returns the identical object
    assert a is b


# 6. missing data does not corrupt the matrix ─────────────────────────────────────

def test_missing_data_isolated(rig):
    sm = rig["sm"]
    # A second security with NO price/fundamental/insider data.
    empty = make_security_id(isin="US_EMPTY", figi=None, ticker="EMPT",
                             exchange="XNYS", first_date=date(2000, 1, 1))
    sm.register(Security(security_id=empty, ticker="EMPT", exchange="XNYS"),
                valid_from=date(2000, 1, 1))
    rig["fstore"].write_facts([_fact("StockholdersEquity", 1e9, "2019-12-31", "2020-02-01", "b1")])

    m = rig["eng"].feature_matrix_as_of(date(2020, 6, 30), features=["close", "book_value"])
    # AAPL has price + book value; EMPT has neither — its NaNs don't touch AAPL's row.
    assert _num(m.frame.loc[rig["sid"], "close"]) == 95.0
    assert _num(m.frame.loc[rig["sid"], "book_value"]) == 1e9
    assert _isnull(m.frame.loc[empty, "close"])
    rep = check(m)
    assert rep["ok"] and not rep["duplicate_ids"]
    assert rep["rows"] == 2


def _num(v):
    return float(v)


def _isnull(v):
    return v is None or (isinstance(v, float) and math.isnan(v))
