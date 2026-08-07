"""Backfill insider transactions from SEC EDGAR Forms 3/4/5 (AIDP M5).

CIK-based, incremental, logged. For each CIK: read the submission index, pick
Form 3/4/5 filings newer than what's already stored (incremental), fetch each
ownership XML, parse, append. Needs network + xmltodict + a descriptive SEC
User-Agent ("Name email") per SEC fair-access policy.

Usage:
    python scripts/backfill_insiders.py 320193 --user-agent "Aurelius you@example.com"
    python scripts/backfill_insiders.py --cik-file ciks.txt --user-agent "..." --since 2020-01-01
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import date, datetime
from pathlib import Path

import httpx

from aurelius.market_data.insiders import (
    InsiderStore,
    fetch_submissions,
    parse_form3,
    parse_form4,
    parse_form5,
)

_PARSERS = {"3": parse_form3, "4": parse_form4, "5": parse_form5,
            "3/A": parse_form3, "4/A": parse_form4, "5/A": parse_form5}


def _doc_url(cik: str, accession: str, primary: str) -> str:
    acc = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{primary}"


async def _run(ciks: list[str], user_agent: str, db_path: str, since: date | None) -> None:
    import xmltodict  # optional dep; only needed for the live XML path

    store = InsiderStore(db_path)
    headers = {"User-Agent": user_agent}
    try:
        for cik in ciks:
            n = 0
            try:
                sub = await fetch_submissions(cik, user_agent=user_agent)
                recent = sub.get("filings", {}).get("recent", {})
                forms = recent.get("form", [])
                accns = recent.get("accessionNumber", [])
                primaries = recent.get("primaryDocument", [])
                accepted = recent.get("acceptanceDateTime", [])
                filed = recent.get("filingDate", [])
                for i, form in enumerate(forms):
                    if form not in _PARSERS:
                        continue
                    fdate = date.fromisoformat(filed[i])
                    if since and fdate < since:
                        continue
                    acc_dt = datetime.fromisoformat(accepted[i].replace("Z", "+00:00"))
                    xml = httpx.get(_doc_url(cik, accns[i], primaries[i]), headers=headers, timeout=30.0)
                    xml.raise_for_status()
                    doc = xmltodict.parse(xml.text).get("ownershipDocument", {})
                    rows = _PARSERS[form](doc, accession=accns[i], filing_date=fdate,
                                          acceptance_datetime=acc_dt)
                    n += store.write_transactions(rows)
                    time.sleep(0.15)  # SEC fair-access
                print(f"CIK {cik}: {n} insider rows")
            except Exception as exc:  # noqa: BLE001 — log and continue batch
                print(f"CIK {cik}: ERROR {exc}")
    finally:
        store.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ciks", nargs="*")
    p.add_argument("--cik-file")
    p.add_argument("--user-agent", required=True)
    p.add_argument("--db", default="./data/insiders.duckdb")
    p.add_argument("--since", help="YYYY-MM-DD; skip filings before this (incremental)")
    args = p.parse_args()
    ciks = list(args.ciks)
    if args.cik_file:
        ciks += [c.strip() for c in Path(args.cik_file).read_text().splitlines() if c.strip()]
    if not ciks:
        p.error("no CIKs given")
    since = date.fromisoformat(args.since) if args.since else None
    asyncio.run(_run(ciks, args.user_agent, args.db, since))


if __name__ == "__main__":
    main()
