"""Backfill the PIT fundamentals ledger from SEC EDGAR (AIDP Phase 3 migration).

Fetches companyfacts per CIK, parses to immutable facts + filings, appends to the
ledger, logs the run. Idempotent (facts keyed incl. accession). Needs network and
a descriptive SEC User-Agent ("Name email") per SEC fair-access policy.

Usage:
    python scripts/backfill_fundamentals.py 320193 789019 \
        --user-agent "Aurelius Research you@example.com"
    python scripts/backfill_fundamentals.py --cik-file ciks.txt --user-agent "..."
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from aurelius.market_data.fundamentals import (
    FundamentalsStore,
    fetch_company_facts,
    parse_company_facts,
)


async def _run(ciks: list[str], user_agent: str, db_path: str) -> None:
    store = FundamentalsStore(db_path)
    try:
        for cik in ciks:
            try:
                doc = await fetch_company_facts(cik, user_agent=user_agent)
                facts, filings = parse_company_facts(doc)
                nf = store.write_facts(facts)
                nfi = store.record_filings(filings)
                store.log_ingestion(cik, facts=nf, filings=nfi, status="ok")
                print(f"CIK {cik}: {nf} facts, {nfi} filings")
            except Exception as exc:  # noqa: BLE001 — log and continue the batch
                store.log_ingestion(cik, facts=0, filings=0, status="error", message=str(exc))
                print(f"CIK {cik}: ERROR {exc}")
            time.sleep(0.15)  # SEC fair-access: keep under ~10 req/s
    finally:
        store.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ciks", nargs="*")
    p.add_argument("--cik-file")
    p.add_argument("--user-agent", required=True, help='SEC requires "Name email"')
    p.add_argument("--db", default="./data/fundamentals.duckdb")
    args = p.parse_args()
    ciks = list(args.ciks)
    if args.cik_file:
        ciks += [c.strip() for c in Path(args.cik_file).read_text().splitlines() if c.strip()]
    if not ciks:
        p.error("no CIKs given")
    asyncio.run(_run(ciks, args.user_agent, args.db))


if __name__ == "__main__":
    main()
