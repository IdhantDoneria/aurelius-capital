"""Invariants of the signal, sleeve and allocation layers.

The specification requires every one of these to pass before any deployment.
Two of them — the look-ahead truncation test and the perfect-foresight detector
— are checking the rig itself: if the harness is not sensitive to look-ahead,
every other number the harness produces is meaningless.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mentisrex.programme import allocator, signals, sleeves
from mentisrex.programme.config import CORE_SLEEVES, SATELLITE_SLEEVES

pytestmark = pytest.mark.unit

TOL = 1e-9


# ── look-ahead ────────────────────────────────────────────────────────────────


def test_no_lookahead_signals(panel, mask, config):
    """Truncate the panel, recompute, and require every retained value to match.

    This is the single most important test in the suite. A signal that peeks —
    a centred window, a `shift(-1)`, a full-sample mean, a global rank — has a
    different value at date t depending on whether the future was visible when
    it was computed, and that is exactly what truncation exposes.
    """
    cut = panel.index[int(len(panel.index) * 0.7)]
    full = signals.compute_all_signals(panel, mask, config.signals)

    truncated_panel = panel.truncate(cut)
    truncated_mask = mask.loc[mask.index <= cut]
    partial = signals.compute_all_signals(truncated_panel, truncated_mask, config.signals)

    failures = []
    for name in full:
        a, b = full[name], partial[name]
        a = a.loc[a.index <= cut]
        if isinstance(a, pd.DataFrame):
            b = b.reindex(index=a.index, columns=a.columns)
            diff = (a - b).abs().to_numpy()
        else:
            b = b.reindex(a.index)
            diff = (a - b).abs().to_numpy()
        both_nan = np.isnan(a.to_numpy()) & np.isnan(b.to_numpy())
        worst = np.nanmax(np.where(both_nan, 0.0, diff)) if diff.size else 0.0
        nan_mismatch = int((np.isnan(a.to_numpy()) != np.isnan(b.to_numpy())).sum())
        if not (worst <= TOL) or nan_mismatch:
            failures.append(f"{name}: max diff {worst:.3g}, {nan_mismatch} NaN-pattern mismatches")

    assert not failures, "signals differ after truncation:\n  " + "\n  ".join(failures)


def test_eligibility_no_lookahead(panel, mask, config):
    from mentisrex.programme.data import eligibility_mask

    cut = panel.index[int(len(panel.index) * 0.6)]
    partial = eligibility_mask(panel.truncate(cut), config.universe)
    retained = mask.loc[mask.index <= cut]
    assert partial.shape == retained.shape
    assert (partial.to_numpy() == retained.to_numpy()).all()


def test_perfect_foresight_is_detected(panel, mask, config):
    """Feed a deliberately look-ahead signal and require an absurd Sharpe.

    If a signal built from tomorrow's returns does NOT produce a Sharpe far
    beyond anything achievable, the harness is not sensitive to look-ahead and
    no result it produces can be trusted.
    """
    universe = panel.universe_columns()
    future = panel.returns[universe].shift(-config.execution.signal_to_trade_lag)
    cheating = signals.cross_sectional_zscore(future, mask.reindex(columns=universe))
    weights = sleeves.cross_sectional_to_weights(cheating, panel)
    held = sleeves.apply_holding_period(weights, 1, panel.returns)
    ret = sleeves.sleeve_returns(held, panel.returns, config.execution.signal_to_trade_lag).dropna()

    sharpe = ret.mean() / ret.std(ddof=1) * np.sqrt(252)
    assert sharpe > 8.0, f"harness is blind to look-ahead: cheating Sharpe only {sharpe:.2f}"


def test_lag_is_applied_exactly_once(panel, config):
    """Shifting the weights by one row must shift the return series by one row."""
    universe = panel.universe_columns()
    rng = np.random.default_rng(11)
    weights = pd.DataFrame(
        rng.normal(0, 0.01, (len(panel.index), len(universe))),
        index=panel.index, columns=universe,
    )
    lag = config.execution.signal_to_trade_lag
    base = sleeves.sleeve_returns(weights, panel.returns, lag)
    manual = (weights.shift(lag) * panel.returns[universe]).sum(axis=1)
    pd.testing.assert_series_equal(base.dropna(), manual.reindex(base.index).dropna())


# ── sleeve shape ──────────────────────────────────────────────────────────────


def test_cross_sectional_weights_are_exactly_neutral(panel, mask, config):
    """`cross_sectional_to_weights` must return an exactly neutral, gross-1.0 book.

    This is the invariant of the construction itself, checked before any
    holding period is applied.
    """
    raw = signals.compute_all_signals(panel, mask, config.signals)
    for name in SATELLITE_SLEEVES:
        weights = sleeves.cross_sectional_to_weights(raw[name], panel)
        active = weights.loc[weights.abs().sum(axis=1) > 0]
        assert not active.empty, f"{name} produced no active rows"
        assert active.sum(axis=1).abs().max() < 1e-9, f"{name} is not dollar neutral"
        assert (active.abs().sum(axis=1) - 1.0).abs().max() < 1e-9, f"{name} gross is not 1.0"
        assert (weights[panel.benchmark].to_numpy() == 0.0).all(), f"{name} touched the benchmark"


def test_held_cross_sectional_book_stays_near_neutral(built):
    """Between rebalances the book drifts with returns, so exact neutrality is
    the wrong thing to demand of a HELD book — winners grow and losers shrink,
    and a real portfolio does exactly that.

    What must hold is that the drift stays small relative to gross. A large net
    would mean the sleeve had quietly become a directional bet, which is the
    failure the borrow filter also exists to prevent.
    """
    for name in SATELLITE_SLEEVES:
        weights = built[name].weights
        active = weights.loc[weights.abs().sum(axis=1) > 0]
        net = active.sum(axis=1).abs()
        gross = active.abs().sum(axis=1)
        assert (net / gross).max() < 0.10, (
            f"{name} drifted to {(net / gross).max():.1%} net of gross between rebalances"
        )


def test_directional_sleeves_only_touch_benchmark(built, panel):
    universe = panel.universe_columns()
    for name in CORE_SLEEVES:
        others = built[name].weights[universe]
        assert (others.fillna(0.0).to_numpy() == 0.0).all(), f"{name} traded a single name"


# ── caps and cost identities ──────────────────────────────────────────────────


@pytest.mark.parametrize("cap", [1.0, 2.0, 2.75])
def test_gross_cap_never_breached(built, panel, config, cap):
    book = allocator.combine(built, panel, config, effective_cap=cap)
    assert book.gross.max() <= cap + TOL


def test_single_name_cap(built, panel, config):
    book = allocator.combine(built, panel, config)
    universe = panel.universe_columns()
    worst = book.target_weights[universe].abs().to_numpy()
    assert np.nanmax(worst) <= config.allocator.max_position + TOL


def test_benchmark_cap(built, panel, config):
    book = allocator.combine(built, panel, config)
    worst = book.target_weights[panel.benchmark].abs().max()
    assert worst <= config.allocator.max_position_benchmark + TOL


def test_cost_identity(built, panel, config):
    """Modelled cost must equal turnover times the rate, exactly.

    The point of asserting an identity rather than a range is that a cost
    applied to the wrong base — gross instead of traded notional, say — would
    still look plausible in aggregate and would quietly change every net figure
    the programme reports.
    """
    book = allocator.combine(built, panel, config)
    modelled = allocator.transaction_cost(book, config.costs)
    expected = book.turnover * config.costs.one_way_bps / 10_000.0
    assert (modelled - expected).abs().max() < 1e-12


def test_financing_identity(built, panel, config, policy_rates):
    """Recompute the specification's section 2.3 formula by hand and match to 1e-12."""
    book = allocator.combine(built, panel, config)
    modelled = allocator.financing_cost(book, policy_rates, config.financing)

    fin = config.financing
    rate = policy_rates.reindex(book.gross.index).ffill().bfill()
    long_leg, short_leg = book.long_exposure, book.short_exposure
    by_hand = (
        (long_leg - 1.0).clip(lower=0.0) * (rate + fin.margin_spread)
        + short_leg * fin.borrow_fee
        - short_leg * (rate - fin.rebate_spread).clip(lower=0.0)
    ) / fin.trading_days
    assert (modelled - by_hand).abs().max() < 1e-12


def test_effective_breadth_recovers_known_structure():
    """Ten independent streams score near ten; two blocks of five score near two."""
    rng = np.random.default_rng(5)
    independent = pd.DataFrame(rng.normal(0, 0.01, (2000, 10)))
    assert allocator.effective_breadth(independent) > 9.0

    a, b = rng.normal(0, 0.01, 2000), rng.normal(0, 0.01, 2000)
    blocks = pd.DataFrame(
        {i: (a if i < 5 else b) + rng.normal(0, 0.0005, 2000) for i in range(10)}
    )
    assert allocator.effective_breadth(blocks) < 3.0
