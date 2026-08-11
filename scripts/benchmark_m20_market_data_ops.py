"""AIDP M20 — market-data operations benchmarks (deterministic, offline).

Times each operational stage — ingestion, ordering, arbitration, PIT reconstruction, replay,
incremental update, serialization — at increasing message counts and reports runtime, throughput
and peak memory (tracemalloc). No network, no wall-clock in the measured logic. Run:
    uv run python scripts/benchmark_m20_market_data_ops.py
"""

from __future__ import annotations

import time
import tracemalloc
from datetime import date

from aurelius.research import market_data_ops as ops


def _stream(n_secs: int, days: int, *, seed: int = 0):
    seeds = {f"S{i}": 100.0 + (i % 500) for i in range(n_secs)}
    return ops.StreamingSimulator(ops.SimConfig(
        seeds=seeds, start=date(2024, 1, 2), days=days, seed=seed)).generate(
        ops.FaultSpec(duplicate_frac=0.1, revision_frac=0.1, reorder=True))


def _time(fn, *a, **k):
    tracemalloc.start()
    t0 = time.perf_counter()
    r = fn(*a, **k)
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return r, dt, peak / 1e6


def bench(n_secs: int, days: int) -> None:
    msgs = _stream(n_secs, days)
    n = len(msgs)
    vd = date(2024, 1, 2)
    from datetime import timedelta
    vd = date(2024, 1, 2) + timedelta(days=days - 1)

    state = ops.MarketDataState()
    (_r, dt_i, mem_i) = _time(state.ingest, msgs)

    sm = ops.SequenceManager(ops.OrderingPolicy.REORDER)
    (order_rep, dt_o, _m) = _time(sm.process, msgs)

    arb = ops.SourceArbiter()
    (_a, dt_ar, _m) = _time(arb.arbitrate, list(order_rep.accepted))

    (_rec, dt_r, mem_r) = _time(state.reconstruct, valuation_date=vd, knowledge_date=vd)

    # replay-emit stage timed on its own (reconstruction is timed separately above, so we don't
    # double-count the M19 normalization pass here)
    engine = ops.MarketDataReplayEngine(msgs)
    (_rp, dt_rp, mem_rp) = _time(engine.replay, ops.ReplayConfig(dates=(vd,)), reconstruct=False)

    (_j, dt_s, _m) = _time(ops.messages_to_json, msgs[:5000])

    thru = n / dt_i if dt_i else float("inf")
    print(f"msgs={n:>9}  ingest={dt_i*1e3:8.1f}ms ({thru:>10.0f}/s)  order={dt_o*1e3:8.1f}ms  "
          f"arbitrate={dt_ar*1e3:7.1f}ms  reconstruct={dt_r*1e3:8.1f}ms  replay_emit={dt_rp*1e3:8.1f}ms  "
          f"serialize5k={dt_s*1e3:6.1f}ms  peak_recon={mem_r:6.1f}MB")


def bench_incremental(n_secs: int, days: int, batches: int) -> None:
    msgs = _stream(n_secs, days)
    step = max(1, len(msgs) // batches)
    state = ops.MarketDataState()
    t0 = time.perf_counter()
    for i in range(0, len(msgs), step):
        state.ingest(msgs[i:i + step])
    dt = time.perf_counter() - t0
    print(f"\nincremental ingest ({batches} batches, {len(msgs)} msgs): {dt*1e3:.1f}ms  "
          f"final state fingerprint {state.fingerprint()[:12]}")


def main() -> None:
    print("AIDP M20 — market-data operations benchmarks (deterministic, offline)\n")
    for n_secs, days in ((2_000, 5), (5_000, 20), (10_000, 100)):
        bench(n_secs, days)
    bench_incremental(5_000, 20, batches=50)
    print("\n(Reconstruction is a pure function of the deduplicated message set; ordering and "
          "arbitration are the linear passes. Memory grows with retained messages — batch by "
          "security/date window for multi-million-message replay windows.)")


if __name__ == "__main__":
    main()
