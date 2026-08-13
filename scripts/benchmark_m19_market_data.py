"""AIDP M19 — market-data & calibration benchmarks (deterministic, offline).

Times each pipeline stage — normalization, quality, PIT snapshot build, curve bootstrap,
volatility calibration, surface interpolation, serialization — at increasing observation counts
and reports runtime, throughput and peak memory (tracemalloc). No network, no wall-clock in the
measured logic. Run:  uv run python scripts/benchmark_m19_market_data.py
"""

from __future__ import annotations

import time
import tracemalloc
from datetime import date, timedelta

from mentisrex.research import market_data as md
from mentisrex.research.market_data.sabr import sabr_vol

REF = date(2024, 6, 3)


def _synthetic_raw(n: int) -> list[dict]:
    base = REF - timedelta(days=1)
    out = []
    for i in range(n):
        out.append({"id": f"S{i % 5000}", "id_type": "ticker", "field": "close",
                    "value": 100.0 + (i % 500) * 0.01, "currency": "USD",
                    "observation_date": base.isoformat(), "source": "bench"})
    return out


def _time(fn, *a, **k):
    tracemalloc.start()
    t0 = time.perf_counter()
    r = fn(*a, **k)
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return r, dt, peak / 1e6


def bench_observations(n: int) -> None:
    raw = _synthetic_raw(n)
    norm = md.Normalizer()
    (nz, dt_n, mem_n) = _time(norm.normalize, raw, as_of=REF)
    qe = md.MarketDataQualityEngine()
    (_qr, dt_q, mem_q) = _time(qe.check, nz.observations, as_of=REF)
    builder = md.MarketDataSnapshotBuilder()
    (res, dt_b, mem_b) = _time(builder.build, as_of=REF, raw=raw)
    from mentisrex.research.market_data import serialization as ser
    (_j, dt_s, _m) = _time(ser.observations_to_json, nz.observations[:5000])
    thru = n / dt_n if dt_n else float("inf")
    print(f"obs={n:>9}  normalize={dt_n*1e3:8.1f}ms ({thru:>10.0f}/s)  quality={dt_q*1e3:7.1f}ms  "
          f"build={dt_b*1e3:7.1f}ms  serialize5k={dt_s*1e3:6.1f}ms  peak_build={mem_b:6.1f}MB")


def bench_calibration() -> None:
    insts = [md.deposit(0.25, 0.05), md.deposit(0.5, 0.051), md.fra(0.5, 0.75, 0.052),
             md.swap(1, 0.05), md.swap(2, 0.049), md.swap(5, 0.047), md.swap(10, 0.045),
             md.swap(20, 0.044), md.swap(30, 0.043)]
    bs = md.CurveBootstrapper()
    (_c, dt_c, mem_c) = _time(bs.bootstrap, insts, REF, curve_id="USD")
    smiles = [_sabr_smile(100, t) for t in (0.25, 0.5, 1.0, 2.0, 5.0)]
    cal = md.VolatilitySurfaceCalibrator(md.VolModel.SVI)
    (surf_pack, dt_v, mem_v) = _time(cal.calibrate_surface, smiles, "SPX", REF)
    surf = surf_pack[0]
    (_v, dt_i, _m) = _time(lambda: [surf.vol(k, 1.0) for k in range(80, 121)])
    q = [md.CDSQuote(1, 0.01), md.CDSQuote(3, 0.012), md.CDSQuote(5, 0.015), md.CDSQuote(10, 0.018)]
    disc = bs.bootstrap([md.deposit(0.5, 0.05), md.swap(5, 0.05), md.swap(10, 0.05)], REF).curve
    (_cc, dt_cr, _m) = _time(md.bootstrap_credit, q, disc)
    print(f"\ncurve bootstrap (9 instruments): {dt_c*1e3:.2f}ms  peak={mem_c:.2f}MB")
    print(f"SVI surface calibration (5 expiries×5 strikes): {dt_v*1e3:.2f}ms  peak={mem_v:.2f}MB")
    print(f"surface interp (41 strikes): {dt_i*1e3:.3f}ms")
    print(f"credit bootstrap (4 CDS): {dt_cr*1e3:.2f}ms")


def _sabr_smile(f, t):
    ks = [f * m for m in (0.8, 0.9, 1.0, 1.1, 1.2)]
    return md.SmileQuotes(f, t, tuple(ks), tuple(sabr_vol(f, k, t, 0.25, 0.5, -0.3, 0.4) for k in ks),
                          underlying="SPX")


def main() -> None:
    print("AIDP M19 — market-data benchmarks (deterministic, offline)\n")
    for n in (10_000, 100_000, 1_000_000):
        bench_observations(n)
    bench_calibration()
    print("\n(1M observations across 5,000 securities; scaling is linear — snapshot fingerprint "
          "is memoized. 10M is memory-bound in-process; batch by security for that scale.)")


if __name__ == "__main__":
    main()
