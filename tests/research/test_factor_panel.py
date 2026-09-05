"""M36: ResearchMatrix -> factor-panel adapter (PIT forward returns)."""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import pytest

from mentisrex.research.factor_campaign import FactorCampaign
from mentisrex.research.factor_panel import panels_from_matrices


@dataclass
class FakeMatrix:
    as_of_date: date
    frame: pd.DataFrame
    directions: dict = field(default_factory=dict)


def _matrix(d, values, feature="mom", direction="higher"):
    frame = pd.DataFrame({feature: values}, index=[f"sid{i}" for i in range(len(values))])
    return FakeMatrix(d, frame, {feature: direction})


def _price_book(book):
    """book: {symbol: {date: close}}. close_fn ignores knowledge_date (test data
    has no splits), symbol_fn is identity sid->sid."""

    def close_fn(sym, as_of, knowledge_date=None):
        return book.get(sym, {}).get(as_of)

    def symbol_fn(sid, as_of):
        return sid

    return close_fn, symbol_fn


def test_builds_aligned_panels_and_drops_last_date():
    d1, d2, d3 = date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1)
    ms = [_matrix(d1, [1.0, 2.0, 3.0]), _matrix(d2, [3.0, 2.0, 1.0]), _matrix(d3, [1.0, 1.0, 1.0])]
    book = {f"sid{i}": {d1: 10.0, d2: 11.0, d3: 12.0} for i in range(3)}
    close_fn, symbol_fn = _price_book(book)
    signals, fwd = panels_from_matrices(ms, "mom", close_fn=close_fn, symbol_fn=symbol_fn)
    assert len(signals) == 2
    assert len(fwd) == 2
    assert fwd[0]["sid0"] == pytest.approx(11.0 / 10.0 - 1.0)


def test_direction_lower_is_negated():
    d1, d2 = date(2020, 1, 1), date(2020, 2, 1)
    ms = [
        _matrix(d1, [1.0, 5.0], feature="ep", direction="lower"),
        _matrix(d2, [1.0, 5.0], feature="ep"),
    ]
    book = {f"sid{i}": {d1: 10.0, d2: 10.0} for i in range(2)}
    close_fn, symbol_fn = _price_book(book)
    signals, _ = panels_from_matrices(ms, "ep", close_fn=close_fn, symbol_fn=symbol_fn)
    assert signals[0]["sid0"] == -1.0
    assert signals[0]["sid1"] == -5.0


def test_missing_forward_price_dropped():
    d1, d2 = date(2020, 1, 1), date(2020, 2, 1)
    ms = [_matrix(d1, [1.0, 2.0]), _matrix(d2, [1.0, 2.0])]
    book = {"sid0": {d1: 10.0, d2: 11.0}}  # sid1 delisted (no prices)
    close_fn, symbol_fn = _price_book(book)
    _, fwd = panels_from_matrices(ms, "mom", close_fn=close_fn, symbol_fn=symbol_fn)
    assert "sid0" in fwd[0]
    assert "sid1" not in fwd[0]


def test_needs_two_matrices():
    with pytest.raises(ValueError):
        panels_from_matrices(
            [_matrix(date(2020, 1, 1), [1.0])],
            "mom",
            close_fn=lambda *a, **k: 1.0,
            symbol_fn=lambda *a: "x",
        )


def test_end_to_end_into_campaign():
    # rising-price names ranked by signal => a real positive-IC factor through the adapter
    import numpy as np

    rng = np.random.default_rng(0)
    dates = [date(2020, m, 1) for m in range(1, 13)]
    N = 30
    book = {f"sid{i}": {} for i in range(N)}
    ms = []
    prev = {f"sid{i}": 100.0 for i in range(N)}
    for d in dates:
        vals = [float(i) for i in range(N)]  # signal = rank
        ms.append(_matrix(d, vals))
        # forward return = signal-driven drift + noise => strong but not perfect IC
        for i in range(N):
            book[f"sid{i}"][d] = prev[f"sid{i}"]
            ret = 0.02 * (i - N / 2) / N + rng.standard_normal() * 0.01
            prev[f"sid{i}"] = prev[f"sid{i}"] * (1.0 + ret)
    close_fn, symbol_fn = _price_book(book)
    signals, fwd = panels_from_matrices(ms, "mom", close_fn=close_fn, symbol_fn=symbol_fn)
    camp = FactorCampaign(":memory:", t_min=2.0)
    try:
        res = camp.run("mom_real", "momentum", signals, fwd)
        assert res.report.ic_mean > 0.3  # strong positive factor
        assert res.status == "PROMISING"
    finally:
        camp.close()
