"""Benchmark the M12 paper-trading bridge: sync, reconciliation, order generation,
and memory across 100 / 1000 / 10000 securities. Offline, deterministic.

Run: .venv/bin/python scripts/benchmark_paper_trading.py
"""

from __future__ import annotations

import time
import tracemalloc
from datetime import date, timedelta

from mentisrex.research.paper_trading import (
    MockBroker,
    PaperTradingSession,
    PreTradeRiskGate,
    RiskLimits,
    SessionConfig,
    compute_drift,
    reconcile,
)
from mentisrex.research.simulation.orders import SizingConfig, generate_orders


def _universe(n):
    return [f"S{i:05d}" for i in range(n)]


def _providers(ids):
    prices = {sid: 100.0 + (i % 50) for i, sid in enumerate(ids)}
    w = 1.0 / len(ids)
    target = {sid: w for sid in ids}
    return prices, target


def bench(n, n_ticks=12):
    ids = _universe(n)
    prices, target = _providers(ids)
    gate = PreTradeRiskGate(RiskLimits(max_name_weight=1.0, max_gross_leverage=1.05))
    cfg = SessionConfig(initial_capital=1e9, sizing=SizingConfig(allow_short=False))
    timeline = [date(2024, 1, 1) + timedelta(days=21 * i) for i in range(n_ticks)]

    tracemalloc.start()
    s = PaperTradingSession(broker=MockBroker(initial_cash=1e9), config=cfg, risk_gate=gate)

    t0 = time.perf_counter()
    for d in timeline:
        s.step(d, target, prices)
    sync_s = time.perf_counter() - t0
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # isolate order generation
    t0 = time.perf_counter()
    for _ in range(10):
        generate_orders(target, s.book.state, prices, cfg.sizing)
    gen_ms = (time.perf_counter() - t0) / 10 * 1e3

    # isolate reconciliation
    acct = s.broker.get_account()
    t0 = time.perf_counter()
    for _ in range(10):
        reconcile(s.book.state, acct)
    rec_ms = (time.perf_counter() - t0) / 10 * 1e3

    t0 = time.perf_counter()
    for _ in range(10):
        compute_drift(s.book.state, acct, target)
    drift_ms = (time.perf_counter() - t0) / 10 * 1e3

    print(f"N={n:>6}  {n_ticks} ticks: total_sync={sync_s*1e3:8.1f}ms "
          f"({sync_s/n_ticks*1e3:6.2f}ms/tick)  order_gen={gen_ms:7.2f}ms  "
          f"reconcile={rec_ms:6.2f}ms  drift={drift_ms:6.2f}ms  peak_mem={peak/1e6:7.1f}MB  "
          f"reconciled={all(e.reconciled for e in s.sync_events)}")


if __name__ == "__main__":
    for n in (100, 1000, 10000):
        bench(n)
