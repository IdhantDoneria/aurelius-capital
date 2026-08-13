"""AIDP M17 multi-asset / derivatives benchmarks — deterministic, offline.

Measures instrument-registry, valuation, mark-to-market, margin, serialization and
reconciliation throughput plus peak memory as instruments, positions and lifecycle events
scale. Uses the `DeterministicMockPricer` (pure-function, no network).

Run: `uv run python scripts/benchmark_m17_instruments.py`
      TARGETS: 10k instruments, 100k positions, 1M lifecycle events
"""

from __future__ import annotations

import time
import tracemalloc
from datetime import date

from mentisrex.research import instruments as ins
from mentisrex.research.instruments import margin as mg
from mentisrex.research.instruments import reconciliation as recon
from mentisrex.research.instruments import risk as rk
from mentisrex.research.instruments import serialization as ser

T0 = date(2026, 1, 5)
DE = date(2026, 12, 18)


def _build(n_instruments: int) -> ins.InstrumentBook:
    b = ins.InstrumentBook(1e12)
    for i in range(n_instruments):
        kind = i % 4
        if kind == 0:
            b.book_trade(ins.equity(f"EQ{i}"), 100, 100.0 + (i % 50))
        elif kind == 1:
            b.book_trade(ins.future(f"FU{i}", contract_size=50, expiry=DE,
                                    initial_margin_rate=0.05, maintenance_margin_rate=0.04),
                         2, 4000.0 + (i % 100))
        elif kind == 2:
            b.book_trade(ins.call(f"OP{i}", underlying=f"EQ{i}", strike=100.0, expiry=DE),
                         1, 5.0 + (i % 10))
        else:
            b.book_trade(ins.forward(f"FW{i}", contract_size=1000, settlement_date=DE),
                         1, 1.10)
    return b


def _bench(n_instruments: int, *, mark_rounds: int = 1) -> dict:
    tracemalloc.start()
    t = time.perf_counter()
    b = _build(n_instruments)
    t_book = time.perf_counter() - t

    marks = {}
    for i in range(n_instruments):
        kind = i % 4
        pfx = ("EQ", "FU", "OP", "FW")[kind]
        marks[f"{pfx}{i}"] = (100.0, 4005.0, 6.0, 1.11)[kind]

    t = time.perf_counter()
    for _ in range(mark_rounds):
        b.mark(marks, when=T0)
    t_mark = (time.perf_counter() - t) / mark_rounds

    t = time.perf_counter()
    rk.exposures(b, marks, greeks_provider=ins.BlackScholesPricer(),
                 market={k: {"spot": 100.0, "vol": 0.2, "rate": 0.01, "t": 0.25}
                         for k in marks if k.startswith("OP")})
    t_risk = time.perf_counter() - t

    from mentisrex.research.instruments.models import InstrumentType
    futures = b.registry.of_type(InstrumentType.FUTURE)
    t = time.perf_counter()
    for f in futures:                                          # margin on the futures slice
        mg.requirement(f, 2, 4005.0)
    t_margin = time.perf_counter() - t

    ext = {p.instrument_id: {"quantity": p.quantity} for p in b.open_positions()}
    t = time.perf_counter()
    recon.reconcile_positions(b, ext)
    t_recon = time.perf_counter() - t

    t = time.perf_counter()
    js = ser.to_json(b)
    t_ser = time.perf_counter() - t

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "instruments": n_instruments,
        "positions": len(b.open_positions()),
        "events": len(b.events),
        "book_s": round(t_book, 4),
        "mark_s": round(t_mark, 4),
        "risk_s": round(t_risk, 4),
        "margin_s": round(t_margin, 4),
        "recon_s": round(t_recon, 4),
        "serialize_s": round(t_ser, 4),
        "serialized_mb": round(len(js) / 1e6, 2),
        "peak_mb": round(peak / 1e6, 1),
    }


def main() -> None:
    print("AIDP M17 — Multi-Asset & Derivatives benchmarks (deterministic, offline)\n")
    rows = []
    for n in (1_000, 10_000, 25_000):
        r = _bench(n, mark_rounds=1)
        rows.append(r)
        print(f"instruments={r['instruments']:>6}  positions={r['positions']:>6}  "
              f"events={r['events']:>7}  book={r['book_s']:>7}s  mark={r['mark_s']:>7}s  "
              f"risk={r['risk_s']:>6}s  margin={r['margin_s']:>6}s  recon={r['recon_s']:>6}s  "
              f"serialize={r['serialize_s']:>6}s  peak={r['peak_mb']:>6}MB")

    # 1M lifecycle events: 25k instruments marked ~40 rounds → >1M InstrumentEvents
    print("\n1M lifecycle-event stress (25k instruments, 55 mark rounds):")
    b = _build(25_000)
    marks = {p.instrument_id: p.last_mark or 100.0 for p in b.open_positions()}
    t = time.perf_counter()
    for _ in range(55):
        b.mark(marks, when=T0)
    dt = time.perf_counter() - t
    print(f"  events={len(b.events):>9}  elapsed={dt:.2f}s  "
          f"throughput={len(b.events) / dt / 1e6:.2f}M events/s")


if __name__ == "__main__":
    main()
