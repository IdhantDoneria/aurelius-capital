"""SEC EDGAR Form 3/4/5 → insider transaction rows (AIDP M5).

The parsers are pure: they take an already-parsed ownership document (dict, as
produced from the filing XML by e.g. xmltodict) plus the filing-level metadata
(accession / filing_date / acceptance_datetime come from the submission index,
NOT the XML body) and emit ledger rows. No network in tests.

Form semantics:
  Form 3 — initial statement of beneficial ownership (holdings, not trades)
  Form 4 — changes in ownership (the transaction workhorse; due within 2 biz days)
  Form 5 — annual statement of deferred/exempt transactions
Forms 4 and 5 share the transaction structure; Form 3 reports holdings only.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def _txn_id(accession: str, table: str, idx: int) -> str:
    return "INS" + hashlib.blake2b(f"{accession}|{table}|{idx}".encode(), digest_size=8).hexdigest()


def _v(node: Any, *path: str) -> Any:
    """Walk nested dicts unwrapping SEC's {'value': X} envelopes."""
    cur = node
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    if isinstance(cur, dict) and "value" in cur:
        return cur["value"]
    return cur


def _insider_meta(doc: dict) -> dict:
    owner = doc.get("reportingOwner") or {}
    rel = owner.get("reportingOwnerRelationship") or {}
    if rel.get("isOfficer") in (True, "true", "1"):
        itype, role = "officer", rel.get("officerTitle") or "officer"
    elif rel.get("isDirector") in (True, "true", "1"):
        itype, role = "director", "director"
    elif rel.get("isTenPercentOwner") in (True, "true", "1"):
        itype, role = "tenpercent", "10% owner"
    else:
        itype, role = "other", (rel.get("otherText") or "other")
    return {"insider_name": _v(owner, "reportingOwnerId", "rptOwnerName"),
            "insider_role": role, "insider_type": itype}


def _as_list(x: Any) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _base(doc: dict, *, accession: str, filing_date: date, acceptance_datetime: datetime,
          form_type: str, security_id: str | None) -> dict:
    cik = str(_v(doc, "issuer", "issuerCik") or "").lstrip("0") or str(_v(doc, "issuer", "issuerCik") or "")
    return {"security_id": security_id, "cik": cik, **_insider_meta(doc),
            "filing_date": filing_date, "acceptance_datetime": acceptance_datetime,
            "accession": accession, "form_type": form_type,
            "source": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"}


def _parse_transactions(doc: dict, form_type: str, **meta: Any) -> list[dict]:
    base = _base(doc, form_type=form_type, **meta)
    out: list[dict] = []
    for table in ("nonDerivativeTable", "derivativeTable"):
        node = doc.get(table) or {}
        txn_key = "nonDerivativeTransaction" if table == "nonDerivativeTable" else "derivativeTransaction"
        for i, t in enumerate(_as_list(node.get(txn_key))):
            shares = _num(_v(t, "transactionAmounts", "transactionShares"))
            price = _num(_v(t, "transactionAmounts", "transactionPricePerShare"))
            ad = _v(t, "transactionAmounts", "transactionAcquiredDisposedCode")  # A|D
            signed = shares if ad != "D" else (-shares if shares is not None else None)
            out.append({**base, "transaction_id": _txn_id(meta["accession"], table, i),
                        "transaction_date": _date(_v(t, "transactionDate")),
                        "transaction_code": _v(t, "transactionCoding", "transactionCode"),
                        "shares": signed, "price": price,
                        "value": (abs(signed) * price) if (signed is not None and price is not None) else None,
                        "ownership_after": _num(_v(t, "postTransactionAmounts", "sharesOwnedFollowingTransaction")),
                        "ownership_type": _ownership(_v(t, "ownershipNature", "directOrIndirectOwnership"))})
    return out


def _ownership(code: Any) -> str:
    return "indirect" if str(code).upper() == "I" else "direct"


def _num(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _date(x: Any) -> date | None:
    return date.fromisoformat(x) if isinstance(x, str) and x else None


def parse_form4(doc: dict, *, accession: str, filing_date: date, acceptance_datetime: datetime,
                security_id: str | None = None, form_type: str = "4") -> list[dict]:
    """Parse a Form 4 (or 4/A amendment) ownership document into transaction rows."""
    return _parse_transactions(doc, form_type, accession=accession, filing_date=filing_date,
                               acceptance_datetime=acceptance_datetime, security_id=security_id)


def parse_form5(doc: dict, *, accession: str, filing_date: date, acceptance_datetime: datetime,
                security_id: str | None = None) -> list[dict]:
    """Form 5 shares Form 4's transaction structure."""
    return parse_form4(doc, accession=accession, filing_date=filing_date,
                       acceptance_datetime=acceptance_datetime, security_id=security_id, form_type="5")


def parse_form3(doc: dict, *, accession: str, filing_date: date, acceptance_datetime: datetime,
                security_id: str | None = None) -> list[dict]:
    """Form 3 = initial holdings (no transactions). Emit one holding row per line
    with transaction_code 'H' and the reported shares as ownership_after."""
    base = _base(doc, form_type="3", accession=accession, filing_date=filing_date,
                 acceptance_datetime=acceptance_datetime, security_id=security_id)
    out: list[dict] = []
    node = doc.get("nonDerivativeTable") or {}
    for i, h in enumerate(_as_list(node.get("nonDerivativeHolding"))):
        owned = _num(_v(h, "postTransactionAmounts", "sharesOwnedFollowingTransaction"))
        out.append({**base, "transaction_id": _txn_id(accession, "holding", i),
                    "transaction_date": _date(doc.get("periodOfReport")),
                    "transaction_code": "H", "shares": None, "price": None, "value": None,
                    "ownership_after": owned,
                    "ownership_type": _ownership(_v(h, "ownershipNature", "directOrIndirectOwnership"))})
    return out


async def fetch_submissions(cik: str | int, *, user_agent: str) -> dict:
    """Fetch a CIK's submission index (lists Form 3/4/5 accessions + acceptance
    timestamps). Network — not used in tests."""
    import asyncio

    import httpx

    url = SEC_SUBMISSIONS.format(cik=int(cik))

    def _get() -> dict:
        r = httpx.get(url, headers={"User-Agent": user_agent}, timeout=30.0)
        r.raise_for_status()
        return r.json()

    return await asyncio.to_thread(_get)
