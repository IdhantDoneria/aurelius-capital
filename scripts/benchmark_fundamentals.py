"""Benchmark the PIT fundamentals ledger at institutional scale (Phase 3).

Seeds ~companies × concepts × periods facts, then times:
  - bulk ingest throughput (rows/sec)
  - single fact_as_of point query (index lookup)
  - a cross-sectional sweep: fact_as_of for every company as-of one date

Run: python scripts/benchmark_fundamentals.py [companies] [years]
Default 10,000 companies × 20 years × ~15 concepts (annual) ≈ 3M facts.
"""

from __future__ import annotations

import sys
import time
from datetime import date

from mentisrex.market_data.fundamentals import FundamentalsStore

CONCEPTS = ["Assets", "Liabilities", "StockholdersEquity", "NetIncomeLoss", "Revenues",
            "GrossProfit", "OperatingIncomeLoss", "CommonStockSharesOutstanding", "LongTermDebt",
            "CashAndCashEquivalentsAtCarryingValue", "AssetsCurrent", "LiabilitiesCurrent",
            "NetCashProvidedByUsedInOperatingActivities", "DepreciationDepletionAndAmortization",
            "WeightedAverageNumberOfSharesOutstandingBasic"]


def run(companies: int = 10_000, years: int = 20) -> None:
    store = FundamentalsStore(":memory:")
    facts = []
    for c in range(companies):
        cik = str(c)
        for y in range(2000, 2000 + years):
            end = date(y, 12, 31)
            filed = date(y + 1, 3, 1)
            for concept in CONCEPTS:
                unit = "shares" if "Shares" in concept else "USD"
                facts.append({"cik": cik, "security_id": None, "taxonomy": "us-gaap",
                              "concept": concept, "unit": unit, "period_start": None,
                              "period_end": end, "fiscal_year": y, "fiscal_period": "FY",
                              "value": float(1_000 + y), "form": "10-K",
                              "accession": f"{c}-{y}", "filing_date": filed, "frame": None})
    total = len(facts)
    t0 = time.perf_counter()
    # write in chunks to bound memory
    for i in range(0, total, 500_000):
        store.write_facts(facts[i:i + 500_000])
    ingest_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    store.fact_as_of("5000", "StockholdersEquity", date(2015, 6, 30))
    point_ms = (time.perf_counter() - t1) * 1000

    t2 = time.perf_counter()
    hits = 0
    for c in range(companies):
        if store.fact_as_of(str(c), "StockholdersEquity", date(2015, 6, 30)) is not None:
            hits += 1
    sweep_s = time.perf_counter() - t2

    store.close()
    print(f"facts: {total:,}  ({companies:,} companies x {years}y x {len(CONCEPTS)} concepts)")
    print(f"  ingest:            {ingest_s:6.2f}s  ({total/ingest_s/1e6:.2f}M rows/s)")
    print(f"  fact_as_of point:  {point_ms:6.2f} ms")
    print(f"  cross-section {companies:,} companies as-of: {sweep_s:6.2f}s  ({companies/sweep_s:,.0f}/s, {hits:,} hits)")


if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:3]]
    run(*a) if a else run()
