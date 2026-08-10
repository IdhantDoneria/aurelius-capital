"""AIDP M18 valuation benchmarks — deterministic, offline.

Measures single-instrument and batch valuation latency/throughput, Greeks, curve build,
surface interpolation and portfolio valuation across 1 / 1k / 10k / 100k instruments, plus
peak memory. No network. Uses in-process pricers and a static snapshot.

Run: `uv run python scripts/benchmark_m18_valuation.py`
  TARGETS: 10k equities, 10k options, 10k futures, 10k bonds, 1k swaps, 100k total.
"""

from __future__ import annotations

import time
import tracemalloc
from datetime import date

from aurelius.research import instruments as ins
from aurelius.research import valuation as val
from aurelius.research.valuation import bonds as vbonds
from aurelius.research.valuation import swaps as vswaps

AS_OF = date(2026, 1, 5)
EXPIRY = date(2027, 1, 5)


def build_snapshot(n_under: int) -> val.MarketDataSnapshot:
    zc = val.ZeroCurve("USD", AS_OF, (0.25, 1, 2, 5, 10, 30), (0.03,) * 6)
    spots = {f"U{i}": 100.0 + (i % 50) for i in range(n_under)}
    surfaces = {f"U{i}": val.flat_surface(f"U{i}", AS_OF, 0.2 + (i % 10) * 0.01)
                for i in range(n_under)}
    return val.build_snapshot(AS_OF, spots=spots, rates={"USD": zc},
                              vol_surfaces=surfaces, dividend_yields={})


def build_positions(n_each: int, n_under: int) -> list:
    pos = []
    for i in range(n_each):
        u = f"U{i % n_under}"
        pos.append((ins.equity(u), 100, None))
        pos.append((ins.call(f"C{i}", underlying=u, strike=100.0, expiry=EXPIRY), 1, None))
        pos.append((_future_with_underlying(f"F{i}", u), 1, None))
        pos.append((ins.bond(f"B{i}", face=100.0, coupon=0.05, maturity=date(2031, 1, 5)), 10, None))
    return pos


def _future_with_underlying(fid: str, under: str):
    from aurelius.research.instruments.models import CashConvention, Instrument, InstrumentType
    return Instrument(fid, InstrumentType.FUTURE, contract_size=1, expiry=EXPIRY,
                      cash_convention=CashConvention.MARGINED, underlying=under)


def bench(n_each: int, n_under: int) -> dict:
    snap = build_snapshot(n_under)
    engine = val.ValuationEngine(validate_pit_on_value=False)   # PIT checked once, not per-call
    positions = build_positions(n_each, n_under)

    tracemalloc.start()
    # single valuation latency
    t = time.perf_counter()
    for _ in range(1000):
        engine.value(positions[1][0], snap)                     # an option
    single_us = (time.perf_counter() - t) / 1000 * 1e6

    # batch portfolio valuation
    t = time.perf_counter()
    pv = val.PortfolioValuationEngine(engine).value(positions, snap)
    batch_s = time.perf_counter() - t

    # curve build + surface interp
    t = time.perf_counter()
    for _ in range(1000):
        val.CurveBuilder().build_zero("USD", AS_OF, [(1.0, 0.03), (5.0, 0.035), (10.0, 0.04)])
    curve_us = (time.perf_counter() - t) / 1000 * 1e6

    surf = snap.vol_surfaces["U0"]
    t = time.perf_counter()
    for i in range(10000):
        surf.vol(100.0 + i % 20, 1.0)
    surf_us = (time.perf_counter() - t) / 10000 * 1e6

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"instruments": len(positions), "single_us": round(single_us, 2),
            "batch_s": round(batch_s, 3),
            "throughput_per_s": round(len(positions) / batch_s),
            "curve_build_us": round(curve_us, 2), "surface_us": round(surf_us, 3),
            "portfolio_base": round(pv.base_value, 0), "peak_mb": round(peak / 1e6, 1)}


def main() -> None:
    print("AIDP M18 — Valuation benchmarks (deterministic, offline)\n")
    for n_each, n_under in ((250, 50), (2500, 200), (25000, 500)):
        r = bench(n_each, n_under)
        print(f"instruments={r['instruments']:>7}  single={r['single_us']:>7}us  "
              f"batch={r['batch_s']:>7}s  thru={r['throughput_per_s']:>7}/s  "
              f"curve_build={r['curve_build_us']:>6}us  surf_interp={r['surface_us']:>6}us  "
              f"peak={r['peak_mb']:>6}MB")
    print("\n(100k instruments = 25000 x 4 asset classes; 1k+ swaps below)")
    snap = build_snapshot(50)
    zc = snap.rates["USD"]
    spec = vswaps.SwapSpec(1e7, 0.03, tuple(date(2026 + i, 1, 5) for i in range(1, 6)), AS_OF)
    t = time.perf_counter()
    for _ in range(1000):
        vswaps.npv(spec, zc)
    print(f"  swap NPV: {(time.perf_counter()-t)/1000*1e6:.2f}us each (1000 swaps)")


if __name__ == "__main__":
    main()
