"""Invariants of the controls: risk breakers, borrow filter, state, config.

These are the parts that exist to stop the programme rather than to run it. A
control that has never been shown to fire is not a control.
"""

from __future__ import annotations

import json
import os
import tempfile
from itertools import pairwise
from pathlib import Path

import pandas as pd
import pytest

from mentisrex.programme import execution, risk
from mentisrex.programme.config import RAMP, ConfigError, ProgrammeError, load_config
from mentisrex.programme.state import ProgrammeState, StateStore, halt, restart

pytestmark = pytest.mark.unit

# Snapshotted at module-collection time, i.e. before any test in the session
# has executed. Used by test_environment_is_not_mutated_by_the_suite below to
# tell "state/ already existed before this run" (e.g. a prior manual CLI run)
# apart from "this test session itself wrote it" — only the latter is a bug.
_STATE_EXISTED_BEFORE_SESSION = Path("state").exists()


def _clean_inputs(**overrides) -> risk.RiskInputs:
    base = {
        "as_of": pd.Timestamp("2026-08-21"),
        "drawdown": 0.05,
        "daily_return": -0.004,
        "realised_vol_21d": 0.22,
        "proposed_gross": 2.70,
        "proposed_net": 1.30,
        "max_abs_position": 0.05,
        "proposed_turnover": 0.08,
        "n_eligible": 590,
        "panel_staleness_days": 0,
        "realised_cost_bps": 5.0,
        "base_cap": 2.75,
    }
    base.update(overrides)
    return risk.RiskInputs(**base)


# ── risk ──────────────────────────────────────────────────────────────────────


def test_clean_inputs_fire_nothing():
    cfg = load_config().risk
    verdict = risk.evaluate(_clean_inputs(), cfg)
    assert verdict.breaches == ()
    assert verdict.effective_cap == pytest.approx(2.75)
    assert not verdict.halted


_TRIPS = {
    "DRAWDOWN_WARN": {"drawdown": 0.22},
    "DRAWDOWN_DERISK": {"drawdown": 0.30},
    "DRAWDOWN_HALT": {"drawdown": 0.40},
    "DAILY_LOSS_WARN": {"daily_return": -0.06},
    "DAILY_LOSS_HALT": {"daily_return": -0.12},
    "VOL_CEILING": {"realised_vol_21d": 0.50},
    "GROSS_HARD": {"proposed_gross": 3.10},
    "NET_HARD": {"proposed_net": 2.60},
    "POSITION_HARD": {"max_abs_position": 0.30},
    "TURNOVER_SPIKE": {"proposed_turnover": 0.70},
    "DATA_STALE": {"panel_staleness_days": 9},
    "UNIVERSE_COLLAPSE": {"n_eligible": 100},
    "COST_DIVERGENCE": {"realised_cost_bps": 25.0},
}


def test_breaker_codes_are_exactly_thirteen():
    assert len(risk.BREAKER_CODES) == 13
    assert set(_TRIPS) == set(risk.BREAKER_CODES)


@pytest.mark.parametrize("code", sorted(_TRIPS))
def test_all_thirteen_breakers_fire(code):
    """Every breaker must be demonstrably reachable from a realistic input."""
    cfg = load_config().risk
    verdict = risk.evaluate(_clean_inputs(**_TRIPS[code]), cfg)
    assert code in {b.code for b in verdict.breaches}


def test_risk_halt_produces_no_orders():
    """A HALT drives the effective cap to zero — that is the mechanism by which
    the 15:35 gate produces no orders at 15:42."""
    cfg = load_config().risk
    verdict = risk.evaluate(_clean_inputs(drawdown=0.40), cfg)
    assert verdict.halted
    assert verdict.effective_cap == 0.0


def test_risk_derisk_halves_cap():
    cfg = load_config().risk
    verdict = risk.evaluate(_clean_inputs(drawdown=0.30), cfg)
    assert not verdict.halted
    assert verdict.effective_cap == pytest.approx(2.75 * cfg.derisk_multiplier)


def test_halt_beats_derisk():
    cfg = load_config().risk
    verdict = risk.evaluate(_clean_inputs(drawdown=0.40, realised_vol_21d=0.50), cfg)
    assert verdict.halted
    assert verdict.effective_cap == 0.0


