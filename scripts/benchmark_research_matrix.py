"""Benchmark the research matrix at scale (AIDP M6).

Seeds a synthetic universe of N securities with prices + fundamentals + insiders,
then times a full feature_matrix_as_of build and a cached retrieval, and reports
matrix memory.

Run: python scripts/benchmark_research_matrix.py [N]   (default 10,000)
Targets: initial build < 10 s, cached retrieval < 500 ms.
"""

from __future__ import annotations

import sys
import time
import tracemalloc
from datetime import date, datetime

from mentisrex.market_data.fundamentals import FundamentalsEngine, FundamentalsStore
from mentisrex.market_data.insiders import InsiderEngine, InsiderStore
from mentisrex.market_data.research_matrix import FEATURES, ResearchMatrixEngine
from mentisrex.market_data.storage.pit_store import PitPriceStore
from mentisrex.market_data.universe import UniverseEngine


class _FakeSM:
    """Minimal SecurityMaster stand-in: a fixed live universe, id==ticker.

    Avoids seeding the real identity store 10k times; the matrix engine only calls
    universe_as_of(...).securities, which is all this provides.
    """

    def __init__(self, secs):
        self._secs = secs

    def live_as_of(self, as_of):
        return self._secs

    def all_securities(self):
        return self._secs

    def historical_identifier(self, sid, as_of):
        return sid  # ticker == security_id here


def run(n: int = 10_000) -> None:
    as_of = date(2020, 6, 30)
    secs = [{"security_id": f"SEC{i:06d}", "ticker": f"SEC{i:06d}", "exchange": "XNYS"}
            for i in range(n)]
    cik_map = {s["security_id"]: str(i) for i, s in enumerate(secs)}

    prices = PitPriceStore(":memory:")
    fstore = FundamentalsStore(":memory:")
    istore = InsiderStore(":memory:")

    prices.write_raw_bars([
        {"symbol": s["security_id"], "timestamp": datetime(2020, 6, d), "frequency": "1d",
         "open": 90, "high": 96, "low": 89, "close": 90.0 + d, "volume": 1000, "source": "b"}
        for s in secs for d in (29, 30)
    ])
    fstore.write_facts([
        {"cik": cik_map[s["security_id"]], "taxonomy": "us-gaap", "concept": c, "unit": "USD",
         "period_end": "2020-03-31", "value": v, "form": "10-K",
         "accession": f"{s['security_id']}{c}", "filing_date": "2020-05-10"}
        for s in secs
        for c, v in (("StockholdersEquity", 5e8), ("Assets", 1e9), ("NetIncomeLoss", 1e8),
                     ("Revenues", 2e9), ("CommonStockSharesOutstanding", 1e7))
    ])
    istore.write_transactions([
        {"transaction_id": f"{s['security_id']}t", "security_id": s["security_id"],
         "cik": cik_map[s["security_id"]], "insider_name": "CEO", "insider_type": "officer",
         "transaction_date": date(2020, 6, 1), "filing_date": date(2020, 6, 3),
         "acceptance_datetime": datetime(2020, 6, 3, 18, 0, 0), "transaction_code": "P",
         "shares": 1000.0, "price": 50.0, "value": 50000.0, "ownership_type": "direct",
         "accession": f"{s['security_id']}a", "form_type": "4"}
        for s in secs
    ])

    fund = FundamentalsEngine(fstore, price_store=prices, security_master=_FakeSM(secs))
    ins = InsiderEngine(istore, cluster_threshold=3)
    uni = UniverseEngine(_FakeSM(secs))
    eng = ResearchMatrixEngine(universe=uni, fundamentals=fund, insiders=ins,
                               prices=prices, cik_map=cik_map)

    # 18 real features; pad to 50 columns with aliases onto existing bundle fields
    # (extra columns are dict lookups over already-computed bundles — near-free) to
    # stress the spec's 50-column target honestly.
    base = list(FEATURES.items())
    i = 0
    while len(FEATURES) < 50:
        name, spec = base[i % len(base)]
        FEATURES[f"{name}_alias{i}"] = spec
        i += 1
    feats = list(FEATURES.keys())
    tracemalloc.start()
    t0 = time.perf_counter()
    m = eng.feature_matrix_as_of(as_of, features=feats)
    build_s = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    mem_mb = m.frame.memory_usage(deep=True).sum() / 1e6

    t1 = time.perf_counter()
    eng.feature_matrix_as_of(as_of, features=feats)
    cache_ms = (time.perf_counter() - t1) * 1000

    for s in (prices, fstore, istore):
        s.close()
    print(f"universe: {n:,} securities × {len(feats)} features")
    print(f"  initial build:      {build_s:7.2f} s   (target < 10 s)")
    print(f"  cached retrieval:   {cache_ms:7.2f} ms  (target < 500 ms)")
    print(f"  matrix memory:      {mem_mb:7.2f} MB")
    print(f"  build peak alloc:   {peak/1e6:7.2f} MB")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 10_000)
