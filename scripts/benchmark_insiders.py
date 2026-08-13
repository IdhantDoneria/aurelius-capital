"""Benchmark the insider ledger at scale (AIDP M5).

Seeds N insider rows across many securities, then times:
  - bulk ingest throughput
  - transactions_as_of latency (PIT window query, one security)
  - insider_position_as_of lookup latency

Run: python scripts/benchmark_insiders.py [N]  (default 1,000,000)
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta

from mentisrex.market_data.insiders import InsiderStore


def run(n: int = 1_000_000, securities: int = 10_000) -> None:
    store = InsiderStore(":memory:")
    per = max(1, n // securities)
    base_dt = datetime(2015, 1, 1)
    rows = []
    for i in range(n):
        sec = i % securities
        k = i // securities
        acc_dt = base_dt + timedelta(days=k)
        rows.append({
            "transaction_id": f"INS{i}", "security_id": f"SEC{sec:06d}", "cik": str(sec),
            "insider_name": f"NAME{i % 7}", "insider_role": "CEO", "insider_type": "officer",
            "transaction_date": (acc_dt - timedelta(days=2)).date(),
            "filing_date": acc_dt.date(), "acceptance_datetime": acc_dt,
            "transaction_code": "P" if i % 2 else "S", "shares": 1000.0, "price": 50.0,
            "value": 50000.0, "ownership_after": float(1000 * (k + 1)), "ownership_type": "direct",
            "accession": f"a{i}", "form_type": "4",
        })

    t0 = time.perf_counter()
    for j in range(0, n, 500_000):
        store.write_transactions(rows[j:j + 500_000])
    ingest_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    got = store.transactions_as_of("SEC005000", date(2030, 1, 1))
    txn_ms = (time.perf_counter() - t1) * 1000

    t2 = time.perf_counter()
    store.insider_position_as_of("SEC005000", "NAME3", date(2030, 1, 1))
    pos_ms = (time.perf_counter() - t2) * 1000

    store.close()
    print(f"rows: {n:,} across {securities:,} securities")
    print(f"  ingest:                    {ingest_s:6.2f}s  ({n/ingest_s/1e6:.2f}M rows/s)")
    print(f"  transactions_as_of:        {txn_ms:7.2f} ms  ({len(got)} collapsed rows)")
    print(f"  insider_position_as_of:    {pos_ms:7.2f} ms")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000)