def test_deployment_ramp_is_monotone_and_clamped():
    caps = [risk.deployment_cap(q) for q in range(len(RAMP) + 3)]
    assert caps[: len(RAMP)] == list(RAMP)
    assert all(b >= a for a, b in pairwise(caps))
    assert caps[-1] == RAMP[-1]


def test_sleeve_health_never_zeroes_a_sleeve():
    """A sleeve at zero can never demonstrate recovery, and momentum's worst
    twelve-month windows are historically followed by its best."""
    cfg = load_config().risk
    dates = pd.bdate_range("2023-01-01", periods=800)
    dying = pd.Series(-0.004, index=dates)
    healthy = pd.Series(0.002, index=dates)
    out = risk.sleeve_health({"S5": dying, "S1": healthy}, dates[-1], cfg)
    assert out["S5"] > 0.0
    assert out["S5"] <= 1.0
    assert out["S1"] == pytest.approx(1.0)


# ── borrow filter ─────────────────────────────────────────────────────────────


def _neutral_target(config, n: int = 20) -> pd.Series:
    names = [f"N{i:02d}" for i in range(n)]
    values = [0.01] * (n // 2) + [-0.01] * (n // 2)
    target = pd.Series(values, index=names, dtype="float64")
    target[config.universe.benchmark] = 1.50
    return target


def test_borrow_filter_preserves_neutrality():
    config = load_config()
    target = _neutral_target(config)
    shorts = [s for s in target.index if target[s] < 0]
    shortable = {s: (i % 3 != 0) for i, s in enumerate(shorts)}

    filtered = execution.borrow_filter(target, shortable, config, config.universe.benchmark)
    non_bench = filtered.drop(labels=[config.universe.benchmark])
    active = non_bench[non_bench != 0.0]
    assert abs(active.sum()) < 1e-9, "cross-sectional book left directional after the filter"


def test_borrow_filter_never_raises_gross():
    config = load_config()
    target = _neutral_target(config)
    shorts = [s for s in target.index if target[s] < 0]
    shortable = dict.fromkeys(shorts, False)

    before = float(target.abs().sum())
    after = float(
        execution.borrow_filter(target, shortable, config, config.universe.benchmark).abs().sum()
    )
    assert after <= before + 1e-12


def test_borrow_filter_fails_closed_on_unknown_symbols():
    """Availability that was never confirmed is not availability."""
    config = load_config()
    target = _neutral_target(config)
    filtered = execution.borrow_filter(target, {}, config, config.universe.benchmark)
    non_bench = filtered.drop(labels=[config.universe.benchmark])
    assert (non_bench[non_bench < 0].abs().sum()) == pytest.approx(0.0)


def test_orders_below_the_minimum_are_suppressed():
    config = load_config()
    names = ["AAA", "BBB", "CCC"]
    target = pd.Series([0.10, 0.0001, -0.10], index=names, dtype="float64")
    current = pd.Series(0.0, index=names, dtype="float64")
    prices = pd.Series([50.0, 20.0, 75.0], index=names, dtype="float64")

    order_set = execution.build_orders(
        target, current, 1_000_000.0, prices, config, pd.Timestamp("2026-08-21")
    )
    traded = {o.symbol for o in order_set.orders}
    assert "BBB" not in traded, "$100 order should have been suppressed under the $250 floor"
    assert traded == {"AAA", "CCC"}
    assert order_set.target_weights["BBB"] == pytest.approx(current["BBB"])


# ── state ─────────────────────────────────────────────────────────────────────


def test_state_roundtrip_is_atomic():
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(tmp)
        state = ProgrammeState(
            high_water_mark=1_250_000.0, nav=1_000_000.0, quarters_live=2,
            first_trade_date="2026-01-05", halted=False, halt_reason=None,
            sleeve_health={"S5": 0.5}, last_run_date="2026-08-21",
            config_fingerprint="abc123",
        )
        store.save(state)
        loaded = store.load()
        assert loaded == state
        assert loaded.drawdown == pytest.approx(0.2)
        # An atomic write leaves no partial file behind for a reader to observe.
        leftovers = [p.name for p in Path(tmp).iterdir() if p.suffix not in {".json", ".jsonl"}]
        assert leftovers == []


def test_corrupt_state_raises_rather_than_resetting():
    """Silently resetting the high-water mark would disarm every drawdown
    breaker at exactly the moment they are needed."""
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(tmp)
        store.save(store.load())
        target = next(p for p in Path(tmp).iterdir() if p.suffix == ".json")
        target.write_text("{not json")
        with pytest.raises(ProgrammeError):
            store.load()


def test_restart_requires_operator_and_note():
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(tmp)
        halt(store, "DRAWDOWN_HALT")
        assert store.load().halted
        for operator, note in [("", "x"), ("x", ""), ("   ", "   ")]:
            with pytest.raises(ConfigError):
                restart(store, operator, note)
        assert store.load().halted, "a refused restart must leave the halt in place"
        restart(store, "ID", "reviewed the 2026-08-21 halt")
        assert not store.load().halted


def test_audit_log_is_append_only():
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(tmp)
        for i in range(5):
            store.append_audit({"event": "run", "n": i})
        path = Path(tmp) / "audit.jsonl"
        lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        assert len(lines) == 5
        assert [rec["n"] for rec in lines] == [0, 1, 2, 3, 4]
        assert all("ts" in rec for rec in lines)


# ── config ────────────────────────────────────────────────────────────────────


def test_config_fingerprint_changes_with_any_field():
    """A fingerprint that misses a field cannot do its job, which is letting a
    performance change be attributed to a parameter change or ruled out."""
    base = load_config()
    baseline = base.fingerprint()
    perturbations = {
        "costs.one_way_bps": 7.5,
        "allocator.k_core": 4.5,
        "allocator.gross_cap": 2.5,
        "risk.drawdown_halt": 0.36,
        "financing.borrow_fee": 0.01,
        "execution.signal_to_trade_lag": 3,
        "signals.momentum_lookback": 252,
        "universe.min_dollar_volume": 5e6,
    }
    for path, value in perturbations.items():
        assert base.with_overrides(**{path: value}).fingerprint() != baseline, path


def test_unknown_override_path_is_rejected():
    with pytest.raises(ConfigError):
        load_config().with_overrides(**{"costs.no_such_field": 1.0})


def test_rungs_match_the_specification_ladder():
    """Specification Table 7. These are the six one-line configuration changes
    that move the programme up the deployment ladder."""
    expected = {
        "deploy": (4.00, 1.60, 1.00),
        "conservative": (4.00, 1.60, 1.50),
        "mandate": (4.00, 2.40, 2.00),
        "standard": (4.00, 3.00, 2.50),
        "recommended": (4.00, 3.60, 2.75),
        "aggressive": (4.00, 4.00, 3.00),
    }
    for name, (k_core, k_sat, cap) in expected.items():
        alloc = load_config().with_rung(name).allocator
        assert (alloc.k_core, alloc.k_satellite, alloc.gross_cap) == (k_core, k_sat, cap)


def test_quality_gate_fatals(panel, mask, config):
    """Each fatal code must be reachable, and a healthy panel must clear."""
    from mentisrex.programme.data import quality_gate

    healthy = quality_gate(panel, mask, config, as_of=panel.index[-1])
    assert healthy.ok, f"synthetic panel should be clean, got {healthy.fatal}"

    stale = quality_gate(panel, mask, config, as_of=panel.index[-1] + pd.Timedelta(days=45))
    assert "STALE_PANEL" in stale.fatal

    empty_mask = mask.copy()
    empty_mask.loc[:, :] = False
    collapsed = quality_gate(panel, empty_mask, config, as_of=panel.index[-1])
    assert "UNIVERSE_COLLAPSE" in collapsed.fatal


def test_environment_is_not_mutated_by_the_suite():
    """Guards against a test writing state into the working tree.

    A pre-existing `state/` (e.g. left over from a manual `mentisrex.programme`
    CLI run before pytest was ever invoked) is not this suite's doing and must
    not fail the check — only `state/` appearing *during* this session, which
    would mean some test wrote runtime state where it shouldn't, is a real bug.
    """
    if _STATE_EXISTED_BEFORE_SESSION:
        pytest.skip("state/ predates this test session (not suite-created)")
    assert not Path("state").exists() or os.environ.get("MRX_ALLOW_STATE") == "1", (
        "state/ did not exist before this test session but exists now — "
        "a test wrote runtime state into the working tree."
    )
