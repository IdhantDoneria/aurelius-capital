"""PIT insider transaction regression (AIDP M5). All offline.

Filing-delay isolation, Form 4 parsing, amendment handling, SecurityMaster
identity mapping, and multi-insider cluster aggregation.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from mentisrex.market_data.identity import Security, SecurityMaster, make_security_id
from mentisrex.market_data.insiders import (
    InsiderEngine,
    InsiderStore,
    parse_form4,
)

SID = "AUR_TEST_0001"


def _form4_doc(name, shares, price, ad="A", owned=5000, code="P", officer=True):
    return {
        "issuer": {"issuerCik": "320193", "issuerTradingSymbol": "AAPL"},
        "reportingOwner": {"reportingOwnerId": {"rptOwnerName": name},
                           "reportingOwnerRelationship": {"isOfficer": officer, "officerTitle": "CEO"}},
        "nonDerivativeTable": {"nonDerivativeTransaction": {
            "transactionDate": {"value": "2026-01-01"},
            "transactionCoding": {"transactionCode": code},
            "transactionAmounts": {
                "transactionShares": {"value": shares},
                "transactionPricePerShare": {"value": price},
                "transactionAcquiredDisposedCode": {"value": ad}},
            "postTransactionAmounts": {"sharesOwnedFollowingTransaction": {"value": owned}},
            "ownershipNature": {"directOrIndirectOwnership": {"value": "D"}},
        }},
        "periodOfReport": "2026-01-01",
    }


@pytest.fixture
def store() -> InsiderStore:
    s = InsiderStore(":memory:")
    yield s
    s.close()


def _txn(**over):
    doc = _form4_doc(over.pop("name", "COOK TIMOTHY"), over.pop("shares", 1000),
                     over.pop("price", 150.0), ad=over.pop("ad", "A"),
                     owned=over.pop("owned", 5000), code=over.pop("code", "P"))
    rows = parse_form4(doc, accession=over.pop("accession", "a1"),
                       filing_date=over.pop("filing_date", date(2026, 1, 3)),
                       acceptance_datetime=over.pop("acceptance", datetime(2026, 1, 3, 18, 0, 0)),
                       security_id=SID, form_type=over.pop("form_type", "4"))
    return rows


# 1. filing-delay isolation ─────────────────────────────────────────────────────

def test_filing_delay_isolation(store: InsiderStore) -> None:
    store.write_transactions(_txn())  # trade 2026-01-01, accepted 2026-01-03 18:00
    assert store.transactions_as_of(SID, date(2026, 1, 2)) == []          # not yet public
    visible = store.transactions_as_of(SID, date(2026, 1, 4))
    assert len(visible) == 1 and visible[0]["transaction_code"] == "P"    # public now


def test_acceptance_gate_not_transaction_date(store: InsiderStore) -> None:
    # Same trade date, but accepted a day later than filing_date to prove the gate.
    store.write_transactions(_txn(acceptance=datetime(2026, 1, 3, 9, 0, 0)))
    # Query at 2026-01-03 08:00 — before acceptance → invisible even though tx date passed.
    assert store.transactions_as_of(SID, datetime(2026, 1, 3, 8, 0, 0)) == []
    assert len(store.transactions_as_of(SID, datetime(2026, 1, 3, 10, 0, 0))) == 1


# 2. Form 4 parsing ─────────────────────────────────────────────────────────────

def test_form4_parsing_fields(store: InsiderStore) -> None:
    rows = _txn(name="COOK TIMOTHY", shares=2000, price=175.0, ad="A", code="P")
    r = rows[0]
    assert r["insider_name"] == "COOK TIMOTHY"
    assert r["insider_role"] == "CEO" and r["insider_type"] == "officer"
    assert r["transaction_code"] == "P"
    assert r["shares"] == 2000 and r["price"] == 175.0
    assert r["value"] == 2000 * 175.0
    assert r["ownership_type"] == "direct"


def test_disposal_is_signed_negative(store: InsiderStore) -> None:
    rows = _txn(shares=500, price=100.0, ad="D", code="S")
    assert rows[0]["shares"] == -500          # disposal → negative
    assert rows[0]["value"] == 500 * 100.0    # value stays positive magnitude


# 3. amendment handling ──────────────────────────────────────────────────────────

def test_amendment_returns_latest(store: InsiderStore) -> None:
    # Original: 100 shares (accepted Jan 3). Amendment 4/A: 150 shares (accepted Jan 10).
    store.write_transactions(_txn(accession="a1", shares=100, owned=100,
                                  acceptance=datetime(2026, 1, 3, 18, 0, 0)))
    store.write_transactions(_txn(accession="a2", shares=150, owned=150, form_type="4/A",
                                  acceptance=datetime(2026, 1, 10, 18, 0, 0)))
    got = store.transactions_as_of(SID, date(2026, 1, 15))
    assert len(got) == 1 and got[0]["shares"] == 150        # amendment wins
    # But as known on Jan 5, only the original was public.
    early = store.transactions_as_of(SID, date(2026, 1, 5))
    assert len(early) == 1 and early[0]["shares"] == 100
    # Both rows preserved in the append-only ledger.
    assert len(store.latest_transactions(SID)) == 2


# 4. security identity mapping ────────────────────────────────────────────────────

def test_identity_mapping_through_security_master(store: InsiderStore) -> None:
    sm = SecurityMaster(":memory:")
    try:
        sid = make_security_id(isin="US0378331005", figi=None, ticker="AAPL", exchange="XNAS",
                               first_date=date(1980, 12, 12))
        sm.register(Security(security_id=sid, ticker="AAPL", exchange="XNAS", isin="US0378331005"),
                    valid_from=date(1980, 12, 12))
        rows = _txn()
        for r in rows:
            r["security_id"] = sid
        store.write_transactions(rows)
        eng = InsiderEngine(store, security_master=sm)
        resolved = eng.resolve_security("AAPL", date(2026, 1, 1))
        assert resolved == sid
        sig = eng.insider_signal_as_of(resolved, date(2026, 1, 4))
        assert sig.purchases == 1
    finally:
        sm.close()


# 5. multiple insiders / cluster buying ──────────────────────────────────────────

def test_cluster_buying_aggregation(store: InsiderStore) -> None:
    for i, name in enumerate(["COOK TIMOTHY", "MAESTRI LUCA", "OBRIEN DEIRDRE"]):
        store.write_transactions(_txn(name=name, accession=f"a{i}", shares=1000 * (i + 1), price=150.0))
    # one sale by a fourth insider
    store.write_transactions(_txn(name="WILLIAMS JEFF", accession="s1", shares=500, price=150.0,
                                  ad="D", code="S"))
    eng = InsiderEngine(store, cluster_threshold=3)
    sig = eng.insider_signal_as_of(SID, date(2026, 1, 4))
    assert sig.purchases == 3 and sig.sales == 1
    assert sig.insider_count == 3          # three distinct buyers
    assert sig.cluster_buy is True
    assert sig.buy_value == (1000 + 2000 + 3000) * 150.0
    assert sig.net_value == sig.buy_value - 500 * 150.0
