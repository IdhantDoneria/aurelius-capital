"""AIDP M16 multi-currency / FX benchmarks — deterministic, offline.

Measures valuation / FX-conversion / reconciliation / P&L-attribution / serialization
throughput and peak memory as currencies, positions and transactions scale. Uses the
`DeterministicMockFXProvider` (pure-function rates, no network).

Run: `uv run python scripts/benchmark_m16_fx.py`
"""

from __future__ import annotations

import time
import tracemalloc
from datetime import date
from itertools import product

from aurelius.research import fx
from aurelius.research.fx import serialization
from aurelius.research.post_trade import SettlementConfig

T0 = date(2026, 1, 5)
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _codes(n: int) -> list:
    """First `n` distinct 3-letter codes != USD."""
    out = []
    for a, b, c in product(_LETTERS, repeat=3):
        code = a + b + c
        if code == "USD":
            continue
        out.append(code)
        if len(out) == n:
            return out
    return out


def _bench(n_currencies: int, n_positions: int, *, serialize: bool = True) -> dict:
    ccys = _codes(n_currencies)
    provider = fx.DeterministicMockFXProvider("USD")
    book = fx.MultiCurrencyBook("USD", provider,
                                initial={"USD": 1e12, **{c: 1e9 for c in ccys}},
                                settlement_config=SettlementConfig(default_days=2))

    tracemalloc.start()
    t0 = time.perf_counter()
    for i in range(n_positions):
        ccy = ccys[i % n_currencies]
        book.book_fill(security_id=f"S{i}", quantity=10.0, price=100.0 + (i % 50),
                       cost=1.0, currency=ccy, trade_date=T0)
    t_book = time.perf_counter() - t0

    prices = {f"S{i}": 101.0 + (i % 50) for i in range(n_positions)}

    t0 = time.perf_counter()
    val = fx.valuation(book, as_of=T0, prices=prices)
    t_val = time.perf_counter() - t0

    t0 = time.perf_counter()
    fx.convert(provider, 1e6, ccys[0], "USD", as_of=T0)      # single conversion cost
    t_conv = time.perf_counter() - t0

    t0 = time.perf_counter()
    recon = fx.reconcile(book, as_of=T0)
    t_recon = time.perf_counter() - t0

    snap0 = fx.value_snapshot(book, as_of=T0)
    snap1 = {c: (v * 1.01, r * 1.02) for c, (v, r) in snap0.items()}
    t0 = time.perf_counter()
    pnl = fx.fx_pnl(book, snap0, snap1)
    t_pnl = time.perf_counter() - t0

    t_ser = 0.0
    if serialize:
        t0 = time.perf_counter()
        _ = serialization.to_json(book, as_of=T0)
        t_ser = time.perf_counter() - t0

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    n_events = sum(len(e.log) for e in book.books.values())
    return {"currencies": n_currencies, "positions": n_positions, "events": n_events,
            "book_s": t_book, "val_s": t_val, "conv_s": t_conv, "recon_s": t_recon,
            "pnl_s": t_pnl, "ser_s": t_ser, "peak_mb": peak / 1e6,
            "base_value": val.total_base, "recon_ok": recon.ok, "pnl_ok": pnl.reconciles}


def main() -> None:
    rows = [
        _bench(100, 1_000),
        _bench(1_000, 10_000),
        _bench(50, 10_000),
        _bench(100, 100_000, serialize=False),        # 100k transactions
        _bench(200, 350_000, serialize=False),        # >1M lifecycle events
    ]
    hdr = (f"{'ccys':>6} {'pos':>8} {'events':>10} {'book_s':>8} {'val_s':>7} {'conv_ms':>8} "
           f"{'recon_s':>8} {'pnl_s':>7} {'ser_s':>7} {'peakMB':>9} {'ok':>4}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        ok = r["recon_ok"] and r["pnl_ok"]
        print(f"{r['currencies']:>6,} {r['positions']:>8,} {r['events']:>10,} {r['book_s']:>8.3f} "
              f"{r['val_s']:>7.3f} {r['conv_s'] * 1000:>8.3f} {r['recon_s']:>8.3f} "
              f"{r['pnl_s']:>7.3f} {r['ser_s']:>7.2f} {r['peak_mb']:>9.1f} {str(ok):>4}")
    assert all(r["recon_ok"] and r["pnl_ok"] for r in rows), "benchmark must reconcile"


if __name__ == "__main__":
    main()
