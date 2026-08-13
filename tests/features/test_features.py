"""Feature platform tests: value correctness, look-ahead safety, pipeline, store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from mentisrex.features import (
    Bar,
    FeaturePipeline,
    FeatureStore,
    all_features,
    get,
)
from mentisrex.features.registry import Window


def _bars(closes, start=None, vol=1000):
    """Build a simple ascending daily bar series from a list of closes."""
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    out = []
    for i, c in enumerate(closes):
        c = Decimal(str(c))
        out.append(
            Bar(
                timestamp=start + timedelta(days=i),
                open=c,
                high=c + Decimal("1"),
                low=c - Decimal("1"),
                close=c,
                volume=Decimal(str(vol)),
            )
        )
    return out


def _win(closes, **kw):
    d = [Decimal(str(c)) for c in closes]
    return Window(open=d, high=[x + 1 for x in d], low=[x - 1 for x in d], close=d, volume=d, **kw)


# ── value correctness ─────────────────────────────────────────────────────────


def test_returns_1d():
    assert get("returns_1d")(_win([100, 110])) == Decimal("0.1")


def test_sma_20():
    assert get("sma_20")(_win(list(range(1, 21)))) == Decimal("10.5")


def test_zscore_constant_is_zero():
    assert get("zscore_20")(_win([50] * 20)) == Decimal(0)


def test_rsi_bounds_all_up_all_down():
    assert get("rsi_14")(_win(list(range(1, 20)))) == Decimal(100)
    assert get("rsi_14")(_win(list(range(20, 1, -1)))) == Decimal(0)


def test_bollinger_pctb_midpoint():
    # symmetric ramp: last close sits above the mean, %B > 0.5 and within band
    v = get("bollinger_pctb_20")(_win(list(range(1, 21))))
    assert v is not None
    assert Decimal("0.5") < v <= Decimal("1")


def test_relative_volume():
    w = Window(
        open=[Decimal(1)] * 20,
        high=[Decimal(1)] * 20,
        low=[Decimal(1)] * 20,
        close=[Decimal(1)] * 20,
        volume=[Decimal(100)] * 19 + [Decimal(200)],
    )
    assert get("relative_volume_20")(w) == Decimal(200) / (Decimal(2100) / Decimal(20))


def test_beta_self_is_one():
    closes = [100 + i for i in range(70)]
    w = _win(closes, market=[Decimal(str(c)) for c in closes])
    b = get("beta_60")(w)
    assert b is not None
    assert abs(b - Decimal(1)) < Decimal("0.01")


# ── bias prevention: no look-ahead ────────────────────────────────────────────


def test_no_lookahead_value_unchanged_when_future_appended():
    """A feature's value at bar t must not change when later bars are added."""
    base = [100 + (i % 5) for i in range(40)]
    pipe = FeaturePipeline(use_cache=False)
    rows_short = pipe.compute_symbol("X", _bars(base[:30]))
    rows_long = pipe.compute_symbol("X", _bars(base))  # 10 extra future bars

    def at(rows, feat, ts):
        return next(r.value for r in rows if r.feature == feat and r.timestamp == ts)

    ts = _bars(base)[25].timestamp
    for feat in {r.feature for r in rows_short}:
        assert at(rows_short, feat, ts) == at(rows_long, feat, ts), feat


# ── pipeline: missing data, caching ───────────────────────────────────────────


def test_insufficient_history_is_none_not_error():
    rows = FeaturePipeline().compute_symbol("X", _bars([100, 101, 102]))
    sma = [r for r in rows if r.feature == "sma_20"]
    assert sma
    assert all(r.value is None for r in sma)


def test_cache_skips_recompute():
    pipe = FeaturePipeline(use_cache=True)
    bars = _bars(list(range(1, 40)))
    pipe.compute_symbol("X", bars)
    assert pipe._cache  # populated
    # second run returns identical values from cache
    again = pipe.compute_symbol("X", bars)
    assert all(r.value == pipe._cache[(r.symbol, r.feature, r.version, r.timestamp)] for r in again)


def test_incremental_since_only_new_timestamps():
    bars = _bars(list(range(1, 40)))
    cutoff = bars[30].timestamp
    rows = FeaturePipeline().compute_symbol("X", bars, since=cutoff)
    assert rows
    assert all(r.timestamp > cutoff for r in rows)


# ── store round-trip + point-in-time read ─────────────────────────────────────


def test_store_roundtrip_and_point_in_time():
    store = FeatureStore(":memory:")
    store.sync_definitions(all_features())
    bars = _bars(list(range(1, 40)))
    rows = FeaturePipeline().compute_symbol("AAPL", bars)
    written = store.write_values(rows)
    assert written > 0  # Nones skipped, real values stored

    as_of = bars[25].timestamp
    got = store.read_values("AAPL", "sma_20", as_of=as_of)
    assert got
    assert all(r["timestamp"] <= as_of for r in got)

    xs = store.cross_section("sma_20", as_of=bars[-1].timestamp)
    assert any(r["symbol"] == "AAPL" for r in xs)
    store.close()


def test_registry_populated_and_documented():
    feats = all_features()
    assert len(feats) >= 18
    for f in feats:  # quant docs are mandatory
        assert f.spec.economic_intuition
        assert f.spec.failure_modes
