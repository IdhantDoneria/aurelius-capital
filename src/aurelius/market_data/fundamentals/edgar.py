"""SEC EDGAR companyfacts → fact ledger (AIDP M3).

parse_company_facts is pure (no I/O) — unit-testable against a synthetic
companyfacts document. fetch_company_facts does the network call (SEC requires a
descriptive User-Agent); it's used by scripts/backfill_fundamentals.py.

EDGAR companyfacts JSON shape:
  {"cik": 320193, "facts": {"us-gaap": {"<Concept>": {"units":
      {"USD": [{"end","val","accn","fy","fp","form","filed","frame","start"?}, ...]}}}}}
"""

from __future__ import annotations

from datetime import date
from typing import Any

SEC_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def parse_company_facts(doc: dict[str, Any], security_id: str | None = None) -> tuple[list[dict], list[dict]]:
    """Split a companyfacts document into (facts, filings).

    facts: one row per XBRL data point (never deduped across accessions →
    restatements preserved). filings: one row per distinct accession.
    """
    cik = str(doc.get("cik", "")).lstrip("0") or str(doc.get("cik", ""))
    cik = f"{int(cik):d}" if cik.isdigit() else cik
    facts: list[dict] = []
    filings: dict[str, dict] = {}

    for taxonomy, concepts in (doc.get("facts") or {}).items():
        for concept, body in concepts.items():
            for unit, points in (body.get("units") or {}).items():
                for p in points:
                    end = _d(p.get("end"))
                    accn = p.get("accn")
                    filed = _d(p.get("filed"))
                    if end is None or accn is None or filed is None or p.get("val") is None:
                        continue  # broken/incomplete XBRL point — skip (quality flags separately)
                    facts.append({
                        "cik": cik, "security_id": security_id, "taxonomy": taxonomy,
                        "concept": concept, "unit": unit,
                        "period_start": _d(p.get("start")), "period_end": end,
                        "fiscal_year": p.get("fy"), "fiscal_period": p.get("fp"),
                        "value": float(p["val"]), "form": p.get("form"),
                        "accession": accn, "filing_date": filed, "frame": p.get("frame"),
                        "vendor": "sec_edgar",
                        "source_document": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}",
                        "data_version": 1,
                    })
                    f = filings.get(accn)
                    # keep the latest period_end seen for the accession as its report period
                    if f is None or (f["period_end"] and end and end > f["period_end"]):
                        filings[accn] = {
                            "accession": accn, "cik": cik, "security_id": security_id,
                            "form": p.get("form"), "filing_date": filed, "period_end": end,
                            "report_type": p.get("form"),
                            "source_document": facts[-1]["source_document"],
                        }
    return facts, list(filings.values())


async def fetch_company_facts(cik: str | int, *, user_agent: str) -> dict[str, Any]:
    """Fetch companyfacts JSON from SEC. Requires a descriptive User-Agent
    ("Name email") per SEC fair-access policy. Network — not used in tests."""
    import asyncio

    import httpx

    url = SEC_COMPANYFACTS.format(cik=int(cik))

    def _get() -> dict[str, Any]:
        r = httpx.get(url, headers={"User-Agent": user_agent}, timeout=30.0)
        r.raise_for_status()
        return r.json()

    return await asyncio.to_thread(_get)
